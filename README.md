# Telegram Bot — MoySklad integratsiyasi

Mijozlar uchun Telegram bot. MoySklad ERP tizimi bilan to'liq integratsiya qilingan: buyurtmalar, otgruzkalar, to'lovlar haqida real vaqt bildirishnomalari, balans ko'rish, hisobot olish va manzil saqlash.

---

## Imkoniyatlar

| Funksiya | Tavsif |
|---|---|
| 📱 Ro'yxatdan o'tish | Telefon raqami orqali avtomatik MoySklad kontragentga ulanish |
| 📍 Manzil | Yetkazib berish manzilini yuborish — MoySklad kontragentga saqlanadi |
| 💰 Balans | Joriy qoldiq (MoySklad dan jonli) |
| 🛒 Buyurtmalar | So'nggi otgruzkalar ro'yxati |
| 📊 Hisobot | Davr bo'yicha PDF hisobot (kunlik / haftalik / oylik va boshqalar) |
| 🔔 Bildirishnomalar | Buyurtma, otgruzka, qaytarish, to'lov — avtomatik xabar |
| 🌐 Til | O'zbek / Rus tili |

---

## Texnik stek

- **Python** 3.11
- **aiogram** 3.7 — Telegram bot framework
- **aiohttp** 3.9 — webhook server
- **httpx** 0.27 — MoySklad API client (async)
- **aiosqlite** 0.20 — SQLite bazasi
- **reportlab** + **Pillow** — PDF hisobot generatsiya
- **Docker** + **Caddy** — deploy va SSL

---

## Sozlash

### 1. `.env` fayli yaratish

```bash
cp "OY - Comfort bot/.env.example" "OY - Comfort bot/.env"
```

`.env` faylini to'ldiring:

| O'zgaruvchi | Qayerdan olish |
|---|---|
| `BOT_TOKEN` | @BotFather → /newbot |
| `MOYSKLAD_TOKEN` | MoySklad → Sozlamalar → Foydalanuvchilar → Kirish kalitlari |
| `WEBHOOK_HOST` | Server domeningiz (`https://yourdomain.com`) |
| `WEBHOOK_SECRET` | Istalgan tasodifiy satr (webhook himoyasi uchun) |
| `ADMIN_IDS` | Admin Telegram ID-lari, vergul bilan (`123456,789012`) |
| `COMPANY_PHONE` | Kompaniya telefon raqami (botda ko'rsatiladi) |
| `DB_PATH` | Docker uchun: `/data/comfort_bot.db` |

### 2. Logotip

PDF hisobot uchun logotip fayl qo'ying:

```
OY - Comfort bot/assets/logo.png
```

Tavsiya etilgan o'lcham: 200×200 px, PNG format.

### 3. MoySklad webhook-larini ulash

`register_webhooks.py` skriptini bir marta ishga tushiring:

```bash
cd "OY - Comfort bot"
python register_webhooks.py
```

Yoki MoySklad panelidan qo'lda: **Sozlamalar → Webhook-lar → Yaratish**

Ro'yxatga olinishi kerak bo'lgan voqealar:

| Voqea | URL |
|---|---|
| Buyurtma — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |
| Otgruzka — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |
| Savdo qaytarish — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |
| Kirim to'lov — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |
| Chiqim to'lov — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |
| Ta'minot — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |
| Ta'minotchi qaytarish — Yaratish | `https://yourdomain.com/moysklad/webhook?secret=SECRET` |

### 4. Telegram ID maxsus atributi (MoySklad)

Botni webhook bildirishnomalar yuborishi uchun MoySklad kontragentda **Telegram ID** maxsus atributi bo'lishi kerak.

`moysklad_api.py` faylida UUID ni yangilang (tegishli qatorda):

```python
"href": f"{MOYSKLAD_API}/entity/counterparty/metadata/attributes/<UUID>",
```

UUID ni topish uchun:
```bash
python list_attributes.py
```

---

## Docker bilan ishga tushirish (tavsiya etiladi)

### Talablar

- Docker 24+
- Docker Compose v2
- Ochiq portlar: `80`, `443`, `8080`

### Ishga tushirish

```bash
# 1. Repozitoriyni clone qiling
git clone <repo-url>
cd uhudtg

# 2. .env faylini to'ldiring (yuqoridagi bo'limga qarang)

# 3. Domenni Caddyfile ga kiriting
echo 'yourdomain.com {
    reverse_proxy /moysklad/* bot:8080
}' > Caddyfile

# 4. Konteynerlarni ishga tushiring
docker compose up -d --build

# 5. Webhook larni ro'yxatdan o'tkazing
docker compose exec bot python register_webhooks.py
```

### Foydali buyruqlar

```bash
# Loglarni ko'rish
docker compose logs -f bot

# Botni qayta ishga tushirish
docker compose restart bot

# To'xtatish
docker compose down
```

---

## Mahalliy ishga tushirish (test uchun)

```bash
cd "OY - Comfort bot"
pip install -r requirements.txt
python bot.py
```

Webhook larni lokal test qilish uchun [ngrok](https://ngrok.com/) dan foydalaning:

```bash
ngrok http 8080
# Olingan HTTPS URL ni WEBHOOK_HOST ga kiriting
```

---

## Loyiha tuzilmasi

```
uhudtg/
├── OY - Comfort bot/
│   ├── bot.py                  ← Asosiy kirish nuqtasi
│   ├── config.py               ← .env dan konfiguratsiya
│   ├── database.py             ← SQLite: foydalanuvchilar, buyurtmalar
│   ├── moysklad_api.py         ← MoySklad API client
│   ├── webhook_server.py       ← MoySklad webhook qabul qiluvchi
│   ├── scheduler.py            ← Kunlik hisobot rejalashtiruvchi
│   ├── daily_report.py         ← Admin hisobot generatori
│   ├── pdf_generator.py        ← PDF hisobot generatori
│   ├── locales.py              ← Matnlar (uz / ru)
│   ├── keyboards.py            ← Telegram tugmalar
│   ├── formatting.py           ← Raqam va sana formatlash
│   ├── time_utils.py           ← Vaqt zonasi yordamchisi
│   ├── handlers/
│   │   ├── start.py            ← /start, ro'yxatdan o'tish, manzil
│   │   └── menu.py             ← Balans, Buyurtmalar, Hisobot, Til, Manzil
│   ├── register_webhooks.py    ← Webhook larni bir marta ro'yxatdan o'tkazish
│   ├── list_webhooks.py        ← Ro'yxatdagi webhook larni ko'rish
│   ├── cleanup_webhooks.py     ← Barcha webhook larni o'chirish
│   ├── list_attributes.py      ← Kontragent maxsus atributlari va UUID lari
│   ├── restore_users.py        ← MoySklad dan foydalanuvchilarni tiklash
│   ├── sync_users.py           ← Foydalanuvchilarni sinxronlash
│   ├── sync_balances.py        ← Barcha foydalanuvchilar balansini yangilash
│   ├── assets/
│   │   └── logo.png            ← PDF uchun logotip (qo'lda qo'shiladi)
│   ├── .env                    ← Tokenlar (git ga commit qilinmaydi!)
│   ├── .env.example            ← Shablon
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
├── Caddyfile
└── deploy/                     ← Server sozlash skriptlari
```

---

## Mijoz ro'yxatdan o'tish jarayoni

```
/start
  └─► Telefon raqam so'raladi
        └─► MoySklad da qidiriladi
              ├─► Topildi (mavjud kontragent)
              │     └─► Asosiy menyu
              └─► Topilmadi (yangi mijoz)
                    └─► Manzil so'raladi (o'tkazish mumkin)
                          └─► Asosiy menyu
```

Mavjud mijozlar `📍 Manzilim` tugmasi orqali manzilni istalgan vaqt yangilay oladi.

---

## MoySklad ↔ Telegram ma'lumot oqimi

```
Telegram → MoySklad
  Telefon  → phone
  Ism      → name
  TG ID    → maxsus atribut
  Manzil   → actualAddress

MoySklad → Telegram (webhook orqali)
  Buyurtma yaratildi    → Bildirishnoma
  Otgruzka yaratildi    → Bildirishnoma + PDF
  To'lov qabul qilindi  → Bildirishnoma
  Qaytarish             → Bildirishnoma
```

---

## Foydali skriptlar

| Skript | Vazifasi |
|---|---|
| `register_webhooks.py` | MoySklad webhook larini bir marta ro'yxatdan o'tkazish |
| `list_webhooks.py` | Ro'yxatdagi webhook larni ko'rish |
| `cleanup_webhooks.py` | Barcha webhook larni o'chirish |
| `list_attributes.py` | Kontragent maxsus atributlarini va UUID larini ko'rish |
| `restore_users.py` | MoySklad dan foydalanuvchilar jadvalini tiklash |
| `sync_balances.py` | Barcha foydalanuvchilar balansini yangilash |
| `healthcheck.py` | Bot holat tekshiruvi |
