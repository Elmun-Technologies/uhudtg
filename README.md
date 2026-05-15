# Comfort Textile — Telegram Bot

Mijozlar uchun Telegram bot. MoySklad ERP tizimi bilan to'liq integratsiya qilingan: buyurtmalar, otgruzkalar, to'lovlar haqida real vaqt bildirishnomalari, balans ko'rish, hisobot olish va manzil saqlash.

---

## Imkoniyatlar

| Funksiya | Tavsif |
|---|---|
| 📱 Ro'yxatdan o'tish | Telefon raqami orqali avtomatik MoySklad kontragentga ulanish (yoki yangisini yaratish) |
| 📍 Manzil | Yetkazib berish manzilini yuborish — MoySklad kontragentga saqlanadi |
| 💰 Balans | Joriy qoldiq (MoySklad dan jonli) |
| 🛒 Buyurtmalar | So'nggi otgruzkalar ro'yxati |
| 📊 Hisobot | Davr bo'yicha PDF hisobot |
| 🔔 Bildirishnomalar | Buyurtma, otgruzka, qaytarish, to'lov — avtomatik xabar |
| 📈 Kunlik hisobot | 20:00 da admin va otgruzkasi bo'lgan har bir mijozga avtomatik |
| 🌐 Til | O'zbek / Rus tili |

---

## Texnik stek

- **Python** 3.11
- **aiogram** 3.7 — Telegram bot framework
- **aiohttp** 3.9 — webhook server
- **httpx** 0.27 — MoySklad API client
- **aiosqlite** 0.20 — SQLite
- **reportlab** + **Pillow** — PDF hisobot
- **Docker Compose** — deploy

HTTPS va routing — Traefik (yoki har qanday tashqi reverse proxy) qiladi. Bot o'zi SSL boshqarmaydi.

---

## Sozlash

### 1. `.env` faylini to'ldiring

```bash
cp "OY - Comfort bot/.env.example" .env
```

| O'zgaruvchi | Qayerdan olish |
|---|---|
| `BOT_TOKEN` | @BotFather → `/newbot` |
| `MOYSKLAD_TOKEN` | MoySklad → Sozlamalar → Foydalanuvchilar → Kirish kalitlari |
| `WEBHOOK_HOST` | Tashqi HTTPS URL (`https://your.domain` yoki `https://1-2-3-4.sslip.io`) |
| `WEBHOOK_SECRET` | Tasodifiy satr — `openssl rand -hex 24` |
| `ADMIN_IDS` | Admin Telegram ID-lar, vergul bilan |
| `COMPANY_PHONE` | Botda ko'rsatiladigan kompaniya telefoni |
| `DB_PATH` | Docker uchun majburiy: `/data/comfort_bot.db` |

> ⚠️ `.env` faylini hech qachon git ga commit qilmang.

### 2. Logotip

PDF hisobot uchun:
```
assets/logo.png
```
Tavsiya: 200×200 px PNG.

---

## Docker bilan ishga tushirish (tavsiya etiladi)

### Talablar
- Docker 24+ va Docker Compose v2
- Tashqi reverse proxy (Traefik / nginx / Caddy) — HTTPS uchun
- Tashqaridan kirish mumkin bo'lgan domen yoki IP

### Oddiy holat (mustaqil server)

```bash
git clone <repo-url>
cd uhudtg
cp "OY - Comfort bot/.env.example" .env
# .env faylini to'ldiring
docker compose up -d --build
docker compose logs -f bot
```

### Traefik (Dokploy/Coolify) bilan

`docker-compose.yml` da Traefik labellar va `dokploy-network` allaqachon sozlangan. Faqat `Host()` qiymatini o'zingizning domeningizga moslab qo'ying:

```yaml
- "traefik.http.routers.comfort-bot.rule=Host(`your.domain`) && PathPrefix(`/moysklad`)"
```

Traefik `letsencrypt` resolver bilan SSL avtomatik oladi.

### MoySklad webhook larini ulash

MoySklad → Sozlamalar → Webhook lar → Yaratish:

| Maydon | Qiymat |
|---|---|
| URL | `https://your.domain/moysklad/webhook?secret=YOUR_SECRET` |
| Hodisalar | `customerorder`, `demand`, `paymentin`, `cashin`, `salesreturn`, `supply`, `purchasereturn` (CREATE) |

Yoki avtomatik:
```bash
docker compose exec bot python register_webhooks.py
```

---

## Foydali buyruqlar

```bash
docker compose logs -f bot              # loglar
docker compose restart bot              # qayta start
docker compose down && docker compose up -d --build   # to'liq qayta build

# DB ga kirish (foydalanuvchilar ro'yxati)
docker exec comfort-bot-bot-1 python -c "
import sqlite3
c = sqlite3.connect('/data/comfort_bot.db')
for r in c.execute('SELECT telegram_id, phone, moysklad_counterparty_id FROM users'): print(r)
"
```

---

## Mahalliy ishga tushirish (test uchun)

```bash
cd "OY - Comfort bot"
pip install -r requirements.txt
DB_PATH=./comfort_bot.db python bot.py
```

Webhook larni lokal test qilish uchun [ngrok](https://ngrok.com/):
```bash
ngrok http 8080
# olingan HTTPS URL ni .env dagi WEBHOOK_HOST ga yozing
```

---

## Loyiha tuzilmasi

```
uhudtg/
├── OY - Comfort bot/
│   ├── bot.py                  ← Asosiy kirish nuqtasi
│   ├── config.py               ← .env dan konfiguratsiya
│   ├── database.py             ← SQLite (foydalanuvchilar)
│   ├── moysklad_api.py         ← MoySklad API client
│   ├── webhook_server.py       ← MoySklad webhook qabul qiluvchi
│   ├── scheduler.py            ← Kunlik hisobot rejalashtiruvchi
│   ├── daily_report.py         ← Admin + mijoz kunlik hisoboti
│   ├── pdf_generator.py        ← PDF hisobot
│   ├── locales.py              ← Matnlar (uz / ru)
│   ├── keyboards.py            ← Telegram tugmalar
│   ├── handlers/
│   │   ├── start.py            ← /start, ro'yxatdan o'tish, manzil
│   │   └── menu.py             ← Balans, Buyurtmalar, Hisobot, Til, Manzil
│   ├── register_webhooks.py    ← MoySklad webhook larini ulash
│   ├── list_webhooks.py
│   ├── cleanup_webhooks.py
│   ├── sync_balances.py        ← Barcha balanslarni yangilash
│   ├── healthcheck.py
│   ├── Dockerfile
│   ├── .env.example
│   └── requirements.txt
├── assets/
│   └── logo.png                ← PDF uchun (qo'lda qo'shiladi)
├── docker-compose.yml
└── deploy/                     ← Server yordamchi skriptlar
```

---

## Mijoz ro'yxatdan o'tish jarayoni

```
/start
  └─► Telefon so'raladi
        └─► MoySklad da telefon bo'yicha qidiriladi
              ├─► Topildi → Mavjud kontragentga bog'lanadi
              └─► Topilmadi → Yangi kontragent yaratiladi
                    └─► Manzil so'raladi (o'tkazsa ham bo'ladi)
                          └─► Asosiy menyu
```

Mavjud mijozlar `📍 Manzilim` orqali manzilni istalgan vaqt yangilay oladi.

---

## Bildirishnomalar oqimi

```
MoySklad → bot (webhook orqali)
  Buyurtma yaratildi    → Mijozga matnli xabar
  Otgruzka yaratildi    → Mijozga PDF + xabar
  To'lov qabul qilindi  → Mijozga xabar
  Qaytarish             → Mijozga xabar

Bot (har kuni 20:00 Asia/Tashkent)
  Admin lar             → To'liq aggregatsiya hisoboti
  Bugun otgruzkasi bor mijozlar → Shaxsiy qisqa hisobot
```

---

## Maslahatlar

- `WEBHOOK_SECRET` ni hech qachon predictable qilmang — `openssl rand -hex 24`
- `MOYSKLAD_TOKEN` muddati o'tsa, bot `401` xato beradi va loglarda aniq yozadi
- Bot trafikni ko'p iste'mol qilsa, `WEBHOOK_WORKERS` ni `5–8` ga oshiring
- `bot_data` Docker volume ni o'chirmang — foydalanuvchilar ro'yxati shu yerda
