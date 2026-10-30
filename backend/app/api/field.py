"""6.5 Field: manager view and the officer's visit list."""
from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app import clock
from app.api.deps import Ctx, ctx
from app.config import ROOT
from app.events import EventType, emit
from app.models import Borrower, Branch, Case, Loan, Officer, TelegramLink, Visit
from app.services import field as field_svc

router = APIRouter(prefix="/api/t/{tenant_id}/field")


@router.get("/manager")
def manager(c: Ctx = Depends(ctx), day: date | None = None):
    s, t = c.session, c.tenant
    day = day or clock.today(t)
    officers = list(s.scalars(select(Officer).where(Officer.tenant_id == t.id).order_by(Officer.name)))
    if c.branch_id:
        officers = [o for o in officers if o.branch_id == c.branch_id]
    branches = {b.id: b.name for b in s.scalars(select(Branch).where(Branch.tenant_id == t.id))}
    out = []
    for o in officers:
        today = list(s.scalars(select(Visit).where(Visit.officer_id == o.id, Visit.assigned_for == day)))
        overdue = s.scalar(select(func.count(Visit.id)).where(Visit.officer_id == o.id, Visit.status == "assigned",
                                                             Visit.assigned_for < day)) or 0
        last30 = list(s.scalars(select(Visit).where(Visit.officer_id == o.id, Visit.assigned_for < day,
                                                    Visit.assigned_for >= date.fromordinal(day.toordinal() - 30))))
        done30 = [v for v in last30 if v.status == "completed"]
        open_cases = s.scalar(select(func.count(Case.id)).where(Case.officer_id == o.id, Case.status == "open")) or 0
        outcomes = defaultdict(int)
        for v in today:
            if v.outcome:
                outcomes[v.outcome] += 1
        out.append({"officer_id": o.id, "officer": o.name, "branch": branches.get(o.branch_id),
                    "today_assigned": len(today), "today_done": sum(1 for v in today if v.status == "completed"),
                    "carried_over": overdue, "open_cases": open_cases,
                    "completion_30d": round(len(done30) / len(last30), 3) if last30 else None,
                    "visits_30d": len(done30), "outcomes_today": dict(outcomes)})
    totals = defaultdict(int)
    for row in out:
        for k, v in row["outcomes_today"].items():
            totals[k] += v
    return {"day": day.isoformat(), "officers": out, "outcomes_today": dict(totals), "sample": t.is_demo}


@router.get("/my")
def my_visits(c: Ctx = Depends(ctx), day: date | None = None, officer_id: int | None = None):
    s, t = c.session, c.tenant
    day = day or clock.today(t)
    oid = c.officer_id or officer_id
    if oid is None:
        raise HTTPException(400, "choose an officer")
    officer = s.get(Officer, oid)
    visits = list(s.scalars(select(Visit).where(Visit.officer_id == oid, Visit.assigned_for <= day,
                                                Visit.tenant_id == t.id)
                            .where((Visit.status == "assigned") | (Visit.assigned_for == day))
                            .order_by(Visit.priority.desc().nulls_last())))
    linked = set(s.scalars(select(TelegramLink.borrower_id).where(TelegramLink.tenant_id == t.id,
                                                                   TelegramLink.status == "active")))
    groups = defaultdict(list)
    for v in visits:
        case = s.get(Case, v.case_id)
        loan = s.get(Loan, case.loan_id)
        b = s.get(Borrower, v.borrower_id)
        groups[b.village or "Other"].append({
            "visit_id": v.id, "case_id": case.id, "status": v.status, "outcome": v.outcome,
            "carried_over": v.assigned_for < day, "borrower": b.name, "borrower_local": b.name_local,
            "phone": b.phone, "village": b.village, "loan": loan.external_id, "loan_type": loan.loan_type,
            "days_overdue": loan.days_overdue, "amount_overdue": loan.amount_overdue, "currency": loan.currency,
            "instalment": loan.instalment_amount, "priority": v.priority, "segment": case.segment,
            "reasons": [r["text"] for r in (case.reason_codes or []) if r["code"] != "days_overdue"][:3],
            "telegram": b.id in linked, "arm": case.arm,
        })
    villages = sorted(groups.items(), key=lambda kv: -max((x["priority"] or 0) for x in kv[1]))
    return {"day": day.isoformat(), "officer": {"id": officer.id, "name": officer.name,
                                                "name_local": officer.name_local},
            "villages": [{"village": k, "visits": v} for k, v in villages],
            "total": len(visits), "done": sum(1 for v in visits if v.status == "completed"), "sample": t.is_demo}


class OutcomeBody(BaseModel):
    outcome: str
    notes: str | None = None
    promise_amount: int | None = None
    promise_date: date | None = None
    photo: str | None = None  # data URL or base64 JPEG
    photo_taken_at: datetime | None = None
    lat: float | None = None
    lng: float | None = None


@router.post("/visits/{visit_id}/outcome")
def outcome(visit_id: int, body: OutcomeBody, c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    v = s.get(Visit, visit_id)
    if v is None or v.tenant_id != t.id:
        raise HTTPException(404)
    if c.officer_id and v.officer_id != c.officer_id:
        raise HTTPException(403, "not your visit")
    if v.status == "completed":
        raise HTTPException(409, "outcome already logged")
    try:
        field_svc.record_outcome(s, t, v, outcome=body.outcome, actor=c.actor, notes=body.notes,
                                 promise_amount=body.promise_amount, promise_date=body.promise_date,
                                 photo_b64=body.photo, photo_taken_at=body.photo_taken_at, lat=body.lat, lng=body.lng)
    except ValueError as e:
        raise HTTPException(400, str(e))
    from app.domain.ranking import score_open_cases

    score_open_cases(s, t, c.actor, case_ids=[v.case_id])
    return {"ok": True}


class ReassignBody(BaseModel):
    officer_id: int


@router.post("/visits/{visit_id}/reassign")
def reassign(visit_id: int, body: ReassignBody, c: Ctx = Depends(ctx)):
    c.require("branch_manager", "head_of_collections")
    v = c.session.get(Visit, visit_id)
    if v is None or v.tenant_id != c.tenant.id or v.status != "assigned":
        raise HTTPException(404)
    old = v.officer_id
    v.officer_id = body.officer_id
    case = c.session.get(Case, v.case_id)
    emit(c.session, tenant_id=c.tenant.id, type=EventType.visit_assigned, at=clock.now(c.tenant), actor=c.actor,
         policy_version=c.tenant.current_policy_version, case_id=case.id, loan_id=case.loan_id,
         borrower_id=case.borrower_id, payload={"visit_id": v.id, "officer_id": body.officer_id, "from": old,
                                               "for": v.assigned_for, "reason": "reassigned"})
    return {"ok": True}


@router.get("/photo/{visit_id}")
def photo(visit_id: int, c: Ctx = Depends(ctx)):
    v = c.session.get(Visit, visit_id)
    if v is None or v.tenant_id != c.tenant.id or not v.photo_path:
        raise HTTPException(404)
    return FileResponse(ROOT / v.photo_path)
