#!/usr/bin/env bash
# deploy_fix.sh — применить фикс DB persistence + currency conversion +
# восстановить пользователей из MoySklad.
#
# Запускать на проде, в директории с docker-compose.yml:
#     git pull origin claude/check-commit-01c5c95-X8ARA
#     bash deploy_fix.sh
#
# Скрипт идемпотентен: можно перезапускать.

set -euo pipefail

# ─── конфигурация ──────────────────────────────────────────────────────────
COMPOSE_SERVICE="${COMPOSE_SERVICE:-bot}"
ENV_FILE="${ENV_FILE:-.env}"
TARGET_DB_PATH="/data/comfort_bot.db"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

# ─── helpers ───────────────────────────────────────────────────────────────
ts() { date +%Y%m%d-%H%M%S; }
log() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }
ok()  { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
warn(){ printf "\033[1;33m!\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; }

# ─── проверки ──────────────────────────────────────────────────────────────
log "Проверка окружения"

if [[ ! -f docker-compose.yml ]]; then
  err "docker-compose.yml не найден в $(pwd). Запустите из корня проекта."
  exit 1
fi
ok "docker-compose.yml найден"

if [[ ! -f "$ENV_FILE" ]]; then
  err "$ENV_FILE не найден. Создайте его перед запуском."
  exit 1
fi
ok ".env найден"

if ! command -v docker >/dev/null 2>&1; then
  err "docker не установлен"; exit 1
fi
if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  err "docker compose / docker-compose не установлен"; exit 1
fi

# Унифицируем команду
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  DC="docker-compose"
fi
ok "docker compose ok ($DC)"

# Имя контейнера бота
BOT_CID="$($DC ps -q "$COMPOSE_SERVICE" 2>/dev/null || true)"
if [[ -z "$BOT_CID" ]]; then
  warn "Контейнер сервиса '$COMPOSE_SERVICE' сейчас не запущен"
else
  ok "Контейнер бота: $BOT_CID"
fi

# ─── шаг 1. бэкап текущей БД из контейнера (если жив) ─────────────────────
log "Шаг 1/5. Бэкап текущей БД"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE=""

if [[ -n "$BOT_CID" ]]; then
  if docker exec "$BOT_CID" test -f /data/comfort_bot.db; then
    BACKUP_FILE="$BACKUP_DIR/comfort_bot.db.$(ts).from_volume"
    docker cp "$BOT_CID:/data/comfort_bot.db" "$BACKUP_FILE"
    ok "Бэкап БД из тома /data → $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
  elif docker exec "$BOT_CID" test -f /app/comfort_bot.db; then
    BACKUP_FILE="$BACKUP_DIR/comfort_bot.db.$(ts).from_app_layer"
    docker cp "$BOT_CID:/app/comfort_bot.db" "$BACKUP_FILE"
    SIZE_BYTES=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE")
    if [[ "$SIZE_BYTES" -gt 4096 ]]; then
      ok "БД из эфемерного слоя /app спасена → $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
      ok "Эту БД восстановим в /data на шаге 4"
    else
      warn "БД в /app слишком маленькая ($SIZE_BYTES bytes), скорее всего это свежая пустая. Будем восстанавливать через restore_users.py"
      rm -f "$BACKUP_FILE"
      BACKUP_FILE=""
    fi
  else
    warn "БД нет ни в /data, ни в /app — будем восстанавливать через restore_users.py"
  fi
else
  warn "Контейнер не запущен, бэкап пропущен"
fi

# ─── шаг 2. правка DB_PATH в .env ─────────────────────────────────────────
log "Шаг 2/5. Проверка DB_PATH в $ENV_FILE"

CURRENT_DB_PATH="$(grep -E '^DB_PATH=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
if [[ "$CURRENT_DB_PATH" == "$TARGET_DB_PATH" ]]; then
  ok "DB_PATH уже = $TARGET_DB_PATH"
else
  ENV_BACKUP="$BACKUP_DIR/.env.$(ts).bak"
  cp "$ENV_FILE" "$ENV_BACKUP"
  ok "Бэкап .env → $ENV_BACKUP"

  if grep -qE '^DB_PATH=' "$ENV_FILE"; then
    # экранируем / в TARGET_DB_PATH для sed
    ESCAPED="$(printf '%s\n' "$TARGET_DB_PATH" | sed 's:[\/&]:\\&:g')"
    sed -i.tmp -E "s|^DB_PATH=.*|DB_PATH=${ESCAPED}|" "$ENV_FILE"
    rm -f "${ENV_FILE}.tmp"
  else
    printf "\nDB_PATH=%s\n" "$TARGET_DB_PATH" >> "$ENV_FILE"
  fi
  ok "DB_PATH установлен в $TARGET_DB_PATH (было: ${CURRENT_DB_PATH:-<отсутствовал>})"
fi

# ─── шаг 3. пересборка ────────────────────────────────────────────────────
log "Шаг 3/5. Пересборка и запуск контейнера"
$DC up -d --build
ok "docker compose up -d --build выполнен"

# подождём, пока контейнер инициализируется
sleep 3
NEW_BOT_CID="$($DC ps -q "$COMPOSE_SERVICE")"
if [[ -z "$NEW_BOT_CID" ]]; then
  err "Контейнер бота не поднялся. Логи:"
  $DC logs --tail 100 "$COMPOSE_SERVICE" || true
  exit 1
fi
ok "Контейнер бота: $NEW_BOT_CID"

# ждём, пока init_db отработает (timeout 30s)
log "Ожидание Database initialised…"
for i in {1..30}; do
  if docker logs "$NEW_BOT_CID" 2>&1 | grep -q "Database initialised"; then
    ok "БД инициализирована"
    break
  fi
  sleep 1
done

# ─── шаг 4. восстановление БД ─────────────────────────────────────────────
log "Шаг 4/5. Восстановление пользователей"

if [[ -n "$BACKUP_FILE" && "$BACKUP_FILE" == *from_app_layer ]]; then
  warn "Сейчас перезапишем свежесозданную пустую БД спасённой из /app"
  read -r -p "Продолжить? [y/N] " confirm
  if [[ "${confirm,,}" == "y" ]]; then
    docker cp "$BACKUP_FILE" "$NEW_BOT_CID:/data/comfort_bot.db"
    docker exec "$NEW_BOT_CID" chmod 666 /data/comfort_bot.db
    ok "Старая БД положена в /data/comfort_bot.db"
    log "Перезапуск контейнера, чтобы он прочитал новую БД"
    $DC restart "$COMPOSE_SERVICE"
    sleep 3
  else
    warn "Восстановление из бэкапа отменено, упадём в restore_users.py"
    BACKUP_FILE=""
  fi
fi

if [[ -z "$BACKUP_FILE" || "$BACKUP_FILE" == *from_volume ]]; then
  log "Запуск restore_users.py (восстановление из MoySklad)"
  docker exec "$NEW_BOT_CID" python restore_users.py
  ok "restore_users.py отработал"
fi

# ─── шаг 5. проверки ──────────────────────────────────────────────────────
log "Шаг 5/5. Проверка"

echo
echo "Файл БД в томе:"
docker exec "$NEW_BOT_CID" ls -la /data/comfort_bot.db || warn "БД в /data не найдена!"

echo
echo "Кол-во пользователей в БД:"
docker exec "$NEW_BOT_CID" python -c "
import asyncio, aiosqlite
from config import DB_PATH
async def main():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(*) FROM users') as cur:
            row = await cur.fetchone()
            print(f'  users: {row[0]}')
        async with db.execute('SELECT COUNT(*) FROM users WHERE moysklad_counterparty_id IS NOT NULL') as cur:
            row = await cur.fetchone()
            print(f'  с привязкой к MS: {row[0]}')
asyncio.run(main())
"

echo
echo "Последние строки лога бота:"
$DC logs --tail 30 "$COMPOSE_SERVICE" | sed 's/^/    /'

cat <<EOF


$(printf '\033[1;32m')═══════════════════════════════════════════════════════════════════
  Готово. Что сделать дальше:
═══════════════════════════════════════════════════════════════════$(printf '\033[0m')

  1. Создайте в МойСклад тестовый платёж от любого восстановленного
     клиента — он должен получить уведомление в Telegram, не нажимая
     /start.

  2. Дождитесь дневного отчёта в 20:00 (Asia/Tashkent) или временно
     поставьте DAILY_REPORT_HOUR/DAILY_REPORT_MINUTE на ближайшие
     минуты в .env, перезапустите контейнер ($DC up -d) и проверьте,
     что суммы реалистичные (не миллионы). После проверки верните 20:00.

  3. Посмотрите INFO-лог aggregate_documents:
        docker logs \$($DC ps -q $COMPOSE_SERVICE) 2>&1 | grep "aggregate_documents.*sample"
     Должны быть строки с rate={'value': <небольшое_число>}.
     Если у каких-то типов value отсутствует — пришлите эти строки,
     нужно будет добавить фолбэк.

  Все бэкапы лежат в: $BACKUP_DIR/

EOF
