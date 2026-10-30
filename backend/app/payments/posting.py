"""Mifos X posting files.

Loan repayments: one row per matched payment, in the Mifos X bulk-import
layout for loan repayments. Columns are configurable; the default follows the
spec. Confirm column names and date format against the lender's Mifos version
before the pilot (Mifos bulk import templates use "dd MMMM yyyy").

A payment can never be exported twice: posting_batch_rows has a unique
constraint on payment_id, and selection excludes anything already exported.
"""
import csv
import io
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.events import EventType, emit
from app.models import Branch, Loan, Payment, Plan, PostingBatch, PostingBatchRow, Schedule, Tenant
from app.money import from_minor

DEFAULT_COLUMNS = [
    {"key": "office", "header": "Office Name"},
    {"key": "loan_account", "header": "Loan Account No."},
    {"key": "date", "header": "Transaction Date"},
    {"key": "amount", "header": "Amount"},
    {"key": "payment_type", "header": "Payment Type"},
    {"key": "receipt", "header": "Receipt No."},
    {"key": "note", "header": "Note"},
]
PAYMENT_TYPE = {"mock": "Mobile Wallet", "mmqr": "MMQR", "khqr": "KHQR"}


class NothingToExport(Exception):
    pass


def exportable(session: Session, tenant: Tenant, date_from: date, date_to: date) -> list[Payment]:
    exported = select(PostingBatchRow.payment_id)
    return list(session.scalars(select(Payment).where(
        Payment.tenant_id == tenant.id, Payment.match_status == "matched", Payment.id.not_in(exported))
        .order_by(Payment.paid_at)))


def create_batch(session: Session, tenant: Tenant, date_from: date, date_to: date, actor: str,
                 columns: list[dict] | None = None) -> PostingBatch:
    columns = columns or DEFAULT_COLUMNS
    pays = [p for p in exportable(session, tenant, date_from, date_to)
            if date_from <= p.paid_at.astimezone(clock.local_now(tenant).tzinfo).date() <= date_to]
    if not pays:
        raise NothingToExport("No matched payments left to export in that range")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["header"] for c in columns])
    tz = clock.local_now(tenant).tzinfo
    for p in pays:
        loan = session.get(Loan, p.loan_id)
        office = session.get(Branch, loan.branch_id).name
        values = {
            "office": office, "loan_account": loan.external_id,
            "date": p.paid_at.astimezone(tz).strftime("%d %B %Y"),
            "amount": from_minor(p.amount, p.currency), "payment_type": PAYMENT_TYPE.get(p.provider, p.provider),
            "receipt": p.reference or p.external_txn_id,
            "note": f"Tenpai {p.kind or ''} payment, matched by {p.match_method}".strip(),
            "currency": p.currency, "provider_txn": p.external_txn_id,
        }
        w.writerow([values.get(c["key"], "") for c in columns])
    now = clock.now(tenant)
    batch = PostingBatch(tenant_id=tenant.id, date_from=date_from, date_to=date_to, columns=columns,
                         row_count=len(pays), file_name=f"mifos-repayments-{tenant.id}-{date_from}-{date_to}.csv",
                         content=buf.getvalue(), created_by=actor, created_at=now)
    session.add(batch)
    session.flush()
    for p in pays:
        session.add(PostingBatchRow(batch_id=batch.id, payment_id=p.id))
        emit(session, tenant_id=tenant.id, type=EventType.payment_exported, at=now, actor=actor,
             policy_version=tenant.current_policy_version, case_id=p.case_id, loan_id=p.loan_id,
             payload={"payment_id": p.id, "batch_id": batch.id, "amount": p.amount})
    session.flush()  # the unique constraint fires here if a payment slipped in twice
    return batch


def restructure_export(session: Session, tenant: Tenant, actor: str) -> str:
    """Loans with accepted plans: the new schedule and a restructured flag, for
    the lender's credit team to book in Mifos. Tenpai flags; it does not
    reclassify or provision."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Office Name", "Loan Account No.", "Client Name", "Restructured", "Plan Type", "Plan ID",
                "Accepted On", "Approved Within Policy", "Breaches", "Instalment No.", "Due Date", "Amount",
                "Currency"])
    tz = clock.local_now(tenant).tzinfo
    plans = session.scalars(select(Plan).where(Plan.tenant_id == tenant.id, Plan.status == "active")
                            .order_by(Plan.id))
    n = 0
    for plan in plans:
        loan = session.get(Loan, plan.loan_id)
        from app.models import Borrower

        b = session.get(Borrower, loan.borrower_id)
        office = session.get(Branch, loan.branch_id).name
        breaches = "; ".join(f"{x['label']} {x['value']} vs {x['limit']}" for x in plan.breaches)
        for p in plan.details["periods"]:
            w.writerow([office, loan.external_id, b.name, "Y", plan.option_type, plan.id,
                        plan.accepted_at.astimezone(tz).strftime("%d %B %Y") if plan.accepted_at else "",
                        "Y" if plan.within_policy else "N", breaches, p["no"],
                        date.fromisoformat(p["due_date"]).strftime("%d %B %Y"),
                        from_minor(p["amount"], loan.currency), loan.currency])
        n += 1
    emit(session, tenant_id=tenant.id, type=EventType.restructure_exported, at=clock.now(tenant), actor=actor,
         policy_version=tenant.current_policy_version, payload={"plans": n})
    return buf.getvalue()
