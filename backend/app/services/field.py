"""Field visits: outcomes logged by credit officers feed back into the case."""
import base64
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.config import ROOT
from app.events import EventType, emit
from app.messaging import service as msg
from app.models import Case, Tenant, Visit
from app.services import cases as case_svc

OUTCOMES = ("paid", "promised", "not_home", "refused", "hardship", "dispute", "moved_away", "deceased")
PHOTOS = ROOT / "uploads" / "visits"


def record_outcome(session: Session, tenant: Tenant, visit: Visit, *, outcome: str, actor: str,
                   notes: str | None = None, promise_amount: int | None = None, promise_date: date | None = None,
                   photo_b64: str | None = None, photo_taken_at: datetime | None = None,
                   lat: float | None = None, lng: float | None = None) -> Visit:
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome}")
    at = clock.now(tenant)
    case = session.get(Case, visit.case_id)
    visit.status, visit.outcome, visit.notes, visit.completed_at = "completed", outcome, notes, at
    visit.gps_lat, visit.gps_lng = lat, lng
    if photo_b64:
        PHOTOS.mkdir(parents=True, exist_ok=True)
        raw = photo_b64.split(",", 1)[-1]
        path = PHOTOS / f"{tenant.id}-visit-{visit.id}.jpg"
        path.write_bytes(base64.b64decode(raw))
        visit.photo_path = str(path.relative_to(ROOT))
        visit.photo_taken_at = photo_taken_at or at
    if outcome == "promised" and promise_amount and promise_date:
        p = case_svc.record_promise(session, tenant, case, amount=promise_amount, due=promise_date, source="officer",
                                    actor=actor, notify=case.arm == "treatment")
        visit.promise_id = p.id
    emit(session, tenant_id=tenant.id, type=EventType.visit_outcome, at=at, actor=actor,
         policy_version=tenant.current_policy_version, case_id=case.id, loan_id=case.loan_id,
         borrower_id=case.borrower_id,
         payload={"visit_id": visit.id, "outcome": outcome, "notes": notes, "promise_amount": promise_amount,
                  "promise_date": promise_date, "photo": visit.photo_path, "gps": [lat, lng] if lat else None,
                  "officer_id": visit.officer_id})
    flag = {"hardship": "vulnerability", "dispute": "dispute", "deceased": "deceased"}.get(outcome)
    if flag:
        msg.raise_flag(session, tenant, borrower_id=case.borrower_id, case=case, kind=flag,
                       subtype="hardship" if outcome == "hardship" else None, source="officer", text=notes,
                       at=at, actor=actor)
        msg.pause_case(session, tenant, case, flag, at, actor)
    if outcome == "paid":
        case.next_action = "Officer reports payment: confirm in Mifos"
    elif outcome == "not_home":
        _, policy = policy_mod.current(session, tenant)
        nxt = case_svc.next_working_day(tenant, policy, clock.today(tenant) + timedelta(days=1))
        v = Visit(tenant_id=tenant.id, case_id=case.id, borrower_id=case.borrower_id, officer_id=visit.officer_id,
                  assigned_for=nxt, priority=visit.priority, status="assigned", assigned_at=at)
        session.add(v)
        session.flush()
        emit(session, tenant_id=tenant.id, type=EventType.visit_assigned, at=at, actor="system",
             policy_version=tenant.current_policy_version, case_id=case.id, loan_id=case.loan_id,
             borrower_id=case.borrower_id, payload={"visit_id": v.id, "officer_id": v.officer_id, "for": nxt,
                                                   "reason": "not home, retry"})
    elif outcome == "moved_away":
        case.next_action = "Borrower moved: manager to decide"
    elif outcome == "refused":
        case.next_action = "Refused: manager review"
    session.flush()
    return visit
