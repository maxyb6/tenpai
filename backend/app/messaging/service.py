"""Outbound and inbound messaging.

Outbound: pick the approved template, fill variables, run the send gate, then
deliver (simulated chat, or real Telegram when TELEGRAM_BOT_TOKEN is set).
Blocked messages are logged with rule ID and rescheduled to the next allowed
time. Inbound: normalise Zawgyi, classify, act (pause, flag, route).
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.events import EventType, emit
from app.messaging import gate, links, locale
from app.messaging.classifier import CLASSIFIER, PAUSING, normalise_burmese
from app.messaging.templates_seed import category
from app.models import Borrower, Case, Complaint, Flag, Loan, Message, Officer, TelegramLink, Template, Tenant


def template_for(session: Session, tenant: Tenant, key: str, language: str) -> Template:
    q = (select(Template).where(Template.tenant_id == tenant.id, Template.key == key,
                                Template.language == language, Template.status != "retired")
         .order_by((Template.status == "approved").desc(), Template.version.desc()))
    tpl = session.scalars(q).first()  # newest approved version; a draft only if nothing is approved
    if tpl is None and language != "en":
        return template_for(session, tenant, key, "en")
    if tpl is None:
        raise LookupError(f"no template {key}")
    return tpl


def _fmt_value(key: str, value, currency: str, lang: str):
    if isinstance(value, int) and key.endswith(("amount", "amount_due", "instalment")):
        return locale.money(value, currency, lang)
    if isinstance(value, date):
        return locale.day(value, lang)
    if isinstance(value, int):
        return locale.number(value, lang)
    return value


def build_variables(session: Session, tenant: Tenant, borrower: Borrower, case: Case | None, loan: Loan | None,
                    lang: str, extra: dict | None = None) -> dict:
    _, policy = policy_mod.current(session, tenant)
    brand = tenant.brand
    token = links.make_token(tenant.id, borrower.id, case.id if case else None, clock.now(tenant).timestamp())
    officer = session.get(Officer, loan.officer_id) if loan and loan.officer_id else None
    local = lang != "en"
    raw = {
        "borrower_name": (borrower.name_local or borrower.name) if local else borrower.name,
        "lender_name": (brand.get("lender_name_local") or brand.get("lender_name")) if local else brand.get("lender_name"),
        "lender_phone": brand.get("lender_phone", ""),
        "pay_link": links.telegram_app_link(brand.get("bot_username", "lender_bot"), token),
        "invite_link": links.telegram_start_link(brand.get("bot_username", "lender_bot"), token),
        "sla_hours": policy.slas.approval_hours,
        "officer_name": ((officer.name_local or officer.name) if local else officer.name) if officer else "",
    }
    currency = loan.currency if loan else tenant.reporting_currency
    if loan:
        raw["amount_due"] = loan.amount_overdue if loan.amount_overdue > 0 else loan.instalment_amount
        raw["due_date"] = loan.next_due_date
        raw["days_overdue"] = loan.days_overdue
    raw.update(extra or {})
    return {k: _fmt_value(k, v, currency, lang) for k, v in raw.items()}, token


def render(body: str, variables: dict) -> str:
    class Safe(dict):
        def __missing__(self, k):
            return "{" + k + "}"

    return body.format_map(Safe({k: "" if v is None else v for k, v in variables.items()}))


def send(session: Session, tenant: Tenant, *, borrower: Borrower, case: Case | None, key: str,
         actor: str = "system", extra: dict | None = None, at: datetime | None = None,
         as_reply: bool = False) -> Message | None:
    """Returns None when the borrower has no channel for this template at all
    (not on Telegram, never linked): there is nothing to plan or gate."""
    at = at or clock.now(tenant)
    if key != "telegram_invite" and not session.scalar(
            select(func.count(TelegramLink.id)).where(TelegramLink.borrower_id == borrower.id)):
        return None
    loan = session.get(Loan, case.loan_id) if case else session.scalars(
        select(Loan).where(Loan.borrower_id == borrower.id, Loan.status == "active")).first()
    tpl = template_for(session, tenant, key, borrower.language)
    tpl_en = template_for(session, tenant, key, "en")
    vars_local, token = build_variables(session, tenant, borrower, case, loan, tpl.language, extra)
    vars_en, _ = build_variables(session, tenant, borrower, case, loan, "en", extra)
    msg = Message(
        tenant_id=tenant.id, case_id=case.id if case else None, borrower_id=borrower.id, direction="out",
        channel=tpl.channel, template_id=tpl.id, template_key=key, template_version=tpl.version,
        language=tpl.language, body=render(tpl.body, vars_local), body_shadow=render(tpl_en.body, vars_en),
        variables={"token": token, "as_reply": as_reply, **{k: str(v) for k, v in vars_en.items()}},
        status="planned", planned_at=at,
    )
    session.add(msg)
    session.flush()
    version, _ = policy_mod.current(session, tenant)
    emit(session, tenant_id=tenant.id, type=EventType.message_planned, at=at, actor=actor, policy_version=version,
         case_id=msg.case_id, borrower_id=borrower.id, loan_id=loan.id if loan else None,
         payload={"message_id": msg.id, "template": key, "template_version": tpl.version,
                  "language": tpl.language, "channel": tpl.channel})
    dispatch(session, tenant, msg, at=at, actor=actor)
    return msg


def dispatch(session: Session, tenant: Tenant, msg: Message, *, at: datetime, actor: str = "system") -> Message:
    """Run the gate on a planned message, then send it or block and reschedule."""
    version, policy = policy_mod.current(session, tenant)
    borrower = session.get(Borrower, msg.borrower_id)
    case = session.get(Case, msg.case_id) if msg.case_id else None
    tpl = session.get(Template, msg.template_id)
    as_reply = bool((msg.variables or {}).get("as_reply"))
    d = gate.check(session, tenant, policy, version, borrower=borrower, case=case, template=tpl,
                   rendered=msg.body or "", channel=msg.channel, at=at, as_reply=as_reply)
    msg.gate_decision = "allowed" if d.allowed else "blocked"
    msg.gate_rule_id = d.rule_id
    msg.gate_trace = d.trace
    msg.policy_version = version
    common = dict(tenant_id=tenant.id, at=at, actor=actor, policy_version=version, case_id=msg.case_id,
                  borrower_id=msg.borrower_id, loan_id=case.loan_id if case else None)
    if not d.allowed:
        msg.status = "blocked"
        msg.next_allowed_at = d.next_allowed_at
        emit(session, type=EventType.message_blocked, payload={
            "message_id": msg.id, "template": msg.template_key, "rule_id": d.rule_id, "reason": d.reason,
            "next_allowed_at": d.next_allowed_at, "trace": d.trace}, **common)
        if d.next_allowed_at:
            retry = Message(**{c: getattr(msg, c) for c in (
                "tenant_id", "case_id", "borrower_id", "direction", "channel", "template_id", "template_key",
                "template_version", "language", "body", "body_shadow", "variables")},
                status="planned", planned_at=d.next_allowed_at)
            session.add(retry)
            session.flush()
            emit(session, type=EventType.message_planned, payload={
                "message_id": retry.id, "template": msg.template_key, "rescheduled_from": msg.id,
                "planned_for": d.next_allowed_at}, **common)
        session.flush()
        return msg

    msg.status = "sent"
    msg.sent_at = at
    emit(session, type=EventType.message_sent, payload={
        "message_id": msg.id, "template": msg.template_key, "template_version": msg.template_version,
        "channel": msg.channel, "language": msg.language, "trace": d.trace,
        "exempt_limits": d.exempt_limits}, **common)
    from app.messaging import telegram

    delivered = telegram.deliver(session, tenant, msg)
    if delivered:
        msg.status = "delivered"
        msg.delivered_at = at
        emit(session, type=EventType.message_delivered, payload={"message_id": msg.id}, **common)
    if case is not None and category(msg.template_key) not in ("transactional",) and not as_reply:
        case.contact_attempts += 1
        case.last_contact_at = at
        if case.state == "new":
            case.state = "contacting"
    session.flush()
    return msg


def process_due(session: Session, tenant: Tenant, actor: str = "system") -> int:
    now = clock.now(tenant)
    due = list(session.scalars(select(Message).where(
        Message.tenant_id == tenant.id, Message.status == "planned", Message.direction == "out",
        Message.planned_at <= now).order_by(Message.planned_at, Message.id)))
    for m in due:
        dispatch(session, tenant, m, at=now, actor=actor)
    return len(due)


def mark_read(session: Session, tenant: Tenant, borrower_id: int, at: datetime, actor: str = "borrower") -> int:
    unread = list(session.scalars(select(Message).where(
        Message.borrower_id == borrower_id, Message.direction == "out", Message.status.in_(("sent", "delivered")),
        Message.channel == "telegram")))
    for m in unread:
        m.status, m.read_at = "read", at
        emit(session, tenant_id=tenant.id, type=EventType.message_read, at=at, actor=actor, case_id=m.case_id,
             borrower_id=borrower_id, policy_version=m.policy_version, payload={"message_id": m.id})
    return len(unread)


# ---------------------------------------------------------------------------
# Inbound


def pause_case(session: Session, tenant: Tenant, case: Case, reason: str, at: datetime, actor: str) -> None:
    if case.automation_paused and case.pause_reason == reason:
        return
    case.automation_paused = True
    case.pause_reason = reason
    emit(session, tenant_id=tenant.id, type=EventType.automation_paused, at=at, actor=actor,
         policy_version=tenant.current_policy_version, case_id=case.id, loan_id=case.loan_id,
         borrower_id=case.borrower_id, payload={"reason": reason})


def raise_flag(session: Session, tenant: Tenant, *, borrower_id: int, case: Case | None, kind: str,
               subtype: str | None, source: str, text: str | None, at: datetime, actor: str,
               message_id: int | None = None) -> Flag:
    flag = Flag(tenant_id=tenant.id, borrower_id=borrower_id, case_id=case.id if case else None, kind=kind,
                subtype=subtype, source=source, message_id=message_id, text=text, active=True, raised_at=at,
                raised_by=actor)
    session.add(flag)
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.flag_raised, at=at, actor=actor,
         policy_version=tenant.current_policy_version, case_id=case.id if case else None,
         loan_id=case.loan_id if case else None, borrower_id=borrower_id,
         payload={"flag_id": flag.id, "kind": kind, "subtype": subtype, "source": source, "text": text})
    return flag


def open_complaint(session: Session, tenant: Tenant, *, borrower: Borrower, case: Case | None, text: str,
                   source: str, at: datetime, actor: str) -> Complaint:
    _, policy = policy_mod.current(session, tenant)
    c = Complaint(tenant_id=tenant.id, case_id=case.id if case else None, borrower_id=borrower.id, source=source,
                  text=text, status="open", opened_at=at, sla_due_at=at + timedelta(hours=policy.slas.complaint_hours))
    session.add(c)
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.complaint_opened, at=at, actor=actor,
         policy_version=tenant.current_policy_version, case_id=c.case_id, borrower_id=borrower.id,
         loan_id=case.loan_id if case else None, payload={"complaint_id": c.id, "source": source, "text": text})
    if case:
        pause_case(session, tenant, case, "open_complaint", at, actor)
    send(session, tenant, borrower=borrower, case=case, key="complaint_received", at=at,
         extra={"complaint_ref": f"C-{c.id:05d}", "sla_hours": policy.slas.complaint_hours}, as_reply=True)
    return c


def opt_out(session: Session, tenant: Tenant, borrower: Borrower, case: Case | None, at: datetime, actor: str):
    link = session.scalars(select(TelegramLink).where(TelegramLink.borrower_id == borrower.id,
                                                      TelegramLink.status == "active")).first()
    if link is None:
        return
    # Confirmation goes out first, while the link is still active.
    send(session, tenant, borrower=borrower, case=case, key="opt_out_confirmation", at=at, as_reply=True)
    link.status, link.opted_out_at = "opted_out", at
    emit(session, tenant_id=tenant.id, type=EventType.opted_out, at=at, actor=actor,
         policy_version=tenant.current_policy_version, case_id=case.id if case else None, borrower_id=borrower.id,
         payload={"channel": "telegram"})


def receive_reply(session: Session, tenant: Tenant, borrower: Borrower, text: str, *, channel: str = "telegram",
                  at: datetime | None = None, external_id: str | None = None, score: bool = True) -> Message:
    at = at or clock.now(tenant)
    case = session.scalars(select(Case).where(Case.borrower_id == borrower.id, Case.status == "open")).first()
    norm_info = {}
    if borrower.language == "my":
        text, norm_info = normalise_burmese(text)
    c = CLASSIFIER.classify(text, borrower.language)
    msg = Message(tenant_id=tenant.id, case_id=case.id if case else None, borrower_id=borrower.id, direction="in",
                  channel=channel, language=borrower.language, body=text, status="received", planned_at=at,
                  classification=c.label, classification_detail={**c.as_dict(), **norm_info},
                  external_id=external_id)
    session.add(msg)
    session.flush()
    common = dict(tenant_id=tenant.id, at=at, policy_version=tenant.current_policy_version,
                  case_id=msg.case_id, borrower_id=borrower.id, loan_id=case.loan_id if case else None)
    emit(session, type=EventType.reply_received, actor="borrower",
         payload={"message_id": msg.id, "text": text, "channel": channel, **norm_info}, **common)
    emit(session, type=EventType.reply_classified, actor="system",
         payload={"message_id": msg.id, **c.as_dict()}, **common)
    link = session.scalars(select(TelegramLink).where(TelegramLink.borrower_id == borrower.id,
                                                      TelegramLink.status == "active")).first()
    if link:
        link.last_inbound_at = at
    mark_read(session, tenant, borrower.id, at)

    if c.label in PAUSING:
        kind = {"vulnerability": "vulnerability", "dispute": "dispute", "complaint": "complaint",
                "stop": "opt_out"}[c.label]
        if c.label == "complaint":
            open_complaint(session, tenant, borrower=borrower, case=case, text=text, source="chat", at=at,
                           actor="borrower")
        elif c.label == "stop":
            opt_out(session, tenant, borrower, case, at, "borrower")
        if c.label != "complaint":
            raise_flag(session, tenant, borrower_id=borrower.id, case=case, kind=kind, subtype=c.subtype,
                       source="inbound_classifier", text=text, at=at, actor="system", message_id=msg.id)
        if case and c.label != "complaint":
            pause_case(session, tenant, case, {"vulnerability": "vulnerability", "dispute": "dispute",
                                               "stop": "opt_out"}[c.label], at, "system")
    elif c.label == "cant_pay" and case:
        send(session, tenant, borrower=borrower, case=case, key="plan_offer", at=at, as_reply=True)
        case.next_action = "Borrower asked for a plan"
    elif c.label == "already_paid" and case:
        case.next_action = "Check payment received"
    elif c.label == "will_pay" and case:
        case.next_action = "Confirm promise date"
    if case and score:
        from app.domain.ranking import score_open_cases

        score_open_cases(session, tenant, actor="system", case_ids=[case.id])
    session.flush()
    return msg


def sent_count(session: Session, case_id: int) -> int:
    return session.scalar(select(func.count(Message.id)).where(
        Message.case_id == case_id, Message.direction == "out", Message.status.in_(gate.SENT_STATUSES))) or 0
