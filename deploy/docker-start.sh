#!/usr/bin/env bash
# deploy/docker-start.sh — Comfort Bot ni serverda ishga tushirish
# Ishlatish: bash deploy/docker-start.sh
set -euo pipefail

GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

cd "$(dirname "$0")/.."   # loyiha ildiziga o'tamiz

echo "=== Comfort Bot — Docker deploy ==="

# 1. .env tekshiruvi
[[ -f .env ]] || err ".env fayli topilmadi. Yarating va tokenlarni to'ldiring."
ok ".env mavjud"

for VAR in BOT_TOKEN MOYSKLAD_TOKEN WEBHOOK_HOST WEBHOOK_SECRET; do
    grep -q "^${VAR}=" .env || warn ".env da ${VAR} yo'q — tekshiring!"
done

# 2. assets papkasi
mkdir -p assets
[[ -f assets/logo.png ]] || warn "assets/logo.png yo'q — PDF da logo bo'lmaydi"
ok "assets/ papkasi tayyor"

# 3. Docker tekshiruvi
command -v docker >/dev/null 2>&1 || err "Docker o'rnatilmagan"
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    err "docker compose / docker-compose topilmadi"
fi
ok "Docker: $DC"

# 4. Port tekshiruvi
PORT=$(grep -E '^WEBHOOK_HOST_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo "8082")
PORT=${PORT:-8082}
if ss -tlnp 2>/dev/null | grep -q ":${PORT} " || \
   netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    warn "Port ${PORT} band! .env da WEBHOOK_HOST_PORT=<boshqa_port> qo'ying (masalan 8083)"
fi

# 5. Eski bot konteynerini to'xtatish (agar bor bo'lsa)
if $DC ps -q bot 2>/dev/null | grep -q .; then
    echo "Eski konteyner to'xtatilmoqda..."
    $DC stop bot
fi

# 6. Build va ishga tushirish
echo "Build va ishga tushirish..."
$DC up -d --build

# 7. Natija tekshiruvi
sleep 4
if $DC ps | grep -q "bot.*Up\|bot.*running"; then
    ok "Bot ishlamoqda!"
else
    err "Bot ishga tushmadi. Logni ko'ring: $DC logs bot"
fi

echo ""
echo "=== Foydali buyruqlar ==="
echo "  Loglar:       $DC logs -f bot"
echo "  To'xtatish:   $DC stop bot"
echo "  Qayta start:  $DC restart bot"
echo "  Port:         127.0.0.1:${PORT} → bot:8080"
echo ""
warn "Nginx/Caddy ga location blok qo'shishni unutmang!"
warn "Ko'ring: deploy/nginx-add-to-existing.conf"
