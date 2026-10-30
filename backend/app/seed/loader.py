"""Seed a demo tenant: generate the sample book, write it as Mifos CSVs, and
import those CSVs through the real pipeline."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app import policy as policy_mod
from app.config import DATA_HOSTING_REGION, SAMPLE_DATA_DIR
from app.events import EventType, emit_many
from app.ingest import pipeline
from app.models import (
    Approval,
    Borrower,
    Branch,
    Case,
    ColumnMapping,
    Complaint,
    Event,
    Flag,
    Group,
    ImportBatch,
    Loan,
    Message,
    Officer,
    Payment,
    PaymentRequest,
    Plan,
    Policy,
    PostingBatch,
    PostingBatchRow,
    Promise,
    SavingsSnapshot,
    SavingsTransaction,
    Schedule,
    TelegramLink,
    Template,
    Tenant,
    User,
    Visit,
)
from app.seed import generator, mifos_export

# Children before parents.
TENANT_TABLES = [
    Event, Flag, Complaint, Visit, Payment, PaymentRequest, Approval, Plan, Promise, Message, Template,
    TelegramLink, Case, SavingsSnapshot, SavingsTransaction, User, ColumnMapping,
]


def reset_tenant(session: Session, tenant_id: str) -> None:
    """Demo only. The events trigger refuses DELETE unless this flag is set in
    the transaction and the tenant is a demo tenant."""
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return
    if not tenant.is_demo:
        raise PermissionError("only demo tenants can be reset")
    session.execute(text("SET LOCAL tenpai.allow_demo_reset = 'on'"))
    batch_ids = select(PostingBatch.id).where(PostingBatch.tenant_id == tenant_id)
    session.execute(delete(PostingBatchRow).where(PostingBatchRow.batch_id.in_(batch_ids)))
    for model in TENANT_TABLES[:8]:
        session.execute(delete(model).where(model.tenant_id == tenant_id))
    session.execute(delete(PostingBatch).where(PostingBatch.tenant_id == tenant_id))
    for model in TENANT_TABLES[8:]:
        session.execute(delete(model).where(model.tenant_id == tenant_id))
    loan_ids = select(Loan.id).where(Loan.tenant_id == tenant_id)
    session.execute(delete(Schedule).where(Schedule.loan_id.in_(loan_ids)))
    for model in (Loan, ImportBatch, Borrower, Group, Officer, Branch, Policy):
        session.execute(delete(model).where(model.tenant_id == tenant_id))
    session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    session.flush()


def seed_tenant(session: Session, market: str, as_of: date, write_sample: bool = True) -> dict:
    world = generator.generate(market, as_of)
    cfg = world.tenant
    reset_tenant(session, cfg["id"])

    tz = ZoneInfo(cfg["timezone"])
    # Seeded "now" is the morning of the export date, inside contact hours.
    now = datetime(as_of.year, as_of.month, as_of.day, 9, 30, tzinfo=tz)
    tenant = Tenant(
        id=cfg["id"], name=cfg["name"], market=market, timezone=cfg["timezone"],
        reporting_currency=cfg["reporting_currency"], brand=cfg["brand"], fx=cfg["fx"], is_demo=True,
        demo_now=now, current_policy_version=0, data_region_note=DATA_HOSTING_REGION,
    )
    session.add(tenant)
    session.flush()
    policy_mod.save_new_version(session, tenant, policy_mod.default_policy(market), actor="system:seed", at=now,
                                note="Default policy for demo tenant")

    out_dir = SAMPLE_DATA_DIR if write_sample else SAMPLE_DATA_DIR / ".tmp"
    paths = mifos_export.write(world, out_dir)
    files = {kind: (p.name, p.read_bytes()) for kind, p in paths.items()}
    result = pipeline.import_files(session, tenant, files, actor="system:seed", as_of=as_of)

    # Staff details the loans file doesn't carry.
    branches = {b.name: b for b in session.scalars(select(Branch).where(Branch.tenant_id == tenant.id))}
    for bdef in world.branches:
        br = branches[bdef["name"]]
        br.code, br.name_local = bdef["code"], bdef["name_local"]
    officers = {o.name: o for o in session.scalars(select(Officer).where(Officer.tenant_id == tenant.id))}
    for odef in world.officers:
        o = officers.get(odef["name"])
        if o is None:  # officer with no loans in the book
            o = Officer(tenant_id=tenant.id, branch_id=branches[odef["branch"]].id, name=odef["name"], code="")
            session.add(o)
            officers[o.name] = o
        o.code, o.name_local, o.phone = odef["code"], odef["name_local"], odef["phone"]
    session.flush()
    for u in world.users:
        session.add(User(
            tenant_id=tenant.id, name=u["name"], email=u["email"], role=u["role"],
            branch_id=branches[u["branch"]].id if u.get("branch") else None,
            officer_id=officers[u["officer"]].id if u.get("officer") else None,
        ))

    borrowers = {b.external_id: b for b in session.scalars(select(Borrower).where(Borrower.tenant_id == tenant.id))}
    events = []
    for link in world.telegram:
        b = borrowers.get(link["client_external_id"])
        if b is None:
            continue
        linked_at = datetime.combine(link["linked_on"], datetime.min.time(), tz) + timedelta(hours=10)
        session.add(TelegramLink(
            tenant_id=tenant.id, borrower_id=b.id, telegram_user_id=None, method=link["method"],
            phone_verified=True, consent_text_version="v1", status="active", linked_at=linked_at,
            last_inbound_at=(datetime.combine(link["last_inbound_on"], datetime.min.time(), tz)
                             + timedelta(hours=12)) if link["last_inbound_on"] else None,
        ))
        events.append({"tenant_id": tenant.id, "type": EventType.telegram_linked, "at": linked_at,
                       "actor": "borrower", "borrower_id": b.id, "policy_version": 1,
                       "payload": {"method": link["method"], "phone_verified": True,
                                   "consent_text_version": "v1", "sample": True}})
    emit_many(session, events)
    session.flush()
    return {"tenant": tenant.id, "as_of": as_of.isoformat(), "files": {k: str(p) for k, p in paths.items()},
            "import": result}
