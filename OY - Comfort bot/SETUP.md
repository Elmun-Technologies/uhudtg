# Comfort Textile Bot — Setup Guide

## 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

## 2. Настройка .env

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

| Переменная | Где взять |
|---|---|
| `BOT_TOKEN` | @BotFather → /newbot |
| `MOYSKLAD_TOKEN` | МойСклад → Настройки → Пользователи → ваш пользователь → **Ключи доступа** |
| `WEBHOOK_HOST` | Публичный URL вашего сервера (напр. https://yourdomain.com) |
| `WEBHOOK_SECRET` | Любая случайная строка — для защиты вебхука |
| `ADMIN_IDS` | Ваш Telegram ID (узнать: @userinfobot) |

## 3. Логотип

Положите файл логотипа в `assets/logo.png`  
(PNG, рекомендуемый размер ~200×200 px)

## 4. Настройка вебхука в МойСклад

1. МойСклад → **Настройки** → **Вебхуки** → **Создать**
2. Создайте **два** вебхука:

   | Событие | URL |
   |---|---|
   | Заказ покупателя — Создание | `https://yourdomain.com/moysklad/webhook?secret=ВАШ_СЕКРЕТ` |
   | Отгрузка — Создание | `https://yourdomain.com/moysklad/webhook?secret=ВАШ_СЕКРЕТ` |

3. Метод: **POST**, Тип данных: **application/json**

## 5. Привязка клиентов

Клиент в Telegram должен быть зарегистрирован в боте через `/start`.  
Телефон в Telegram **должен совпадать** с телефоном контрагента в МойСклад.

Формат телефона в МойСклад: `998XXXXXXXXX` (без `+`, 12 цифр).

## 6. Запуск

```bash
python bot.py
```

Для продакшна рекомендуется использовать systemd или supervisor:

```ini
# /etc/systemd/system/comfort-bot.service
[Unit]
Description=Comfort Textile Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
EnvironmentFile=/path/to/bot/.env

[Install]
WantedBy=multi-user.target
```

## 7. Структура проекта

```
comfort-bot/
├── bot.py              ← Точка входа
├── config.py           ← Конфигурация из .env
├── database.py         ← SQLite: пользователи, заказы, отгрузки
├── locales.py          ← Тексты на uz/ru
├── keyboards.py        ← Клавиатуры Telegram
├── moysklad_api.py     ← МойСклад API клиент
├── pdf_generator.py    ← Генерация PDF отгрузки
├── webhook_server.py   ← Приём вебхуков от МойСклад
├── handlers/
│   ├── start.py        ← /start, регистрация
│   └── menu.py         ← Баланс, Заказы, Отчёт, Язык
├── assets/
│   └── logo.png        ← Логотип для PDF (добавить вручную)
├── .env                ← Ваши токены (не коммитить!)
└── requirements.txt
```

## 8. Локальная разработка (без публичного URL)

Для тестирования вебхуков локально используйте [ngrok](https://ngrok.com/):

```bash
ngrok http 8080
```

Возьмите HTTPS URL из ngrok и вставьте в `WEBHOOK_HOST` в `.env`.
