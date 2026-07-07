# Dokploy'da tiklash — to'liq qo'llanma

Bu bot Dokploy'da **Docker Compose** ilova sifatida ishga tushiriladi.
Dokploy'ning o'zida **Traefik** (reverse proxy) bor va 80/443 portlar hamda
SSL (Let's Encrypt) uni tomonidan avtomatik boshqariladi. Shuning uchun eski
`docker-compose.yml` dagi Caddy KERAK EMAS — buning o'rniga
**`docker-compose.dokploy.yml`** ishlatiladi.

---

## Nima menim (kod) tomonimdan tayyor
- ✅ `docker-compose.dokploy.yml` — Caddy'siz, portlarsiz, `dokploy-network` bilan.
- ✅ `OY - Comfort bot/.env.example` — barcha o'zgaruvchilar to'liq.
- ✅ Tayyor `WEBHOOK_SECRET` (pastda).
- ✅ Tiklash skriptlari kodda (`list_attributes.py`, `register_webhooks.py`, ...).

## Nima siz tomondan (faqat siz kira olasiz)
- 🔑 Telegram / MoySklad / DNS akkauntlaringiz.
- 🖱️ Dokploy UI'da tugmalarni bosish (quyida aniq ko'rsatilgan).

---

## 0. Talablar
- Ishlab turgan **Dokploy** server (Traefik bilan) — public IP.
- Domen (masalan `bot.example.com`).

---

## 1. DNS — domenni Dokploy serverga yo'naltiring
Domen registratoringizda **A record** qo'shing:
```
A    bot.example.com   →   <Dokploy server IP>
```
Tekshiring:
```bash
dig +short bot.example.com     # Dokploy IP chiqishi kerak
```

---

## 2. Dokploy'da ilova yarating
1. Dokploy → **Create Project** (yoki mavjudini oching).
2. **Create Service → Compose**.
3. **Provider = GitHub**, repo: `elmun-technologies/uhudtg`, branch: `main`.
   - Agar GitHub ulanmagan bo'lsa: Settings → Git → GitHub'ni ulang,
     yoki "Public repository" bilan URL kiriting.
4. **General → Compose Path**: `./docker-compose.dokploy.yml`  ← MUHIM.

---

## 3. Environment (maxfiy o'zgaruvchilar)
Dokploy → ilova → **Environment** bo'limiga quyidagini joylang
(o'z qiymatlaringiz bilan):

```env
BOT_TOKEN=<@BotFather dan>
MOYSKLAD_TOKEN=<MoySklad → Ключи доступа dan>
MOYSKLAD_TG_ATTR_UUID=
DOMAIN=bot.example.com
WEBHOOK_HOST=https://bot.example.com
WEBHOOK_PATH=/moysklad/webhook
WEBHOOK_SECRET=<pastdagi tayyor qiymatni qo'ying>
DB_PATH=/data/comfort_bot.db
ADMIN_IDS=<Telegram ID ingiz>
COMPANY_PHONE=+998958220000
APP_TIMEZONE=Asia/Tashkent
```

`MOYSKLAD_TG_ATTR_UUID` ni hozircha **bo'sh** qoldiring — 6-qadamda topamiz.

Tokenlar qayerdan:
| Qiymat | Manba |
|---|---|
| `BOT_TOKEN` | @BotFather → botingiz → `/token` |
| `MOYSKLAD_TOKEN` | MoySklad → Настройки → Пользователи → Ключи доступа → yangi kalit |
| `ADMIN_IDS` | @userinfobot dan Telegram ID |
| `WEBHOOK_SECRET` | pastda tayyor berilgan |

---

## 4. Domain (SSL) qo'shing
Dokploy → ilova → **Domains → Add Domain**:
- **Host**: `bot.example.com`
- **Path**: `/`
- **Container Port**: `8080`
- **HTTPS**: ✅ yoqing (Let's Encrypt)
- **Service**: `bot`

Dokploy Traefik label'larini o'zi qo'shadi. Qo'lda hech narsa yozish shart emas.

---

## 5. Deploy
Dokploy → ilova → **Deploy** tugmasini bosing.
Loglarda `Starting bot polling…` chiqishini kuting.
`https://bot.example.com` ochilib, SSL yashil bo'lsa — proxy ishlayapti.

---

## 6. MoySklad "Telegram ID" atribut UUID sini toping
Dokploy → ilova → **Terminal** (yoki server SSH) orqali konteynerda:
```bash
docker compose -f docker-compose.dokploy.yml exec bot python list_attributes.py
```
Chiqqan UUID ni **Environment → `MOYSKLAD_TG_ATTR_UUID`** ga yozing va
qayta **Deploy** qiling.
> ⚠️ Kodda 2 xil UUID bor (account'ga bog'liq) — shuning uchun majburan shu
> skript orqali to'g'risini aniqlang.

---

## 7. Webhook'larni qayta ulang
Eski webhook'lar hali o'lgan serverga ishora qilyapti. Konteynerda:
```bash
docker compose -f docker-compose.dokploy.yml exec bot python cleanup_webhooks.py
docker compose -f docker-compose.dokploy.yml exec bot python register_webhooks.py
```

## 8. Foydalanuvchilarni tiklash (ixtiyoriy)
```bash
docker compose -f docker-compose.dokploy.yml exec bot python restore_users.py
```

---

## 9. Tekshirish
- [ ] Loglar: `Starting bot polling…`
- [ ] `https://bot.example.com` — SSL ishlayapti
- [ ] Botga `/start` → ro'yxatdan o'tadi
- [ ] MoySklad'da test buyurtma → Telegram'ga bildirishnoma keladi

---

## Ma'lumot saqlash (persistence)
- SQLite `bot_data` nomli Docker volume'da (`/data/comfort_bot.db`) —
  redeploy'da **o'chmaydi**.
- ⚠️ Dokploy'ni butunlay o'chirib qayta o'rnatsangiz volume ketishi mumkin —
  `bot_data` uchun **backup** sozlang (Dokploy → Volumes / Backups).
- Baribir asosiy ma'lumot MoySklad'da — `restore_users.py` bilan tiklanadi.

## Logo (ixtiyoriy)
PDF hisobotda logo chiqishi uchun `assets/logo.png` (200×200 PNG) qo'shing.
Bo'lmasa PDF baribir yaratiladi, faqat logosiz.
