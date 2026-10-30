"""Payments: matching rules and the posting file. No payment is ever exported twice."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Case, Loan, Payment, PostingBatchRow, Tenant
from app.payments import posting
from app.payments import service as pay_svc
from app.payments.provider import PaymentIn

TZ = ZoneInfo("Asia/Yangon")


def _open_case(session):
    return session.scalars(select(Case).where(Case.tenant_id == "mm-demo", Case.status == "open",
                                              Case.arm == "treatment").order_by(Case.id)).first()


def _pay(session, tenant, ref, amount, cur, phone=None, txn=None):
    return pay_svc.receive(session, tenant, PaymentIn(
        external_txn_id=txn or f"T{ref}{amount}", reference=ref, amount=amount, currency=cur, payer_phone=phone,
        paid_at=tenant.demo_now, raw={}))


def test_match_by_reference_then_phone_then_manual(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    tenant.demo_now = datetime(2026, 11, 5, 11, 0, tzinfo=TZ)
    case = _open_case(session)
    loan = session.get(Loan, case.loan_id)
    req, _ = pay_svc.create_request(session, tenant, loan, case, 10_000, actor="test")
    p1 = _pay(session, tenant, req.reference, 10_000, loan.currency)
    assert p1.match_status == "matched" and p1.match_method == "reference" and p1.kind == "partial"
    req2, _ = pay_svc.create_request(session, tenant, loan, case, 12_300, actor="test")
    from app.models import Borrower

    phone = session.get(Borrower, loan.borrower_id).phone
    p2 = _pay(session, tenant, None, 12_300, loan.currency, phone=phone)
    assert p2.match_status == "matched" and p2.match_method == "amount_phone_date"
    p3 = _pay(session, tenant, "NOPE", 777, loan.currency)
    assert p3.match_status == "unmatched"
    pay_svc.match(session, tenant, p3, loan.id, "manual", actor="test")
    assert p3.match_status == "matched" and p3.match_method == "manual"
    # Retried notifications are idempotent.
    assert _pay(session, tenant, req.reference, 10_000, loan.currency).id == p1.id


def test_no_payment_is_exported_twice(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    tenant.demo_now = datetime(2026, 11, 5, 11, 0, tzinfo=TZ)
    case = _open_case(session)
    loan = session.get(Loan, case.loan_id)
    req, _ = pay_svc.create_request(session, tenant, loan, case, 5_000, actor="test")
    _pay(session, tenant, req.reference, 5_000, loan.currency)
    wide = (date(2026, 1, 1), date(2026, 12, 31))
    first = posting.create_batch(session, tenant, *wide, actor="test")
    assert first.row_count >= 1
    with pytest.raises(posting.NothingToExport):
        posting.create_batch(session, tenant, *wide, actor="test")
    exported = session.scalar(select(func.count()).select_from(PostingBatchRow))
    distinct = session.scalar(select(func.count(func.distinct(PostingBatchRow.payment_id))))
    assert exported == distinct
    # The database refuses a second row for the same payment even if code tried.
    pid = session.scalars(select(PostingBatchRow.payment_id)).first()
    session.add(PostingBatchRow(batch_id=first.id, payment_id=pid))
    with pytest.raises(IntegrityError):
        session.flush()


def test_posting_file_columns(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    tenant.demo_now = datetime(2026, 11, 5, 11, 0, tzinfo=TZ)
    case = _open_case(session)
    loan = session.get(Loan, case.loan_id)
    req, _ = pay_svc.create_request(session, tenant, loan, case, 4_200, actor="test")
    _pay(session, tenant, req.reference, 4_200, loan.currency)
    b = posting.create_batch(session, tenant, date(2026, 11, 5), date(2026, 11, 5), actor="test")
    header, *rows = b.content.strip().splitlines()
    assert header == "Office Name,Loan Account No.,Transaction Date,Amount,Payment Type,Receipt No.,Note"
    assert any(loan.external_id in r and "05 November 2026" in r and req.reference in r for r in rows)
