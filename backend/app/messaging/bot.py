"""Live Telegram bot (long polling). Runs only when TELEGRAM_BOT_TOKEN is set.

Opt-in: the borrower opens t.me/<bot>?start=<signed token> (QR at disbursement,
an officer visit, or the one SMS invite), the bot asks them to share their
phone with Telegram's contact button, and the link is recorded with consent.
Replies are classified exactly like the simulated chat. Every message the bot
sends is an approved template; nothing is generated.
"""
import logging
import re
import threading
import time

from sqlalchemy import select

from app import clock
from app.config import TELEGRAM_BOT_TOKEN
from app.db import SessionLocal
from app.events import EventType, emit
from app.messaging import links, telegram
from app.messaging import service as msg
from app.models import Borrower, Case, TelegramLink, Tenant

log = logging.getLogger(__name__)
_pending: dict[int, tuple[str, int, int | None, str]] = {}  # chat_id -> (tenant, borrower, case, method)


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")[-9:]


def _send_template(s, tenant, borrower, chat_id: int, key: str, keyboard: dict | None = None):
    """Render an approved template and send it straight to a chat that is not
    linked yet (opt-in flow). Logged like any other message."""
    tpl = msg.template_for(s, tenant, key, borrower.language)
    vars_, _ = msg.build_variables(s, tenant, borrower, None, None, tpl.language)
    text = msg.render(tpl.body, vars_)
    params = {"chat_id": chat_id, "text": text}
    if keyboard:
        params["reply_markup"] = keyboard
    telegram.call("sendMessage", **params)


def handle(update: dict):
    m = update.get("message") or {}
    chat_id = (m.get("chat") or {}).get("id")
    if not chat_id:
        return
    text = m.get("text") or ""
    with SessionLocal() as s:
        if text.startswith("/start"):
            token = text.split(maxsplit=1)[1] if " " in text else ""
            try:
                tenant_id, borrower_id, case_id = links.read_token(token)
            except ValueError:
                return
            tenant, borrower = s.get(Tenant, tenant_id), s.get(Borrower, borrower_id)
            method = "sms_deeplink" if case_id else "disbursement_qr"
            _pending[chat_id] = (tenant_id, borrower_id, case_id, method)
            kb = {"keyboard": [[{"text": "📱", "request_contact": True}]], "one_time_keyboard": True,
                  "resize_keyboard": True}
            _send_template(s, tenant, borrower, chat_id, "optin_request", kb)
            s.commit()
            return
        contact = m.get("contact")
        if contact and chat_id in _pending:
            tenant_id, borrower_id, case_id, method = _pending.pop(chat_id)
            tenant, borrower = s.get(Tenant, tenant_id), s.get(Borrower, borrower_id)
            verified = _digits(contact.get("phone_number")) == _digits(borrower.phone)
            if not verified and not tenant.is_demo:
                return  # a real lender requires the phone on file
            now = clock.now(tenant)
            for old in s.scalars(select(TelegramLink).where(TelegramLink.borrower_id == borrower.id)):
                old.status = "replaced"
            s.add(TelegramLink(tenant_id=tenant.id, borrower_id=borrower.id, telegram_user_id=contact.get("user_id"),
                               chat_id=chat_id, username=(m.get("from") or {}).get("username"), method=method,
                               phone_verified=verified, consent_text_version="v1", status="active", linked_at=now))
            emit(s, tenant_id=tenant.id, type=EventType.telegram_linked, at=now, actor="borrower",
                 policy_version=tenant.current_policy_version, borrower_id=borrower.id, case_id=case_id,
                 payload={"method": method, "phone_verified": verified, "live": True,
                          "note": None if verified else "demo tenant: phone did not match sample number"})
            s.flush()
            case = s.scalars(select(Case).where(Case.borrower_id == borrower.id, Case.status == "open")).first()
            msg.send(s, tenant, borrower=borrower, case=case, key="optin_done", as_reply=True)
            s.commit()
            return
        link = s.scalars(select(TelegramLink).where(TelegramLink.chat_id == chat_id,
                                                    TelegramLink.status == "active")).first()
        if link and text:
            tenant, borrower = s.get(Tenant, link.tenant_id), s.get(Borrower, link.borrower_id)
            msg.receive_reply(s, tenant, borrower, text, external_id=str(m.get("message_id")))
            s.commit()


def _loop():
    offset = 0
    while True:
        try:
            out = telegram.call("getUpdates", offset=offset, timeout=25)
            for u in out.get("result", []):
                offset = u["update_id"] + 1
                try:
                    handle(u)
                except Exception:  # noqa: BLE001
                    log.exception("bot update failed")
        except Exception as e:  # noqa: BLE001
            log.warning("bot polling error: %s", e)
            time.sleep(5)


def start():
    if not TELEGRAM_BOT_TOKEN:
        return False
    threading.Thread(target=_loop, name="telegram-bot", daemon=True).start()
    return True
