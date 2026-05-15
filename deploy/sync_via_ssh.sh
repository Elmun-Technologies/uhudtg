#!/usr/bin/env bash
# SSH orqali kodni serverga rsync qiladi va servisni qayta ishga tushiradi.
#
# Bir marta (lokal mashinada):
#   export DEPLOY_SSH='ubuntu@SERVER_IP'    # yoki root@...
#   export DEPLOY_PATH='/opt/comfort-bot'   # ixtiyoriy, default shu
#   export DEPLOY_SERVICE='comfort-bot'     # ixtiyoriy, systemd unit
#   ./deploy/sync_via_ssh.sh
#
# Talablar: SSH kalit bilan kirish; serverda NOPASSWD sudo yoki root.
set -euo pipefail

: "${DEPLOY_SSH:?DEPLOY_SSH o‘rnatilmagan (masalan: export DEPLOY_SSH=ubuntu@203.0.113.10)}"
REMOTE_DIR="${DEPLOY_PATH:-/opt/comfort-bot}"
SERVICE="${DEPLOY_SERVICE:-comfort-bot}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/OY - Comfort bot"
[[ -f "$SRC/bot.py" ]] || { echo "Yo‘q: $SRC/bot.py"; exit 1; }

echo "[rsync] $SRC/ -> ${DEPLOY_SSH}:${REMOTE_DIR}/"
rsync -avz \
  --exclude '.git/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'comfort_bot.db' \
  "$SRC/" "${DEPLOY_SSH}:${REMOTE_DIR}/"

echo "[ssh] systemctl restart ${SERVICE}"
ssh "$DEPLOY_SSH" "sudo systemctl restart '${SERVICE}'"
echo "[ok] Tayyor."
