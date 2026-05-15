#!/usr/bin/env bash
# =============================================================================
# deploy.sh — one-shot server setup for Comfort Textile Bot
# Tested on Ubuntu 22.04 / Debian 12 (Airnet Nano VPS)
#
# Usage (run as root or via sudo):
#   chmod +x deploy.sh
#   sudo ./deploy.sh
# =============================================================================
set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/elmun-technologies/comfort-txt.git"
BRANCH="main"
APP_DIR="/opt/comfort-bot"
BOT_USER="comfortbot"
SERVICE_NAME="comfort-bot"
PYTHON_MIN="3.11"

# ─── Helpers ──────────────────────────────────────────────────────────────────
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[ OK ]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
die()   { echo -e "\033[1;31m[ERR ]\033[0m  $*" >&2; exit 1; }

require_root() {
    [ "$(id -u)" -eq 0 ] || die "Run this script as root (sudo ./deploy.sh)"
}

# ─── 1. System packages ───────────────────────────────────────────────────────
install_packages() {
    info "Updating package lists…"
    apt-get update -qq

    info "Installing system dependencies…"
    apt-get install -y -qq \
        python3 python3-pip python3-venv python3-dev \
        git curl nginx certbot python3-certbot-nginx \
        libffi-dev libssl-dev

    # Verify Python version
    PY_VER=$(python3 --version | awk '{print $2}')
    info "Python version: $PY_VER"
}

# ─── 2. Dedicated system user ─────────────────────────────────────────────────
create_user() {
    if id "$BOT_USER" &>/dev/null; then
        ok "User '$BOT_USER' already exists, skipping."
    else
        info "Creating system user '$BOT_USER'…"
        useradd --system --no-create-home --shell /usr/sbin/nologin "$BOT_USER"
        ok "User '$BOT_USER' created."
    fi
}

# ─── 3. Clone / update repository ────────────────────────────────────────────
deploy_code() {
    if [ -d "$APP_DIR/.git" ]; then
        info "Repository found — pulling latest '$BRANCH'…"
        git -C "$APP_DIR" fetch origin
        git -C "$APP_DIR" checkout "$BRANCH"
        git -C "$APP_DIR" reset --hard "origin/$BRANCH"
    else
        info "Cloning repository into $APP_DIR…"
        git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    fi

    # The bot code lives in a subdirectory — flatten if needed
    BOT_SRC="$APP_DIR/OY - Comfort bot"
    if [ -d "$BOT_SRC" ]; then
        info "Moving bot source from subdirectory…"
        shopt -s dotglob
        cp -a "$BOT_SRC"/. "$APP_DIR"/
        shopt -u dotglob
    fi
}

# ─── 4. Python virtual environment & dependencies ────────────────────────────
setup_venv() {
    info "Creating Python virtual environment…"
    python3 -m venv "$APP_DIR/venv"

    info "Installing Python dependencies…"
    "$APP_DIR/venv/bin/pip" install --upgrade pip -q
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
    ok "Dependencies installed."
}

# ─── 5. .env file ─────────────────────────────────────────────────────────────
setup_env() {
    if [ -f "$APP_DIR/.env" ]; then
        ok ".env already exists — skipping creation."
        warn "Review $APP_DIR/.env and make sure all values are correct."
    else
        info "Creating .env from example…"
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        warn ">>> IMPORTANT: Edit $APP_DIR/.env and fill in real credentials! <<<"
        warn "    BOT_TOKEN, MOYSKLAD_TOKEN, WEBHOOK_HOST, WEBHOOK_SECRET, ADMIN_IDS"
    fi
}

# ─── 6. Assets directory ──────────────────────────────────────────────────────
setup_assets() {
    mkdir -p "$APP_DIR/assets"
    if [ ! -f "$APP_DIR/assets/logo.png" ]; then
        warn "Logo not found. Place your logo at $APP_DIR/assets/logo.png"
        warn "(PNG, ~200×200 px recommended)"
    fi
}

# ─── 7. Permissions ───────────────────────────────────────────────────────────
fix_permissions() {
    info "Setting ownership to $BOT_USER…"
    chown -R "$BOT_USER":"$BOT_USER" "$APP_DIR"
    chmod 600 "$APP_DIR/.env"
}

# ─── 8. systemd service ───────────────────────────────────────────────────────
install_service() {
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    info "Installing systemd service…"

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Comfort Textile Telegram Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}
EnvironmentFile=${APP_DIR}/.env
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    ok "Service '$SERVICE_NAME' enabled."
}

# ─── 9. Nginx ─────────────────────────────────────────────────────────────────
setup_nginx() {
    NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"

    if [ -f "$NGINX_CONF" ]; then
        ok "Nginx config already exists — skipping."
        return
    fi

    info "Installing Nginx config…"
    cp "$APP_DIR/deploy/nginx.conf" "$NGINX_CONF"
    ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${SERVICE_NAME}"

    # Remove default nginx site if still present
    rm -f /etc/nginx/sites-enabled/default

    nginx -t && systemctl reload nginx
    ok "Nginx configured."

    warn ">>> Remember to replace 'yourdomain.com' in $NGINX_CONF <<<"
    warn "    Then get SSL: certbot --nginx -d yourdomain.com"
}

# ─── 10. Start the bot ────────────────────────────────────────────────────────
start_service() {
    info "Starting ${SERVICE_NAME}…"
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Bot is running!"
    else
        warn "Bot failed to start. Check logs:"
        warn "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────
main() {
    require_root

    info "=== Comfort Textile Bot — Deploy Script ==="

    install_packages
    create_user
    deploy_code
    setup_venv
    setup_env
    setup_assets
    fix_permissions
    install_service
    setup_nginx
    start_service

    echo ""
    ok "=== Deployment complete! ==="
    echo ""
    echo "  Next steps:"
    echo "  1. Edit /opt/comfort-bot/.env  (fill BOT_TOKEN, MOYSKLAD_TOKEN, etc.)"
    echo "  2. Place logo: /opt/comfort-bot/assets/logo.png"
    echo "  3. Edit Nginx: /etc/nginx/sites-available/comfort-bot"
    echo "     Replace 'yourdomain.com' with your actual domain or IP"
    echo "  4. Obtain SSL: certbot --nginx -d yourdomain.com"
    echo "  5. Restart bot: systemctl restart comfort-bot"
    echo "  6. Watch logs:  journalctl -u comfort-bot -f"
    echo ""
}

main "$@"
