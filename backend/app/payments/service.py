"""Payment requests, notifications and matching.

Matching order: by reference; then amount + payer phone + date window against
open requests; otherwise the manual queue. Partial and over-payments are
allowed and recorded as such.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.events import EventType, emit
from app.models import Borrower, Case, Loan, Payment, PaymentRequest, Promise, Tenant
from app.payments.provider import PaymentIn, provider_for

MATCH_WINDOW_DAYS = 3


def create_request(session: Session, tenant: Tenant, loan: Loan, case: Case | None, amount: int,
                   actor: str) -> tuple[PaymentRequest, dict]:
    now = clock.now(tenant)
    provider = provider_for("mock")
    out = provider.create_request(tenant_id=tenant.id, loan_external_id=loan.external_id, amount=amount,
                                  currency=loan.currency, now=now)
    req = PaymentRequest(tenant_id=tenant.id, case_id=case.id if case else None, loan_id=loan.id,
                         reference=out["reference"], amount=amount, currency=loan.currency, provider=provider.name,
                         qr_payload=out["qr_payload"], deeplink=out["deeplink"], status="open", created_at=now,
                         expires_at=out["expires_at"])
    session.add(req)
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.payment_requested, at=now, actor=actor,
         policy_version=tenant.current_policy_version, case_id=req.case_id, loan_id=loan.id,
         borrower_id=loan.borrower_id,
         payload={"request_id": req.id, "reference": req.reference, "amount": amount, "currency": loan.currency,
                  "provider": provider.name})
    return req, out


def outstanding_arrears(session: Session, loan: Loan) -> int:
    """Arrears per the last import, less payments Tenpai has matched since."""
    paid = sum(p.amount for p in session.scalars(select(Payment).where(
        Payment.loan_id == loan.id, Payment.match_status == "matched")) if loan.arrears_as_of is None
        or p.paid_at.date() >= loan.arrears_as_of)
    return max(0, loan.amount_overdue - paid)


def active_plan_schedule(session: Session, loan: Loan) -> list:
    """Unpaid periods of the newest Tenpai schedule version (an accepted plan)."""
    from app.models import Schedule
    from sqlalchemy import func as f

    latest = session.scalar(select(f.max(Schedule.version)).where(Schedule.loan_id == loan.id)) or 1
    if latest == 1:
        return []
    return list(session.scalars(select(Schedule).where(
        Schedule.loan_id == loan.id, Schedule.version == latest, Schedule.paid_amount < Schedule.total_due)
        .order_by(Schedule.instalment_no)))


def amount_due_now(session: Session, loan: Loan) -> int:
    """What a "pay now" button should ask for: the next plan instalment when a
    plan is active, otherwise the arrears."""
    periods = active_plan_schedule(session, loan)
    if periods:
        return periods[0].total_due - periods[0].paid_amount
    return outstanding_arrears(session, loan)


def receive(session: Session, tenant: Tenant, p: PaymentIn, provider: str = "mock") -> Payment:
    now = clock.now(tenant)
    existing = session.scalars(select(Payment).where(Payment.provider == provider,
                                                     Payment.external_txn_id == p.external_txn_id)).first()
    if existing:
        return existing  # notifications are retried; idempotent
    pay = Payment(tenant_id=tenant.id, provider=provider, external_txn_id=p.external_txn_id, reference=p.reference,
                  amount=p.amount, currency=p.currency, payer_phone=p.payer_phone, paid_at=p.paid_at,
                  received_at=now, raw=p.raw, match_status="unmatched")
    session.add(pay)
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.payment_received, at=now, actor=f"provider:{provider}",
         policy_version=tenant.current_policy_version,
         payload={"payment_id": pay.id, "reference": p.reference, "amount": p.amount, "currency": p.currency,
                  "paid_at": p.paid_at})
    req, method = None, None
    if p.reference:
        req = session.scalars(select(PaymentRequest).where(PaymentRequest.tenant_id == tenant.id,
                                                           PaymentRequest.reference == p.reference)).first()
        method = "reference" if req else None
    if req is None and p.payer_phone:
        candidates = session.execute(
            select(PaymentRequest).join(Loan, Loan.id == PaymentRequest.loan_id)
            .join(Borrower, Borrower.id == Loan.borrower_id)
            .where(PaymentRequest.tenant_id == tenant.id, PaymentRequest.status == "open",
                   PaymentRequest.amount == p.amount, PaymentRequest.currency == p.currency,
                   Borrower.phone == p.payer_phone,
                   PaymentRequest.created_at >= p.paid_at - timedelta(days=MATCH_WINDOW_DAYS),
                   PaymentRequest.created_at <= p.paid_at + timedelta(days=1))).scalars().all()
        if len(candidates) == 1:
            req, method = candidates[0], "amount_phone_date"
    if req is not None:
        match(session, tenant, pay, req.loan_id, method, actor="system", request=req)
    return pay


def match(session: Session, tenant: Tenant, pay: Payment, loan_id: int, method: str, actor: str,
          request: PaymentRequest | None = None) -> Payment:
    now = clock.now(tenant)
    loan = session.get(Loan, loan_id)
    case = session.scalars(select(Case).where(Case.loan_id == loan.id, Case.status == "open")).first()
    due = outstanding_arrears(session, loan)
    pay.loan_id, pay.case_id = loan.id, case.id if case else None
    pay.payment_request_id = request.id if request else None
    pay.match_status, pay.match_method = "matched", method
    pay.kind = "full" if pay.amount == due else ("partial" if pay.amount < due else "over")
    if request:
        request.status = "paid"
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.payment_matched, at=now, actor=actor,
         policy_version=tenant.current_policy_version, case_id=pay.case_id, loan_id=loan.id,
         borrower_id=loan.borrower_id,
         payload={"payment_id": pay.id, "method": method, "amount": pay.amount, "kind": pay.kind,
                  "arrears_before": due, "arrears_after": max(0, due - pay.amount)})
    # Allocate against an active plan's schedule, oldest period first.
    remaining = pay.amount
    for period in active_plan_schedule(session, loan):
        if remaining <= 0:
            break
        take = min(remaining, period.total_due - period.paid_amount)
        period.paid_amount += take
        remaining -= take
        if period.paid_amount >= period.total_due:
            period.paid_on = pay.paid_at.date()
    if case:
        case.collected_amount += pay.amount
        _resolve_promises(session, tenant, case, now)
        from app.messaging import service as msg

        borrower = session.get(Borrower, loan.borrower_id)
        msg.send(session, tenant, borrower=borrower, case=case, key="payment_received", at=now, as_reply=True,
                 extra={"payment_amount": pay.amount, "payment_date": pay.paid_at.date(), "reference": pay.reference
                        or pay.external_txn_id})
        if outstanding_arrears(session, loan) <= 0 and case.state != "plan_active":
            close_case(session, tenant, case, "cured", now, actor)
    return pay


def _resolve_promises(session, tenant, case, now):
    paid = case.collected_amount
    for pr in session.scalars(select(Promise).where(Promise.case_id == case.id, Promise.status == "open")):
        if paid >= pr.amount:
            pr.status, pr.resolved_at = "kept", now
            emit(session, tenant_id=tenant.id, type=EventType.ptp_kept, at=now, actor="system",
                 policy_version=tenant.current_policy_version, case_id=case.id, loan_id=case.loan_id,
                 borrower_id=case.borrower_id, payload={"promise_id": pr.id, "amount": pr.amount})


def close_case(session, tenant, case: Case, reason: str, at: datetime, actor: str):
    case.status, case.state, case.close_reason, case.closed_at = "closed", "closed", reason, at
    emit(session, tenant_id=tenant.id, type=EventType.case_closed, at=at, actor=actor,
         policy_version=tenant.current_policy_version, case_id=case.id, loan_id=case.loan_id,
         borrower_id=case.borrower_id, payload={"reason": reason, "collected": case.collected_amount})
