from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.db import get_session
from app.models import Borrower, Case, Event, Loan, SavingsTransaction, Schedule, TelegramLink, Tenant

from app.api import portfolio

app = FastAPI(title="Tenpai Collections", version="0.1.0")
app.include_router(portfolio.router)
app.include_router(portfolio.sample_router)


def tenant_or_404(session: Session, tenant_id: str) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    return tenant


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {"ok": True}


@app.get("/api/tenants")
def tenants(session: Session = Depends(get_session)):
    return [
        {"id": t.id, "name": t.name, "market": t.market, "is_demo": t.is_demo, "brand": t.brand,
         "timezone": t.timezone, "now": clock.local_now(t).isoformat(),
         "policy_version": t.current_policy_version}
        for t in session.scalars(select(Tenant).order_by(Tenant.id))
    ]


@app.get("/api/tenants/{tenant_id}/overview")
def overview(tenant_id: str, session: Session = Depends(get_session)):
    """Stage 1 inspection endpoint: what's in the book and the log."""
    t = tenant_or_404(session, tenant_id)
    count = lambda model, *where: session.scalar(select(func.count()).select_from(model).where(*where))  # noqa: E731
    loan_ids = select(Loan.id).where(Loan.tenant_id == t.id)
    by_bucket = session.execute(
        select(Case.bucket, Case.arm, func.count(), func.sum(Case.amount_overdue_at_open))
        .where(Case.tenant_id == t.id, Case.status == "open")
        .group_by(Case.bucket, Case.arm)
    ).all()
    events = session.execute(
        select(Event.type, func.count()).where(Event.tenant_id == t.id).group_by(Event.type)
    ).all()
    version, _ = policy_mod.current(session, t)
    return {
        "tenant": t.name,
        "sample_data": t.is_demo,
        "now": clock.local_now(t).isoformat(),
        "policy_version": version,
        "counts": {
            "borrowers": count(Borrower, Borrower.tenant_id == t.id),
            "loans": count(Loan, Loan.tenant_id == t.id),
            "schedule_rows": count(Schedule, Schedule.loan_id.in_(loan_ids)),
            "savings_transactions": count(SavingsTransaction, SavingsTransaction.tenant_id == t.id),
            "telegram_linked": count(TelegramLink, TelegramLink.tenant_id == t.id, TelegramLink.status == "active"),
            "open_cases": count(Case, Case.tenant_id == t.id, Case.status == "open"),
            "events": count(Event, Event.tenant_id == t.id),
        },
        "open_cases_by_bucket": [
            {"bucket": b, "arm": arm, "cases": n, "amount_overdue": int(amt or 0)} for b, arm, n, amt in by_bucket
        ],
        "events_by_type": dict(sorted(events)),
    }


@app.get("/api/tenants/{tenant_id}/events")
def list_events(tenant_id: str, type: str | None = None, case_id: int | None = None, limit: int = 50,
                session: Session = Depends(get_session)):
    tenant_or_404(session, tenant_id)
    q = select(Event).where(Event.tenant_id == tenant_id)
    if type:
        q = q.where(Event.type == type)
    if case_id:
        q = q.where(Event.case_id == case_id)
    rows = session.scalars(q.order_by(Event.id.desc()).limit(min(limit, 500)))
    return [
        {"id": e.id, "type": e.type, "at": e.created_at.isoformat(), "actor": e.actor, "case_id": e.case_id,
         "loan_id": e.loan_id, "borrower_id": e.borrower_id, "policy_version": e.policy_version,
         "payload": e.payload}
        for e in rows
    ]
