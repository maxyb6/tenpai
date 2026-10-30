"""Telegram delivery.

Simulated by default: the message is "delivered" into the in-app chat, which
renders exactly like the phone preview. If TELEGRAM_BOT_TOKEN is set and the
borrower's link has a chat id (they started the real bot), the message also
goes out through the Bot API with the lender's buttons. Calls go straight to
the Bot API over httpx, so no extra Telegram library is needed.
"""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TELEGRAM_BOT_TOKEN
from app.messaging import links
from app.models import Message, TelegramLink, Template, Tenant

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def live() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def call(method: str, **params) -> dict:
    r = httpx.post(API.format(token=TELEGRAM_BOT_TOKEN, method=method), json=params, timeout=15)
    r.raise_for_status()
    return r.json()


def keyboard(tpl: Template, token: str) -> dict | None:
    if not tpl.buttons:
        return None
    url = links.mini_app_url(token)
    rows = []
    for b in tpl.buttons:
        target = url if b["action"] == "open_mini_app" else f"{url}?start={b['action']}"
        # web_app buttons need an https URL registered with BotFather; fall back to a plain link.
        button = {"text": b["label"], "web_app": {"url": target}} if target.startswith("https://") else \
            {"text": b["label"], "url": target}
        rows.append([button])
    return {"inline_keyboard": rows}


def deliver(session: Session, tenant: Tenant, msg: Message) -> bool:
    """Returns True when the message counts as delivered."""
    if msg.channel == "sms":
        return True  # mock SMS provider
    if not live():
        return True
    link = session.scalars(select(TelegramLink).where(TelegramLink.borrower_id == msg.borrower_id)
                           .order_by(TelegramLink.id.desc())).first()
    if link is None or link.chat_id is None:
        return True  # sample borrower with no real chat: stays in the simulated chat
    tpl = session.get(Template, msg.template_id)
    try:
        params = {"chat_id": link.chat_id, "text": msg.body}
        kb = keyboard(tpl, (msg.variables or {}).get("token", ""))
        if kb:
            params["reply_markup"] = kb
        out = call("sendMessage", **params)
        msg.external_id = str(out.get("result", {}).get("message_id"))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("telegram send failed: %s", e)
        msg.status = "failed"
        return False
