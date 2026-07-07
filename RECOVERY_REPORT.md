# Production Recovery Report — OY Comfort Bot (uhudtg)

**Situation:** the DigitalOcean Droplet running production was permanently
destroyed after account suspension (overdue payment). Only the GitHub
repository (`elmun-technologies/uhudtg`) and the external SaaS accounts
(Telegram, MoySklad, DNS registrar) survive. This document lets an engineer
with **no prior knowledge** rebuild the system from scratch.

---

## 0. What this system is

A customer-facing **Telegram bot** for **Uhud Auto**, tightly integrated with
the **MoySklad** ERP. Customers register by phone; the bot links them to their
MoySklad counterparty and pushes real-time notifications (orders, shipments,
returns, payments, supplies) plus PDF reports, and shows their live balance.

| Layer | Tech |
|---|---|
| Bot framework | Python 3.11, aiogram 3.7 (long polling) |
| Webhook receiver | aiohttp 3.9 server on port 8080 |
| ERP client | httpx 0.27 → MoySklad JSON API 1.2 |
| Local store | SQLite via aiosqlite 0.20 |
| PDF | reportlab + Pillow |
| Runtime | Docker Compose (2 services: `bot`, `caddy`) |
| TLS / reverse proxy | Caddy 2 (automatic Let's Encrypt) |

**Data flow:** Telegram `/start` → phone match in MoySklad → notifications flow
back from MoySklad → the bot via a single webhook endpoint
`POST /moysklad/webhook?secret=...`.

---

## 1. Codebase analysis (complete)

Application code lives in `OY - Comfort bot/`. Everything is committed to git
**except** secrets, the database, and the logo (see §10).

| File | Role |
|---|---|
| `bot.py` | Entry point. Boots DB, starts polling + aiohttp webhook server + daily-report scheduler. |
| `config.py` | Loads all config from `.env`. **Single source of truth for env vars.** |
| `database.py` | SQLite schema + all queries. Tables: `users`, `orders`, `order_items`, `shipments`, `shipment_items`, `returns`, `return_items`. |
| `webhook_server.py` | Receives MoySklad webhooks, validates `secret`, dispatches Telegram messages/PDFs. |
| `moysklad_api.py` | Async MoySklad client: fetch entities, balances, create/sync counterparty (writes the "Telegram ID" custom attribute), global rate-limiting + retry. |
| `handlers/start.py` | `/start`, phone registration, address capture. |
| `handlers/menu.py` | Balance, Orders, Report, Language, Address buttons. |
| `scheduler.py` / `daily_report.py` | Daily admin report at 20:00 Asia/Tashkent. |
| `pdf_generator.py` | Shipment/period PDFs. Logo optional (renders blank cell if absent). |
| `locales.py`, `keyboards.py`, `formatting.py`, `time_utils.py` | i18n (uz/ru), keyboards, number/date formatting, TZ helpers. |
| `register_webhooks.py` | **One-shot:** registers all 9 webhooks in MoySklad → your webhook URL. |
| `list_webhooks.py` / `cleanup_webhooks.py` | Inspect / delete all registered webhooks. |
| `list_attributes.py` | Prints counterparty custom attributes + their UUIDs (needed for `MOYSKLAD_TG_ATTR_UUID`). |
| `restore_users.py` | **Recovery tool:** rebuilds the `users` table from MoySklad by reading each counterparty's "Telegram ID" attribute. |
| `sync_users.py`, `sync_balances.py` | Sync users / refresh balances from MoySklad. |
| `healthcheck.py`, `check_*.py`, `audit_phones.py` | Diagnostics. |
| `Dockerfile` | python:3.11-slim, installs deps, `mkdir /data /app/assets`, runs `bot.py`. |

Root: `docker-compose.yml`, `Caddyfile`, `deploy/` (legacy VPS scripts),
`README.md`, `deploy_fix.sh`.

---

## 2 & 3. Required environment variables

A **complete** `.env.example` is committed at `OY - Comfort bot/.env.example`.
Full list (defaults from `config.py` shown where they exist):

| Variable | Required? | Default | Purpose |
|---|---|---|---|
| `BOT_TOKEN` | **Yes** | — | Telegram bot auth |
| `MOYSKLAD_TOKEN` | **Yes** | — | MoySklad API Bearer token |
| `MOYSKLAD_TG_ATTR_UUID` | Recommended | `0db9b9e1-…4ee9` | UUID of "Telegram ID" counterparty attribute (account-specific) |
| `DOMAIN` | **Yes (for HTTPS)** | — | Domain for Caddy/Let's Encrypt (`Caddyfile` uses `{$DOMAIN}`) |
| `WEBHOOK_HOST` | **Yes** | — | Public HTTPS base URL (`https://<DOMAIN>`) |
| `WEBHOOK_PATH` | No | `/moysklad/webhook` | Webhook route |
| `WEBHOOK_PORT` | No | `8080` | Internal listen port |
| `WEBHOOK_SECRET` | **Yes** | `secret` | Validates incoming webhooks (**not recoverable — set new**) |
| `WEBHOOK_HOST_PORT` | No | (unset) | Expose 8080 on host directly (skip if using Caddy) |
| `DB_PATH` | **Yes** | `comfort_bot.db` | **Must be `/data/comfort_bot.db` in Docker** |
| `ADMIN_IDS` | **Yes** | `[]` | Admin Telegram IDs (comma-separated) |
| `COMPANY_PHONE` | No | `+998958220000` | Shown in bot |
| `APP_TIMEZONE` | No | `Asia/Tashkent` | Bot timezone |
| `DAILY_REPORT_HOUR` / `_MINUTE` | No | `20` / `0` | Daily report time |
| `MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ` | No | `Europe/Moscow` | MS timestamp source TZ |
| `MOYSKLAD_ENRICH_CONCURRENCY` | No | `6` | Parallel enrich requests |
| `WEBHOOK_WORKERS` | No | `3` | Webhook worker count |
| `MS_MOMENT_LOG` | No | off | Debug logging |

---

## 4. Where each value comes from

| Value | Source | Recoverable? |
|---|---|---|
| **Telegram Bot Token** | @BotFather → your bot → `/token` (reissue) or `/newbot` | ✅ Yes — log into the Telegram account that owns the bot. Reissuing invalidates the old token. |
| **MoySklad Token** | МойСклад → Настройки → Пользователи → user → **Ключи доступа** → generate | ✅ Yes — log into MoySklad and mint a new access key. |
| **Webhook Host / DOMAIN** | Your DNS registrar / domain you own (`https://<domain>`) | ✅ Yes — you own the domain; just re-point the A record to the new server IP. |
| **Webhook Secret** | Arbitrary random string you chose; lived **only** in the server `.env` | ❌ **No** — old value is gone with the server. Generate a new one (`openssl rand -hex 24`) and re-register webhooks. |
| **Admin IDs** | Each admin's Telegram numeric ID (@userinfobot) | ✅ Yes — known to the operators. |
| **Company Phone** | Business phone; default `+998958220000` | ✅ Yes — known. |
| **Database Path** | Config value; `/data/comfort_bot.db` (Docker volume) | ✅ Path yes; the **data** inside is lost (see §5–6). |
| **MOYSKLAD_TG_ATTR_UUID** | `python list_attributes.py` against your MoySklad account | ✅ Yes — regenerate after MoySklad token is set. ⚠️ Two different UUIDs appear in the repo (see §11). |
| **Other secrets** | None. No payment keys, no third-party APIs beyond Telegram + MoySklad. | — |

---

## 5. Does the bot store critical data locally?

**Minimally.** The only actively-written table is **`users`**, holding:

- `telegram_id` ↔ `phone` (the account link),
- `moysklad_counterparty_id` (cached),
- `balance_usd` + `balance_updated_at` (a cache; always re-fetched live),
- `language` (uz/ru), `name`, `registered_at`.

Everything customers *see* (orders, shipments, returns, balance, reports) is
read **live from MoySklad**, not from SQLite. The `webhook_server.py` docstring
states this explicitly: *"История отгрузок/заказов/возвратов в SQLite не
хранится … В users сохраняются только привязка к контрагенту и баланс."*

## 6. Does SQLite hold important business data or only temporary data?

**Business-critical data: essentially none of it is irreplaceable.**

- `orders`/`shipments`/`returns` + their `_items` tables exist in the schema
  but are **not populated in normal operation** — they are legacy/unused; the
  authoritative record is MoySklad.
- `users` is the one table with real value, **but it is reconstructable** from
  MoySklad via `restore_users.py`, *provided* counterparties carry the
  "Telegram ID" custom attribute (the bot writes it when it creates/syncs a
  counterparty).

**What is genuinely lost and NOT recoverable from MoySklad:**
- `language` preference per user (defaults back to `uz`; users can re-pick).
- Users whose counterparty never got the Telegram-ID attribute written
  (e.g. matched purely by phone and never triggered a sync) — they must run
  `/start` again to re-link.

**Bottom line:** the SQLite DB is a **cache/link table**, not the system of
record. Losing it costs re-linking convenience, not business data.

---

## 7. Fresh Ubuntu deployment guide (recommended: Docker)

Target: clean Ubuntu 22.04+ with a public IP and ports 80/443 open.

```bash
# 1. Install Docker + Compose plugin
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 2. Clone the repo (NOTE: correct repo is uhudtg, not comfort-txt)
git clone https://github.com/elmun-technologies/uhudtg.git /opt/comfort-bot
cd /opt/comfort-bot

# 3. Create the real .env from the template
cp "OY - Comfort bot/.env.example" .env
#   docker-compose.yml reads ./.env at the repo ROOT — keep it here.
nano .env
#   Fill: BOT_TOKEN, MOYSKLAD_TOKEN, DOMAIN, WEBHOOK_HOST=https://<DOMAIN>,
#         WEBHOOK_SECRET (new random), ADMIN_IDS, DB_PATH=/data/comfort_bot.db
#   MOYSKLAD_TG_ATTR_UUID left blank for now (filled in step 6).

# 4. Point DNS: A record  <DOMAIN> -> this server's public IP (see §14).
#    Wait until `dig +short <DOMAIN>` returns the new IP before step 5,
#    or Caddy's Let's Encrypt challenge will fail.

# 5. Provide the PDF logo (optional but recommended for branding)
mkdir -p assets
#   copy your logo to ./assets/logo.png (PNG ~200x200). PDFs work without it.

# 6. Build & start
docker compose up -d --build

# 7. Find the correct Telegram-ID attribute UUID for THIS MoySklad account
docker compose exec bot python list_attributes.py
#   Put the UUID into .env as MOYSKLAD_TG_ATTR_UUID, then:
docker compose restart bot

# 8. Clean up stale webhooks (they still point at the dead server) and register
docker compose exec bot python cleanup_webhooks.py
docker compose exec bot python register_webhooks.py

# 9. (Optional) rebuild the users table from MoySklad
docker compose exec bot python restore_users.py

# 10. Verify
docker compose logs -f bot           # expect "Starting bot polling…"
curl -I https://<DOMAIN>/moysklad/webhook   # Caddy terminates TLS -> bot
```

**Alternative (bare-metal systemd):** `deploy/setup.sh` / `deploy/deploy.sh`
exist but reference the **wrong repo URL** (`comfort-txt`) and need editing
first (see §11). Docker is the supported path.

---

## 8. docker-compose.yml review

```yaml
services:
  bot:   build ./OY - Comfort bot ; env_file .env ; restart unless-stopped
         dns 8.8.8.8/1.1.1.1  (works around container DNS failures)
         ports: 8080 published only if ${WEBHOOK_HOST_PORT} set
         volumes: bot_data:/data  +  ./assets:/app/assets
  caddy: caddy:2-alpine ; ports 80/443 (+443/udp)
         volumes: ./Caddyfile:ro , caddy_data , caddy_config
volumes: bot_data, caddy_data, caddy_config
```

Findings:
- ✅ Correct: DB on named volume `bot_data:/data`, matching `DB_PATH=/data/...`.
- ✅ Correct: Caddy handles TLS; bot port stays internal by default.
- ⚠️ **`./assets:/app/assets` bind mount** — the `assets/` dir is **not in the
  repo**. If absent, Docker auto-creates an empty dir (harmless; logo just
  won't render). Create it and drop `logo.png` in for branding.
- ⚠️ `caddy` uses `env_file: .env` only to read `{$DOMAIN}` in the Caddyfile —
  so **`DOMAIN` must be present in `.env`** or TLS won't provision.
- ⚠️ `.env` must live at the **repo root** (not inside `OY - Comfort bot/`) —
  compose resolves `env_file: .env` relative to the compose file.

## 9. Docker volumes

| Volume | Contents | Status after loss | Recovery |
|---|---|---|---|
| `bot_data` | `/data/comfort_bot.db` (SQLite) | **Gone** with the droplet | Recreated empty on boot; repopulate `users` via `restore_users.py` |
| `caddy_data` | Let's Encrypt certs/keys, ACME state | **Gone** | Auto-reissued by Caddy on first HTTPS request (needs DNS + port 80/443) |
| `caddy_config` | Caddy autosave config | **Gone** | Auto-regenerated |

**None of the volumes were backed up off-server**, so all volume data is lost.
All three regenerate automatically; only `bot_data`'s `users` table needs the
manual `restore_users.py` step.

---

## 10. Files that existed ONLY on the destroyed server

These are **gitignored or never committed** — they do not exist in GitHub and
are therefore lost:

| File | Why it's gone | Impact | Fix |
|---|---|---|---|
| `.env` (root + `OY - Comfort bot/.env`) | gitignored (`*.env`) | **All secrets lost** | Recreate from `.env.example`; re-obtain tokens (§4) |
| `comfort_bot.db` | gitignored (`*.db`); lived in `bot_data` volume | `users` link table lost | `restore_users.py` |
| `assets/logo.png` | never committed | PDFs lose branding (still generate) | Re-add the PNG |
| Caddy TLS certs | in `caddy_data` volume | none (auto-reissued) | Automatic |
| Any manual server tweaks (cron, firewall, extra `.env` keys) | server-only | unknown | Re-apply per this guide |

---

## 11. Every possible recovery issue

1. **`.env` is gone** → every secret must be re-created/re-obtained (§4). This
   is the single biggest blocker.
2. **`WEBHOOK_SECRET` is unrecoverable** → you must choose a new one. Old
   webhooks in MoySklad still carry the old secret **and** point at the dead
   server's URL — they will silently fail. Run `cleanup_webhooks.py` then
   `register_webhooks.py` with the new secret/host.
3. **Stale webhooks in MoySklad** pointing to the destroyed IP/domain →
   duplicate or dead deliveries until cleaned up.
4. **⚠️ Conflicting Telegram-ID attribute UUIDs in the code:**
   - `config.py` default → `0db9b9e1-bd23-11ef-0a80-045400574ee9`
   - `restore_users.py` `TG_ATTR_ID` → `8666aeb7-192b-11f1-0a80-00f20005e1af`

   These differ. The attribute UUID is **account-specific**. Before trusting
   new-counterparty creation *or* `restore_users.py`, run `list_attributes.py`
   and set the real UUID (in `.env` for the bot; and reconcile
   `restore_users.py` if you use it). A wrong UUID means new counterparties
   are created without the Telegram link and/or restore finds nobody.
5. **Deploy scripts reference the wrong repo.** `deploy/setup.sh` and
   `deploy/deploy.sh` clone `Elmun-Technologies/comfort-txt` — the real repo is
   `elmun-technologies/uhudtg`. Edit `REPO`/`REPO_URL` before using them, or use
   the Docker guide in §7.
6. **DNS still points at the destroyed droplet's IP** → must update the A
   record to the new server (§14). Caddy cannot get a cert until DNS resolves
   to the new IP and ports 80/443 are reachable.
7. **`DB_PATH` default is ephemeral.** `config.py` defaults to a relative
   `comfort_bot.db`; if `.env` doesn't set `/data/...`, the DB lands in the
   container layer and is wiped on every rebuild. `.env` must set
   `DB_PATH=/data/comfort_bot.db`.
8. **`.env` location.** Compose expects `.env` at repo root; putting it only in
   `OY - Comfort bot/` will leave the container with empty config.
9. **`DOMAIN` missing from the old `.env.example`** (now fixed here) → Caddy
   would fail TLS. Ensure it's set.
10. **Language preferences and phone-only users** are not restorable from
    MoySklad (§6) — expect some users to re-`/start`.
11. **Account suspension root cause.** The provider suspended for non-payment —
    ensure billing is resolved (or use a different provider) before redeploying,
    or the same thing recurs. Set up billing alerts.
12. **No off-site backups existed.** Add a backup for `bot_data` going forward
    (§15).

---

## 12. Complete recovery checklist

```
ACCOUNTS
[ ] Regain access to Telegram account that owns the bot
[ ] Regain access to MoySklad account
[ ] Regain access to DNS registrar / domain
[ ] Resolve DigitalOcean billing OR choose a new provider

INFRASTRUCTURE
[ ] Provision fresh Ubuntu 22.04+ server, public IP, ports 80/443 open
[ ] Install Docker + Compose plugin
[ ] Point DNS A record  <DOMAIN> -> new server IP ; confirm with dig

SECRETS (.env at repo root)
[ ] BOT_TOKEN            (BotFather; reissue if needed)
[ ] MOYSKLAD_TOKEN       (MoySklad access key — new)
[ ] WEBHOOK_SECRET       (new random: openssl rand -hex 24)
[ ] DOMAIN + WEBHOOK_HOST=https://<DOMAIN>
[ ] ADMIN_IDS
[ ] DB_PATH=/data/comfort_bot.db
[ ] COMPANY_PHONE (default ok)
[ ] MOYSKLAD_TG_ATTR_UUID  (from list_attributes.py — after first boot)

CODE / ASSETS
[ ] git clone elmun-technologies/uhudtg
[ ] Create ./assets/logo.png (optional)

BRING-UP
[ ] docker compose up -d --build
[ ] docker compose exec bot python list_attributes.py  -> set UUID -> restart
[ ] docker compose exec bot python cleanup_webhooks.py
[ ] docker compose exec bot python register_webhooks.py
[ ] docker compose exec bot python restore_users.py    (optional)

VERIFY
[ ] docker compose logs -f bot  shows "Starting bot polling…"
[ ] Caddy issued TLS cert (https://<DOMAIN> responds)
[ ] Send /start to the bot from a test account -> registers
[ ] Create a test order in MoySklad -> notification arrives in Telegram
[ ] Daily report fires / manual admin check

HARDENING (post-recovery)
[ ] Enable billing alerts on the provider
[ ] Schedule off-site backup of the bot_data volume (§15)
[ ] Reconcile the two Telegram-ID UUIDs in code (§11.4)
[ ] Fix repo URL in deploy/*.sh (§11.5)
```

---

# RECOVERY REPORT — summary matrix

### Critical files
| File | In git? | Action |
|---|---|---|
| `.env` (root) | No (gitignored) | Recreate from `.env.example` |
| `assets/logo.png` | No | Re-add (optional) |
| `comfort_bot.db` | No (in volume) | Regenerated; `restore_users.py` |
| All application code | ✅ Yes | `git clone` |

### Critical secrets
`BOT_TOKEN`, `MOYSKLAD_TOKEN`, `WEBHOOK_SECRET` (new), `ADMIN_IDS`,
`MOYSKLAD_TG_ATTR_UUID`. All live only in `.env` → re-create.

### Required API keys
- Telegram Bot token (BotFather)
- MoySklad API Bearer token (MoySklad access keys)
- *(No other third-party keys.)*

### Required databases
- SQLite `comfort_bot.db` (`users` link table). Auto-created empty;
  repopulate with `restore_users.py`. Not the system of record — MoySklad is.

### Required Docker volumes
- `bot_data` (SQLite) · `caddy_data` (TLS certs) · `caddy_config`.
  All recreated on boot; only `bot_data` needs the restore step.

### Required DNS records
- **A record:** `<DOMAIN>` → new server public IP. (AAAA if using IPv6.)
  Must resolve before Caddy can issue the certificate.

### SSL requirements
- Handled automatically by **Caddy** (Let's Encrypt). Prerequisites: DNS
  resolves to this server, ports **80 and 443** open inbound, `DOMAIN` set in
  `.env`. No manual cert handling.

### Recovery priority
1. **P0 — Accounts & billing:** Telegram, MoySklad, DNS, provider.
2. **P0 — Server + DNS:** provision, open 80/443, point A record.
3. **P0 — Secrets:** rebuild `.env`.
4. **P1 — Bring-up:** `docker compose up`, TLS issues, webhooks registered.
5. **P2 — Data:** `restore_users.py`, verify notifications.
6. **P3 — Hardening:** backups, billing alerts, code fixes (§11.4/11.5).

### Estimated recovery time
| Phase | Time |
|---|---|
| Regain accounts + resolve billing | 15–60 min (depends on provider) |
| Provision server + DNS propagation | 15–45 min |
| `.env` + secrets + tokens | 15–20 min |
| `docker compose up` + Caddy TLS | 5–10 min |
| Webhooks + `restore_users` + verify | 15–20 min |
| **Total (happy path)** | **~1.5–3 hours** |

### Step-by-step deployment order
1. Regain Telegram / MoySklad / DNS access; resolve provider billing.
2. Provision Ubuntu server; install Docker; open ports 80/443.
3. Point DNS A record to the new IP; confirm `dig`.
4. `git clone elmun-technologies/uhudtg /opt/comfort-bot`.
5. `cp "OY - Comfort bot/.env.example" .env`; fill secrets (new
   `WEBHOOK_SECRET`, reissued tokens, `DOMAIN`, `DB_PATH=/data/...`).
6. Add `./assets/logo.png` (optional).
7. `docker compose up -d --build`.
8. `list_attributes.py` → set `MOYSKLAD_TG_ATTR_UUID` → `restart bot`.
9. `cleanup_webhooks.py` → `register_webhooks.py`.
10. `restore_users.py` (optional link recovery).
11. Verify: logs, HTTPS, `/start`, a live MoySklad event → Telegram.
12. Harden: backups, billing alerts, fix the two code discrepancies.
