"""The daily run, driven by the tenant clock so the demo can advance a day.

Order: resolve promises due yesterday, send scheduled messages that are now
allowed, rescore, assign visits for the Visit segment, then plan today's
outreach per bucket strategy (pre-due reminders, Telegram invites, reminders).
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.domain.ranking import score_open_cases
from app.events import EventType, emit
from app.messaging import service as msg
from app.messaging.templates_seed import category
from app.models import Borrower, Case, Loan, Message, Promise, TelegramLink, Tenant, Visit
from app.services import cases as case_svc


def sweep_promises(session: Session, tenant: Tenant, today, now, version: int, send: bool = True) -> tuple[int, int]:
    broken = reminders = 0
    for p in session.scalars(select(Promise).where(Promise.tenant_id == tenant.id, Promise.status == "open",
                                                   Promise.due_date < today)):
        case = session.get(Case, p.case_id)
        p.status, p.resolved_at = ("partial" if case.collected_amount > 0 else "broken"), now
        emit(session, tenant_id=tenant.id, type=EventType.ptp_broken, at=now, actor="system", policy_version=version,
             case_id=case.id, loan_id=case.loan_id, borrower_id=case.borrower_id,
             payload={"promise_id": p.id, "amount": p.amount, "due_date": p.due_date, "status": p.status})
        broken += 1
        if send and case.status == "open" and case.arm == "treatment":
            msg.send(session, tenant, borrower=session.get(Borrower, case.borrower_id), case=case,
                     key="promise_broken", at=now, extra={"promise_amount": p.amount, "promise_date": p.due_date})
        if case.state == "promised":
            case.state = "contacting"
    for p in session.scalars(select(Promise).where(Promise.tenant_id == tenant.id, Promise.status == "open",
                                                   Promise.due_date == today)):
        case = session.get(Case, p.case_id)
        if send and case.arm == "treatment" and case.status == "open":
            msg.send(session, tenant, borrower=session.get(Borrower, case.borrower_id), case=case,
                     key="promise_reminder", at=now, extra={"promise_amount": p.amount, "promise_date": p.due_date})
            reminders += 1
    return broken, reminders


def run(session: Session, tenant: Tenant, actor: str = "system:scheduler") -> dict:
    version, policy = policy_mod.current(session, tenant)
    now = clock.now(tenant)
    today = clock.today(tenant)
    stats = {"promises_broken": 0, "promise_reminders": 0, "sent_scheduled": 0, "visits_assigned": 0,
             "invites": 0, "reminders": 0, "pre_due": 0}

    # 1. Promises past their date and not kept.
    stats["promises_broken"], stats["promise_reminders"] = sweep_promises(session, tenant, today, now, version)

    # 2. Messages rescheduled by the gate.
    stats["sent_scheduled"] = msg.process_due(session, tenant, actor)

    # 4. Outreach per bucket strategy, treatment only.
    strategies = {s.bucket: s for s in policy.strategy}
    linked = set(session.scalars(select(TelegramLink.borrower_id).where(
        TelegramLink.tenant_id == tenant.id, TelegramLink.status == "active")))
    open_cases = list(session.scalars(select(Case).where(Case.tenant_id == tenant.id, Case.status == "open")))
    for case in open_cases:
        if case.arm != "treatment" or case.automation_paused or case.segment in ("sensitive", "visit"):
            continue
        if case.state in ("promised", "plan_pending", "plan_active"):
            continue
        borrower = session.get(Borrower, case.borrower_id)
        if case.borrower_id not in linked:
            invited = session.scalar(select(func.count(Message.id)).where(
                Message.case_id == case.id, Message.template_key == "telegram_invite"))
            if not invited and borrower.phone:
                msg.send(session, tenant, borrower=borrower, case=case, key="telegram_invite", at=now)
                stats["invites"] += 1
            continue
        s = strategies.get(case.bucket)
        if not s:
            continue
        attempts = session.scalar(select(func.count(Message.id)).where(
            Message.case_id == case.id, Message.direction == "out", Message.status.in_(("sent", "delivered", "read")),
            Message.template_key.in_(s.templates))) or 0
        if attempts >= s.attempts:
            continue
        if case.last_contact_at and (now - case.last_contact_at) < timedelta(days=s.days_between_attempts):
            continue
        pending = session.scalar(select(func.count(Message.id)).where(
            Message.case_id == case.id, Message.status == "planned"))
        if pending:
            continue
        key = s.templates[min(attempts, len(s.templates) - 1)]
        if key == "visit_notice":
            continue  # sent when a visit is assigned
        msg.send(session, tenant, borrower=borrower, case=case, key=key, at=now)
        stats["reminders"] += 1

    # 3. Rescore and assign visits.
    score_open_cases(session, tenant, actor)
    open_cases = list(session.scalars(select(Case).where(Case.tenant_id == tenant.id, Case.status == "open")))
    for case in open_cases:
        if case.arm == "treatment" and case.segment == "visit" and case.state not in ("plan_pending", "plan_active"):
            has = session.scalar(select(func.count(Visit.id)).where(Visit.case_id == case.id,
                                                                    Visit.status == "assigned"))
            if not has:
                case_svc.assign_visit(session, tenant, case, actor=actor, notify=False)
                stats["visits_assigned"] += 1

    # 5. Pre-due reminders for current loans (no case), Telegram-linked borrowers only.
    pre = strategies.get("pre_due")
    if pre:
        for loan in session.scalars(select(Loan).where(
                Loan.tenant_id == tenant.id, Loan.status == "active", Loan.days_overdue == 0,
                Loan.next_due_date.in_([today + timedelta(days=3), today]))):
            if loan.borrower_id not in linked:
                continue
            key = "due_day_reminder" if loan.next_due_date == today else "pre_due_reminder"
            already = session.scalar(select(func.count(Message.id)).where(
                Message.borrower_id == loan.borrower_id, Message.template_key == key,
                Message.planned_at >= now - timedelta(days=4)))
            if already:
                continue
            msg.send(session, tenant, borrower=session.get(Borrower, loan.borrower_id), case=None, key=key, at=now,
                     extra={"amount_due": loan.instalment_amount, "due_date": loan.next_due_date})
            stats["pre_due"] += 1
    session.flush()
    return stats


def advance_day(session: Session, tenant: Tenant, actor: str) -> dict:
    """Demo: move the clock to 09:00 the next local day and run the daily job."""
    tz = ZoneInfo(tenant.timezone)
    local = clock.local_now(tenant)
    nxt = datetime.combine(local.date() + timedelta(days=1), time(9, 0), tz)
    before = clock.now(tenant)
    tenant.demo_now = nxt
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.clock_advanced, at=nxt, actor=actor,
         policy_version=tenant.current_policy_version, payload={"from": before, "to": nxt})
    # Overdue loans age by a day between imports.
    for loan in session.scalars(select(Loan).where(Loan.tenant_id == tenant.id, Loan.days_overdue > 0)):
        loan.days_overdue += 1
    from app.ingest.pipeline import refresh_cases

    refresh_cases(session, tenant, nxt, actor)
    return run(session, tenant, actor)
