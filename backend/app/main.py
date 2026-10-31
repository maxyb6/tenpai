import base64
import hmac
import logging
import threading

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.api import admin, cases, demo, field, mini, payments, portfolio
from app.config import DEMO_AS_OF, DEMO_PASSWORD, FRONTEND_DIST, SEED_ON_START
from app.db import SessionLocal, get_session
from app.models import Event, Tenant

log = logging.getLogger("tenpai")
SEED_STATE = {"status": "idle"}

app = FastAPI(title="Tenpai Collections", version="0.2.0")
for r in (portfolio.router, portfolio.sample_router, cases.router, mini.router, demo.router, payments.router,
          field.router, admin.router):
    app.include_router(r)


# Borrower-facing paths never ask for the console password: a borrower opens
# their Mini App link on their own phone.
OPEN_PREFIXES = ("/api/mini/", "/m/", "/assets/", "/api/health", "/sw.js", "/manifest.webmanifest", "/icon.svg")


@app.middleware("http")
async def demo_password(request: Request, call_next):
    if not DEMO_PASSWORD or request.url.path.startswith(OPEN_PREFIXES):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            _, _, password = base64.b64decode(header[6:]).decode().partition(":")
            if hmac.compare_digest(password, DEMO_PASSWORD):
                return await call_next(request)
        except Exception:  # noqa: BLE001
            pass
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Collections demo"'})


def _seed_if_empty():
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from app.seed.loader import seed_empty_tenant, seed_tenant

    with SessionLocal() as s:
        if s.scalar(select(func.count(Tenant.id))):
            SEED_STATE["status"] = "ready"
            return
    as_of = date.fromisoformat(DEMO_AS_OF) if DEMO_AS_OF else datetime.now(ZoneInfo("Asia/Yangon")).date()
    SEED_STATE.update(status="seeding", as_of=as_of.isoformat())
    try:
        for market in ("MM", "KH"):
            SEED_STATE["tenant"] = market
            with SessionLocal() as s:
                seed_tenant(s, market, as_of, write_sample=False)
                if market == "MM":
                    seed_empty_tenant(s, market, as_of)
                s.commit()
        SEED_STATE["status"] = "ready"
    except Exception as e:  # noqa: BLE001
        log.exception("seeding failed")
        SEED_STATE.update(status="failed", error=str(e))


@app.on_event("startup")
def _startup():
    from app.messaging import bot

    bot.start()
    if SEED_ON_START:
        threading.Thread(target=_seed_if_empty, name="seed", daemon=True).start()


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {"ok": True, "seed": SEED_STATE}


@app.get("/api/tenants")
def tenants(session: Session = Depends(get_session)):
    return [
        {"id": t.id, "name": t.name, "market": t.market, "is_demo": t.is_demo, "brand": t.brand,
         "timezone": t.timezone, "now": clock.local_now(t).isoformat(),
         "policy_version": t.current_policy_version,
         "events": session.scalar(select(func.count(Event.id)).where(Event.tenant_id == t.id))}
        for t in session.scalars(select(Tenant).order_by(Tenant.market.desc()))
    ]


# The built console, when present (the single-image deploy). Any non-API path
# falls back to index.html so client-side routes like /field and /m/<token> work.
if FRONTEND_DIST.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_file() and str(target).startswith(str(FRONTEND_DIST.resolve())):
            return FileResponse(target)
        if SEED_STATE.get("status") == "seeding":
            return Response(
                "<!doctype html><meta http-equiv=refresh content=10><body style='font-family:sans-serif;padding:40px'>"
                f"Preparing sample data ({SEED_STATE.get('tenant', '')}), about 4 minutes on first start. "
                "This page refreshes itself.</body>", media_type="text/html")
        return FileResponse(FRONTEND_DIST / "index.html")
