#!/usr/bin/env bash
# =============================================================================
# setup.sh — полная установка Comfort Bot на чистый VPS (Ubuntu/Debian)
# Запуск (один раз, от root):
#   curl -fsSL https://raw.githubusercontent.com/Elmun-Technologies/comfort-txt/main/deploy/setup.sh | bash
# =============================================================================
set -euo pipefail

REPO="https://github.com/Elmun-Technologies/comfort-txt.git"
BRANCH="main"
APP_DIR="/opt/comfort-bot"

# ─── цвета ────────────────────────────────────────────────────────────────────
G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;34m'; N='\033[0m'
ok()   { echo -e "${G}[OK]${N}  $*"; }
info() { echo -e "${B}[..]${N}  $*"; }
warn() { echo -e "${Y}[!!]${N}  $*"; }
die()  { echo -e "${R}[ERR]${N} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запустите от root: sudo bash setup.sh"

# ─── 1. Docker ────────────────────────────────────────────────────────────────
install_docker() {
    if command -v docker &>/dev/null; then
        ok "Docker уже установлен: $(docker --version)"
        return
    fi
    info "Устанавливаю Docker…"
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    ok "Docker установлен."
}

# ─── 2. Код ──────────────────────────────────────────────────────────────────
deploy_code() {
    if [ -d "$APP_DIR/.git" ]; then
        info "Обновляю репозиторий…"
        git -C "$APP_DIR" fetch origin "$BRANCH"
        git -C "$APP_DIR" reset --hard "origin/$BRANCH"
    else
        info "Клонирую репозиторий в $APP_DIR…"
        git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR"
    fi
    ok "Код актуален."
}

# ─── 3. Домен ─────────────────────────────────────────────────────────────────
configure_env() {
    cd "$APP_DIR"

    # Берём .env из подпапки проекта (там хранятся реальные токены)
    if [ ! -f ".env" ]; then
        cp "OY - Comfort bot/.env" .env
    fi

    # Спрашиваем только домен
    echo ""
    echo "─────────────────────────────────────────────────"
    echo " Введите домен вашего сервера (пример: bot.example.com)"
    echo " Если домена нет — просто нажмите Enter (бот запустится,"
    echo " но вебхуки МойСклад работать не будут без HTTPS-домена)."
    echo "─────────────────────────────────────────────────"
    read -rp " Домен: " DOMAIN
    DOMAIN="${DOMAIN:-localhost}"

    # Записываем DOMAIN и обновляем WEBHOOK_HOST в .env
    if grep -q "^DOMAIN=" .env; then
        sed -i "s|^DOMAIN=.*|DOMAIN=${DOMAIN}|" .env
    else
        echo "DOMAIN=${DOMAIN}" >> .env
    fi

    if [ "$DOMAIN" != "localhost" ]; then
        sed -i "s|^WEBHOOK_HOST=.*|WEBHOOK_HOST=https://${DOMAIN}|" .env
    fi

    # DB внутри именованного Docker-тома
    sed -i "s|^DB_PATH=.*|DB_PATH=/data/comfort_bot.db|" .env

    ok "Конфиг .env готов (домен: $DOMAIN)."
}

# ─── 4. Логотип ───────────────────────────────────────────────────────────────
prepare_assets() {
    mkdir -p "$APP_DIR/assets"
    if [ ! -f "$APP_DIR/assets/logo.png" ]; then
        # Пытаемся взять логотип из подпапки проекта
        if [ -f "$APP_DIR/OY - Comfort bot/assets/logo.png" ]; then
            cp "$APP_DIR/OY - Comfort bot/assets/logo.png" "$APP_DIR/assets/logo.png"
            ok "Логотип скопирован."
        else
            warn "Логотип не найден. Положите файл сюда: $APP_DIR/assets/logo.png"
        fi
    fi
}

# ─── 5. Запуск ────────────────────────────────────────────────────────────────
start_services() {
    cd "$APP_DIR"
    info "Собираю и запускаю контейнеры…"
    docker compose pull caddy --quiet
    docker compose up --build -d
    sleep 3

    if docker compose ps | grep -q "running\|Up"; then
        ok "Контейнеры запущены!"
    else
        warn "Что-то пошло не так. Смотрите логи:"
        docker compose logs --tail=30
    fi
}

# ─── Итог ─────────────────────────────────────────────────────────────────────
print_summary() {
    cd "$APP_DIR"
    DOMAIN=$(grep "^DOMAIN=" .env | cut -d= -f2)
    echo ""
    echo -e "${G}════════════════════════════════════════════${N}"
    echo -e "${G}  Comfort Bot успешно развёрнут!${N}"
    echo -e "${G}════════════════════════════════════════════${N}"
    echo ""
    echo "  Бот:         запущен, polling Telegram"
    if [ "$DOMAIN" != "localhost" ]; then
    echo "  Вебхук URL:  https://${DOMAIN}/moysklad/webhook"
    echo "  SSL:         Caddy получит сертификат автоматически"
    fi
    echo ""
    echo "  Полезные команды:"
    echo "    Логи бота:      docker compose -f $APP_DIR/docker-compose.yml logs -f bot"
    echo "    Перезапуск:     docker compose -f $APP_DIR/docker-compose.yml restart bot"
    echo "    Остановка:      docker compose -f $APP_DIR/docker-compose.yml down"
    echo ""
    if [ "$DOMAIN" != "localhost" ]; then
    echo "  В МойСклад → Вебхуки укажите:"
    echo "    https://${DOMAIN}/moysklad/webhook?secret=$(grep WEBHOOK_SECRET $APP_DIR/.env | cut -d= -f2)"
    fi
    echo ""
}

# ─── main ─────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${B}══════════════════════════════════════════════${N}"
    echo -e "${B}   Comfort Textile Bot — Установка на VPS${N}"
    echo -e "${B}══════════════════════════════════════════════${N}"
    echo ""

    install_docker
    deploy_code
    configure_env
    prepare_assets
    start_services
    print_summary
}

main "$@"
