"""Simple production healthcheck with Telegram alerts."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from time_utils import local_now as _local_now
except Exception:
    _local_now = None

SERVICE_NAME = "comfort-bot"
STATE_FILE = Path("/tmp/comfort_bot_health_state.json")
LOOKBACK_MINUTES = 10
RESEND_INTERVAL_MINUTES = 30
ERROR_PATTERNS = (
    "ERROR",
    "Traceback",
    "TelegramUnauthorizedError",
    "TelegramConflictError",
)


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _run(command: list[str]) -> str:
    proc = subprocess.run(command, capture_output=True, text=True)
    return (proc.stdout or "") + (proc.stderr or "")


def _service_active() -> bool:
    out = _run(["systemctl", "is-active", SERVICE_NAME]).strip()
    return out == "active"


def _recent_logs() -> str:
    since = (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    return _run(["journalctl", "-u", SERVICE_NAME, "--since", since, "--no-pager"])


def _extract_errors(logs: str) -> list[str]:
    lines: list[str] = []
    for line in logs.splitlines():
        if any(p in line for p in ERROR_PATTERNS):
            lines.append(line.strip())
    return lines[-20:]


def _send_telegram(text: str) -> None:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_ids = [x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    if not bot_token or not admin_ids:
        return

    base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for admin_id in admin_ids:
        payload = urllib.parse.urlencode(
            {
                "chat_id": admin_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        req = urllib.request.Request(base_url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass


def _hash_payload(is_active: bool, errors: list[str]) -> str:
    return json.dumps({"active": is_active, "errors": errors}, ensure_ascii=False)


def _alert_time_str() -> str:
    if _local_now is not None:
        return _local_now().strftime("%Y-%m-%d %H:%M:%S %z")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    state = _read_state()

    active = _service_active()
    logs = _recent_logs()
    errors = _extract_errors(logs)
    has_issue = (not active) or bool(errors)

    now_ts = int(datetime.now(timezone.utc).timestamp())
    issue_hash = _hash_payload(active, errors)
    last_hash = state.get("last_issue_hash")
    last_sent_ts = int(state.get("last_sent_ts", 0))
    cooldown = RESEND_INTERVAL_MINUTES * 60

    if has_issue:
        should_send = (
            issue_hash != last_hash
            or (now_ts - last_sent_ts) >= cooldown
        )
        if should_send:
            message_lines = [
                "<b>Comfort Bot Health Alert</b>",
                f"Service active: <code>{active}</code>",
                f"Time (GMT+5): <code>{_alert_time_str()}</code>",
                "",
            ]
            if errors:
                message_lines.append("<b>Recent errors:</b>")
                message_lines.extend(f"• <code>{e[:300]}</code>" for e in errors[:10])
            else:
                message_lines.append("• No recent error lines, but service is not active.")
            _send_telegram("\n".join(message_lines))

            state["last_issue_hash"] = issue_hash
            state["last_sent_ts"] = now_ts
            state["had_issue"] = True
            _write_state(state)
    else:
        if state.get("had_issue"):
            _send_telegram(
                "<b>Comfort Bot Recovery</b>\n"
                "Service is healthy again.\n"
                f"Time (GMT+5): <code>{_alert_time_str()}</code>"
            )
        state["had_issue"] = False
        state["last_issue_hash"] = ""
        _write_state(state)


if __name__ == "__main__":
    main()

