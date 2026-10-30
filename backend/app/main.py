from fastapi import Depends, FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.api import admin, cases, demo, field, mini, payments, portfolio
from app.db import get_session
from app.models import Event, Tenant

app = FastAPI(title="Tenpai Collections", version="0.2.0")
for r in (portfolio.router, portfolio.sample_router, cases.router, mini.router, demo.router, payments.router,
          field.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {"ok": True}


@app.get("/api/tenants")
def tenants(session: Session = Depends(get_session)):
    return [
        {"id": t.id, "name": t.name, "market": t.market, "is_demo": t.is_demo, "brand": t.brand,
         "timezone": t.timezone, "now": clock.local_now(t).isoformat(),
         "policy_version": t.current_policy_version,
         "events": session.scalar(select(func.count(Event.id)).where(Event.tenant_id == t.id))}
        for t in session.scalars(select(Tenant).order_by(Tenant.market.desc()))
    ]
