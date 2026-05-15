#!/usr/bin/env bash
# =============================================================================
# install.sh — полная автоматическая установка Comfort Bot на VPS
# Запуск в VNC-консоли:
#   sudo bash install.sh
# =============================================================================
set -euo pipefail

APP_DIR="/opt/comfort-bot"
G='\033[1;32m'; Y='\033[1;33m'; B='\033[1;34m'; R='\033[1;31m'; N='\033[0m'
ok()   { echo -e "${G}[OK]${N}  $*"; }
info() { echo -e "${B}[..]${N}  $*"; }
warn() { echo -e "${Y}[!!]${N}  $*"; }
die()  { echo -e "${R}[ERR]${N} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запустите: sudo bash install.sh"

# ─── 1. Зависимости ──────────────────────────────────────────────────────────
info "Обновляю пакеты…"
apt-get update -qq
apt-get install -y -qq git curl ca-certificates

# ─── 2. Docker ───────────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
    ok "Docker уже установлен."
else
    info "Устанавливаю Docker…"
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    ok "Docker установлен."
fi

# ─── 3. Код ──────────────────────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    info "Обновляю код…"
    git -C "$APP_DIR" fetch origin main
    git -C "$APP_DIR" reset --hard origin/main
else
    info "Клонирую репозиторий…"
    git clone --depth 1 --branch main \
        https://github.com/Elmun-Technologies/comfort-txt.git "$APP_DIR"
fi
ok "Код скачан."

# ─── 4. .env ─────────────────────────────────────────────────────────────────
info "Создаю конфигурацию…"
cd "$APP_DIR"

# Определяем публичный IP сервера
SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')

cat > "$APP_DIR/.env" <<EOF
BOT_TOKEN=8770624239:
MOYSKLAD_TOKEN=
WEBHOOK_HOST=http://${SERVER_IP}
WEBHOOK_PATH=/moysklad/webhook
WEBHOOK_PORT=8080
WEBHOOK_SECRET=mySecretKey2024comfort
DB_PATH=/data/comfort_bot.db
ADMIN_IDS=5627275608
COMPANY_PHONE=+998958220000
DOMAIN=${SERVER_IP}
EOF

ok "Конфиг .env создан (IP: ${SERVER_IP})."

# ─── 5. Логотип ──────────────────────────────────────────────────────────────
mkdir -p "$APP_DIR/assets"
SRC="$APP_DIR/OY - Comfort bot/assets/logo.png"
[ -f "$SRC" ] && cp "$SRC" "$APP_DIR/assets/logo.png" && ok "Логотип скопирован."

# ─── 6. Запуск ───────────────────────────────────────────────────────────────
info "Собираю и запускаю контейнеры…"
docker compose -f "$APP_DIR/docker-compose.yml" up --build -d

sleep 4

# ─── 7. Итог ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${G}════════════════════════════════════════════${N}"
echo -e "${G}   Comfort Bot успешно запущен!              ${N}"
echo -e "${G}════════════════════════════════════════════${N}"
echo ""
docker compose -f "$APP_DIR/docker-compose.yml" ps
echo ""
echo "  Логи:        docker compose -f $APP_DIR/docker-compose.yml logs -f bot"
echo "  Перезапуск:  docker compose -f $APP_DIR/docker-compose.yml restart bot"
echo ""
