"""Signed per-borrower links. The token names a case and expiry and carries an
HMAC, so a link opens only that borrower's Mini App and cannot be guessed."""
import hashlib
import hmac
import os
import time

from app.config import LINK_SIGNING_SECRET

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5173")
LINK_TTL_DAYS = 30


def _sig(body: str) -> str:
    return hmac.new(LINK_SIGNING_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:16]


def _b36(n: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = chars[r] + out
    return out or "0"


def make_token(tenant_id: str, borrower_id: int, case_id: int | None, now_ts: float | None = None) -> str:
    exp = int((now_ts or time.time()) + LINK_TTL_DAYS * 86400)
    body = f"{tenant_id}.{borrower_id}.{case_id or 0}.{_b36(exp)}"
    return f"{body}.{_sig(body)}"


def read_token(token: str, now_ts: float | None = None) -> tuple[str, int, int | None]:
    try:
        tenant_id, borrower_id, case_id, exp, sig = token.rsplit(".", 4)
    except ValueError:
        raise ValueError("malformed link")
    body = f"{tenant_id}.{borrower_id}.{case_id}.{exp}"
    if not hmac.compare_digest(sig, _sig(body)):
        raise ValueError("invalid link")
    if int(exp, 36) < (now_ts or time.time()):
        raise ValueError("link expired")
    return tenant_id, int(borrower_id), int(case_id) or None


def mini_app_url(token: str) -> str:
    return f"{PUBLIC_BASE_URL}/m/{token}"


def telegram_app_link(bot_username: str, token: str) -> str:
    """What the borrower sees in the message: a Telegram Mini App direct link."""
    return f"https://t.me/{bot_username}/app?startapp={token}"


def telegram_start_link(bot_username: str, token: str) -> str:
    """Opt-in deep link: opens the bot, which asks the borrower to share their phone."""
    return f"https://t.me/{bot_username}?start={token}"
