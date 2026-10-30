"""6.2 Today, 6.3 Borrower account, 6.4 Approvals."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

from app import clock
from app import policy as policy_mod
from app.api.deps import Ctx, ctx
from app.config import ROOT
from app.domain import plans as plans_mod
from app.domain.ranking import score_open_cases
from app.events import EventType
from app.messaging import links
from app.messaging import service as msg
from app.models import (
    Approval,
    Borrower,
    Branch,
    Case,
    Complaint,
    Event,
    Flag,
    Group,
    Loan,
    Message,
    Officer,
    Payment,
    PaymentRequest,
    Plan,
    Promise,
    SavingsSnapshot,
    Schedule,
    TelegramLink,
    User,
    Visit,
)
from app.payments.service import outstanding_arrears
from app.services import cases as case_svc

router = APIRouter(prefix="/api/t/{tenant_id}")


def _scope(c: Ctx, q, case_model=Case):
    if c.branch_id:
        q = q.where(case_model.branch_id == c.branch_id)
    if c.officer_id:
        q = q.where(case_model.officer_id == c.officer_id)
    return q


def _case_or_404(c: Ctx, case_id: int) -> Case:
    case = c.session.get(Case, case_id)
    if case is None or case.tenant_id != c.tenant.id:
        raise HTTPException(404, "case not found")
    if c.branch_id and case.branch_id != c.branch_id or c.officer_id and case.officer_id != c.officer_id:
        raise HTTPException(403, "outside your scope")
    return case


@router.get("/meta")
def meta(c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    version, policy = policy_mod.current(s, t)
    users = s.scalars(select(User).where(User.tenant_id == t.id).order_by(User.role, User.name))
    return {
        "tenant": {"id": t.id, "name": t.name, "market": t.market, "is_demo": t.is_demo, "brand": t.brand,
                   "timezone": t.timezone, "reporting_currency": t.reporting_currency, "fx": t.fx,
                   "now": clock.local_now(t).isoformat(), "today": clock.today(t).isoformat(),
                   "policy_version": version, "data_region": t.data_region_note},
        "user": {"id": c.user.id, "name": c.user.name, "role": c.role, "branch_id": c.user.branch_id,
                 "officer_id": c.user.officer_id} if c.user else None,
        "users": [{"id": u.id, "name": u.name, "role": u.role, "branch_id": u.branch_id, "officer_id": u.officer_id}
                  for u in users],
        "branches": [{"id": b.id, "name": b.name, "name_local": b.name_local} for b in
                     s.scalars(select(Branch).where(Branch.tenant_id == t.id).order_by(Branch.name))],
        "officers": [{"id": o.id, "name": o.name, "branch_id": o.branch_id} for o in
                     s.scalars(select(Officer).where(Officer.tenant_id == t.id).order_by(Officer.name))],
        "buckets": [b.model_dump() for b in policy.buckets],
    }


@router.get("/today")
def today(c: Ctx = Depends(ctx), branch: int | None = None, officer: int | None = None, bucket: str | None = None,
          segment: str | None = None, arm: str | None = None, q: str | None = None, limit: int = 300):
    s, t = c.session, c.tenant
    now = clock.now(t)
    day = clock.today(t)
    query = (select(Case, Loan, Borrower).join(Loan, Loan.id == Case.loan_id)
             .join(Borrower, Borrower.id == Case.borrower_id)
             .where(Case.tenant_id == t.id, Case.status == "open"))
    query = _scope(c, query)
    for col, val in ((Case.branch_id, branch), (Case.officer_id, officer), (Case.bucket, bucket),
                     (Case.segment, segment), (Case.arm, arm)):
        if val is not None:
            query = query.where(col == val)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Borrower.name.ilike(like), Borrower.name_local.ilike(like),
                                Loan.external_id.ilike(like)))
    rows = s.execute(query.order_by(Case.priority.desc().nulls_last()).limit(limit)).all()
    branches = {b.id: b.name for b in s.scalars(select(Branch).where(Branch.tenant_id == t.id))}
    officers = {o.id: o.name for o in s.scalars(select(Officer).where(Officer.tenant_id == t.id))}
    linked = set(s.scalars(select(TelegramLink.borrower_id).where(TelegramLink.tenant_id == t.id,
                                                                   TelegramLink.status == "active")))
    items = [{
        "case_id": case.id, "borrower_id": b.id, "borrower": b.name, "borrower_local": b.name_local,
        "branch": branches.get(case.branch_id), "officer": officers.get(case.officer_id), "bucket": case.bucket,
        "days_overdue": loan.days_overdue, "amount_overdue": loan.amount_overdue, "currency": loan.currency,
        "loan_type": loan.loan_type, "priority": case.priority, "pay_likelihood": case.pay_likelihood,
        "stake": case.stake, "segment": case.segment, "state": case.state, "next_action": case.next_action,
        "reasons": [r for r in (case.reason_codes or []) if r["code"] != "days_overdue"],
        "telegram": b.id in linked, "arm": case.arm, "paused": case.automation_paused,
    } for case, loan, b in rows]

    # Counters for the whole scope, not just the filtered page.
    local_day_start = clock.local_datetime(t, day, 0)
    day_end = local_day_start + timedelta(days=1)
    scoped_cases = _scope(c, select(Case.id).where(Case.tenant_id == t.id))
    m_scope = Message.case_id.in_(scoped_cases) if (c.branch_id or c.officer_id) else Message.tenant_id == t.id
    count = lambda q_: s.scalar(q_) or 0  # noqa: E731
    open_scope = _scope(c, select(func.count(Case.id)).where(Case.tenant_id == t.id, Case.status == "open"))
    open_linked = _scope(c, select(func.count(Case.id)).where(
        Case.tenant_id == t.id, Case.status == "open", Case.borrower_id.in_(linked) if linked else False))
    counters = {
        "open_cases": count(open_scope),
        "messages_scheduled_today": count(select(func.count(Message.id)).where(
            m_scope, Message.direction == "out", Message.planned_at >= local_day_start, Message.planned_at < day_end,
            Message.status.in_(("planned", "sent", "delivered", "read")))),
        "messages_blocked_today": count(select(func.count(Message.id)).where(
            m_scope, Message.status == "blocked", Message.planned_at >= local_day_start, Message.planned_at < day_end)),
        "plans_awaiting_approval": count(_scope(c, select(func.count(Approval.id)).where(
            Approval.tenant_id == t.id, Approval.status == "pending"), Approval)),
        "visits_assigned": count(select(func.count(Visit.id)).where(
            Visit.tenant_id == t.id, Visit.status == "assigned", Visit.assigned_for <= day,
            *( [Visit.officer_id == c.officer_id] if c.officer_id else []),
            *( [Visit.case_id.in_(scoped_cases)] if c.branch_id else []))),
        "promises_due_today": count(select(func.count(Promise.id)).where(
            Promise.tenant_id == t.id, Promise.status == "open", Promise.due_date == day,
            *( [Promise.case_id.in_(scoped_cases)] if (c.branch_id or c.officer_id) else []))),
        "telegram_link_rate": round(count(open_linked) / max(1, count(open_scope)), 4),
    }
    return {"as_of": now.isoformat(), "counters": counters, "items": items, "sample": t.is_demo}


class BulkBody(BaseModel):
    case_ids: list[int]
    action: str  # send_reminder | assign_visit | mark_sensitive


@router.post("/cases/bulk")
def bulk(body: BulkBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections", "branch_manager")
    out = {"done": 0, "skipped_control": 0, "blocked": 0, "results": []}
    for cid in body.case_ids:
        case = _case_or_404(c, cid)
        if case.arm == "control":
            out["skipped_control"] += 1
            continue
        if body.action == "send_reminder":
            key = _reminder_for(c, case)
            m = msg.send(c.session, c.tenant, borrower=c.session.get(Borrower, case.borrower_id), case=case, key=key,
                         actor=c.actor)
            if m is None:
                out["results"].append({"case_id": cid, "status": "no_channel"})
                continue
            out["results"].append({"case_id": cid, "status": m.status, "rule": m.gate_rule_id})
            out["blocked" if m.status == "blocked" else "done"] += 1
        elif body.action == "assign_visit":
            case_svc.assign_visit(c.session, c.tenant, case, actor=c.actor)
            out["done"] += 1
        elif body.action == "mark_sensitive":
            case_svc.flag_sensitive(c.session, c.tenant, case, kind="lender_tag", note="Marked sensitive (bulk)",
                                    actor=c.actor)
            out["done"] += 1
    score_open_cases(c.session, c.tenant, c.actor, case_ids=body.case_ids)
    return out


def _reminder_for(c: Ctx, case: Case) -> str:
    _, policy = policy_mod.current(c.session, c.tenant)
    link = c.session.scalars(select(TelegramLink).where(TelegramLink.borrower_id == case.borrower_id,
                                                        TelegramLink.status == "active")).first()
    if link is None:
        return "telegram_invite"
    s = next((x for x in policy.strategy if x.bucket == case.bucket), None)
    if s is None:
        return "late_3_days"
    sent = c.session.scalar(select(func.count(Message.id)).where(
        Message.case_id == case.id, Message.template_key.in_(s.templates),
        Message.status.in_(("sent", "delivered", "read")))) or 0
    key = s.templates[min(sent, len(s.templates) - 1)]
    return "late_7_days" if key == "visit_notice" else key


# ---------------------------------------------------------------------------
# Borrower account


def _event_dict(e: Event) -> dict:
    return {"id": e.id, "type": e.type, "at": e.created_at.isoformat(), "actor": e.actor,
            "policy_version": e.policy_version, "payload": e.payload, "case_id": e.case_id}


def _message_dict(m: Message) -> dict:
    return {"id": m.id, "direction": m.direction, "channel": m.channel, "template": m.template_key,
            "template_version": m.template_version, "language": m.language, "body": m.body,
            "shadow": m.body_shadow, "status": m.status, "gate": m.gate_decision, "rule": m.gate_rule_id,
            "trace": m.gate_trace, "policy_version": m.policy_version,
            "planned_at": m.planned_at.isoformat() if m.planned_at else None,
            "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            "read_at": m.read_at.isoformat() if m.read_at else None,
            "next_allowed_at": m.next_allowed_at.isoformat() if m.next_allowed_at else None,
            "classification": m.classification, "classification_detail": m.classification_detail,
            "token": (m.variables or {}).get("token")}


@router.get("/cases/{case_id}")
def account(case_id: int, c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    case = _case_or_404(c, case_id)
    loan = s.get(Loan, case.loan_id)
    b = s.get(Borrower, case.borrower_id)
    officer = s.get(Officer, case.officer_id) if case.officer_id else None
    branch = s.get(Branch, case.branch_id)
    schedules = list(s.scalars(select(Schedule).where(Schedule.loan_id == loan.id)
                               .order_by(Schedule.version, Schedule.instalment_no)))
    snaps = list(s.scalars(select(SavingsSnapshot).where(SavingsSnapshot.borrower_id == b.id)
                           .order_by(SavingsSnapshot.week_start)))
    group = None
    if loan.group_id:
        g = s.get(Group, loan.group_id)
        members = s.execute(select(Loan, Borrower).join(Borrower, Borrower.id == Loan.borrower_id)
                            .where(Loan.group_id == g.id).order_by(Borrower.name)).all()
        group = {"name": g.name, "village": g.village, "members": [
            {"borrower_id": mb.id, "name": mb.name, "days_overdue": ml.days_overdue,
             "amount_overdue": ml.amount_overdue, "is_self": mb.id == b.id} for ml, mb in members]}
    link = s.scalars(select(TelegramLink).where(TelegramLink.borrower_id == b.id)
                     .order_by(TelegramLink.id.desc())).first()
    events = list(s.scalars(select(Event).where(Event.tenant_id == t.id, or_(
        Event.case_id == case.id, and_(Event.borrower_id == b.id, Event.case_id.is_(None))))
                            .order_by(Event.created_at.desc(), Event.id.desc()).limit(400)))
    messages = list(s.scalars(select(Message).where(Message.borrower_id == b.id)
                              .order_by(Message.planned_at, Message.id)))
    plans = list(s.scalars(select(Plan).where(Plan.case_id == case.id).order_by(Plan.id.desc())))
    token = links.make_token(t.id, b.id, case.id, clock.now(t).timestamp())
    score_event = s.get(Event, case.last_score_event_id) if case.last_score_event_id else None
    return {
        "sample": t.is_demo,
        "case": {"id": case.id, "status": case.status, "state": case.state, "segment": case.segment,
                 "bucket": case.bucket, "arm": case.arm, "stratum": case.stratum, "priority": case.priority,
                 "pay_likelihood": case.pay_likelihood, "stake": case.stake, "reasons": case.reason_codes,
                 "paused": case.automation_paused, "pause_reason": case.pause_reason,
                 "next_action": case.next_action, "opened_at": case.opened_at.isoformat(),
                 "attempts": case.contact_attempts, "collected": case.collected_amount,
                 "amount_overdue_at_open": case.amount_overdue_at_open,
                 "policy_version_at_open": case.policy_version_at_open,
                 "score_inputs": score_event.payload.get("inputs") if score_event else None,
                 "segment_rule": score_event.payload.get("segment_rule") if score_event else None},
        "borrower": {"id": b.id, "name": b.name, "name_local": b.name_local, "phone": b.phone, "village": b.village,
                     "gender": b.gender, "language": b.language, "national_id": b.national_id,
                     "external_id": b.external_id, "anonymised": b.anonymised},
        "loan": {"id": loan.id, "external_id": loan.external_id, "product": loan.product, "type": loan.loan_type,
                 "currency": loan.currency, "principal_disbursed": loan.principal_disbursed,
                 "disbursed_on": loan.disbursed_on.isoformat(), "rate": loan.interest_rate_annual,
                 "term": loan.term_instalments, "frequency": loan.frequency, "instalment": loan.instalment_amount,
                 "cycle": loan.loan_cycle, "principal_outstanding": loan.principal_outstanding,
                 "principal_overdue": loan.principal_overdue, "interest_overdue": loan.interest_overdue,
                 "penalty_overdue": loan.penalty_overdue, "amount_overdue": loan.amount_overdue,
                 "arrears_now": outstanding_arrears(s, loan), "days_overdue": loan.days_overdue,
                 "arrears_as_of": loan.arrears_as_of and loan.arrears_as_of.isoformat(),
                 "next_due_date": loan.next_due_date and loan.next_due_date.isoformat(),
                 "last_repayment_date": loan.last_repayment_date and loan.last_repayment_date.isoformat(),
                 "savings_balance": loan.savings_balance, "appraisal": loan.appraisal,
                 "restructure_count": loan.restructure_count},
        "officer": {"id": officer.id, "name": officer.name, "phone": officer.phone} if officer else None,
        "branch": branch.name,
        "group": group,
        "schedule": [{"version": x.version, "no": x.instalment_no, "due_date": x.due_date.isoformat(),
                      "total_due": x.total_due, "paid": x.paid_amount,
                      "paid_on": x.paid_on and x.paid_on.isoformat()} for x in schedules],
        "savings": [{"week": x.week_start.isoformat(), "balance": x.balance, "deposits": x.deposits,
                     "withdrawals": x.withdrawals} for x in snaps],
        "telegram": {"status": link.status, "method": link.method, "linked_at": link.linked_at.isoformat(),
                     "last_inbound_at": link.last_inbound_at and link.last_inbound_at.isoformat()} if link else None,
        "timeline": [_event_dict(e) for e in events],
        "messages": [_message_dict(m) for m in messages],
        "promises": [{"id": p.id, "amount": p.amount, "due_date": p.due_date.isoformat(), "status": p.status,
                      "source": p.source} for p in s.scalars(select(Promise).where(Promise.case_id == case.id))],
        "plans": [{"id": p.id, "type": p.option_type, "status": p.status, "within_policy": p.within_policy,
                   "breaches": p.breaches, "details": p.details, "capacity": p.capacity,
                   "policy_version": p.policy_version, "created_at": p.created_at.isoformat()} for p in plans],
        "visits": [{"id": v.id, "for": v.assigned_for.isoformat(), "status": v.status, "outcome": v.outcome,
                    "notes": v.notes, "photo": v.photo_path} for v in
                   s.scalars(select(Visit).where(Visit.case_id == case.id).order_by(Visit.id.desc()))],
        "flags": [{"id": f.id, "kind": f.kind, "subtype": f.subtype, "text": f.text, "active": f.active,
                   "source": f.source, "raised_at": f.raised_at.isoformat()} for f in
                  s.scalars(select(Flag).where(Flag.borrower_id == b.id).order_by(Flag.id.desc()))],
        "payments": [{"id": p.id, "amount": p.amount, "paid_at": p.paid_at.isoformat(), "status": p.match_status,
                      "kind": p.kind, "reference": p.reference} for p in
                     s.scalars(select(Payment).where(Payment.loan_id == loan.id).order_by(Payment.id.desc()))],
        "mini_app_token": token,
        "mini_app_url": f"/m/{token}",
        "brand": t.brand,
    }


class ActionBody(BaseModel):
    template: str | None = None
    amount: int | None = None
    due_date: date | None = None
    outcome: str | None = None
    note: str | None = None
    kind: str | None = None
    paused: bool | None = None
    answers: dict | None = None
    plan_id: int | None = None


@router.post("/cases/{case_id}/actions/{action}")
def case_action(case_id: int, action: str, body: ActionBody, c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    case = _case_or_404(c, case_id)
    borrower = s.get(Borrower, case.borrower_id)
    if c.role == "leadership":
        raise HTTPException(403, "leadership is read-only")
    if action == "send_template":
        m = msg.send(s, t, borrower=borrower, case=case, key=body.template or _reminder_for(c, case), actor=c.actor)
        if m is None:
            raise HTTPException(400, "Borrower has no Telegram link; send the SMS invite or assign a visit")
        result = _message_dict(m)
    elif action == "log_call":
        case_svc.log_call(s, t, case, outcome=body.outcome or "spoke", note=body.note, actor=c.actor)
        result = {"ok": True}
    elif action == "record_promise":
        if not body.amount or not body.due_date:
            raise HTTPException(400, "amount and due_date required")
        p = case_svc.record_promise(s, t, case, amount=body.amount, due=body.due_date, source="call", actor=c.actor)
        result = {"promise_id": p.id}
    elif action == "generate_plans":
        plans = plans_mod.generate_for_case(s, t, case, answers=body.answers, actor=c.actor)
        result = {"plans": [p.id for p in plans]}
    elif action == "accept_plan":
        plan = s.get(Plan, body.plan_id)
        if plan is None or plan.case_id != case.id:
            raise HTTPException(404, "plan not found")
        result = case_svc.accept_plan(s, t, plan, actor=c.actor, officer_note=body.note)
    elif action == "assign_visit":
        v = case_svc.assign_visit(s, t, case, actor=c.actor, for_date=body.due_date)
        result = {"visit_id": v.id}
    elif action == "flag_sensitive":
        case_svc.flag_sensitive(s, t, case, kind=body.kind or "lender_tag", note=body.note, actor=c.actor)
        result = {"ok": True}
    elif action == "pause":
        case_svc.set_paused(s, t, case, paused=bool(body.paused), actor=c.actor)
        result = {"ok": True}
    else:
        raise HTTPException(400, f"unknown action {action}")
    score_open_cases(s, t, c.actor, case_ids=[case.id])
    return result


@router.get("/files/{path:path}")
def file(path: str, c: Ctx = Depends(ctx)):
    p = (ROOT / path).resolve()
    if not str(p).startswith(str((ROOT / "uploads").resolve())) or not p.is_file() or c.tenant.id not in p.name:
        raise HTTPException(404)
    return FileResponse(p)


# ---------------------------------------------------------------------------
# Approvals


@router.get("/approvals")
def approvals(c: Ctx = Depends(ctx), status: str = "pending"):
    s, t = c.session, c.tenant
    now = clock.now(t)
    q = select(Approval).where(Approval.tenant_id == t.id)
    if status != "all":
        q = q.where(Approval.status == status)
    if c.branch_id:
        q = q.where(Approval.branch_id == c.branch_id)
    out = []
    for a in s.scalars(q.order_by(Approval.sla_due_at)):
        case = s.get(Case, a.case_id)
        loan = s.get(Loan, case.loan_id)
        b = s.get(Borrower, case.borrower_id)
        plan = s.get(Plan, a.plan_id) if a.plan_id else None
        alternatives = []
        if plan:
            alternatives = [{"id": p.id, "type": p.option_type, "within_policy": p.within_policy,
                             "new_instalment": p.details["new_instalment"], "extension": p.details["extension"],
                             "affordable": p.details["affordable"]} for p in s.scalars(select(Plan).where(
                Plan.generation_id == plan.generation_id, Plan.id != plan.id))]
        decider = s.get(User, a.decided_by) if a.decided_by else None
        out.append({
            "id": a.id, "kind": a.kind, "status": a.status, "case_id": case.id, "borrower": b.name,
            "borrower_local": b.name_local, "branch": s.get(Branch, case.branch_id).name,
            "officer": case_svc.officer_name(s, case.officer_id), "loan": loan.external_id, "currency": loan.currency,
            "days_overdue": loan.days_overdue, "amount_overdue": loan.amount_overdue,
            "original": {"instalment": loan.instalment_amount,
                         "remaining_total": plan.details["original_total"] if plan else None,
                         "end_date": (lambda d: d and d.isoformat())(s.scalar(select(func.max(Schedule.due_date))
                                                                             .where(Schedule.loan_id == loan.id,
                                                                                    Schedule.version == 1)))},
            "plan": {"id": plan.id, "type": plan.option_type, "details": plan.details, "capacity": plan.capacity}
            if plan else None,
            "breaches": a.breaches, "officer_note": a.officer_note, "requested_at": a.requested_at.isoformat(),
            "sla_due_at": a.sla_due_at.isoformat(), "sla_seconds_left": int((a.sla_due_at - now).total_seconds()),
            "alternatives": alternatives, "decided_by": decider.name if decider else None,
            "decided_at": a.decided_at and a.decided_at.isoformat(), "decision_note": a.decision_note,
        })
    return {"items": out, "sample": t.is_demo}


class DecideBody(BaseModel):
    decision: str  # approve | reject | counter
    note: str | None = None
    counter_plan_id: int | None = None


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: int, body: DecideBody, c: Ctx = Depends(ctx)):
    c.require("branch_manager", "head_of_collections")
    a = c.session.get(Approval, approval_id)
    if a is None or a.tenant_id != c.tenant.id:
        raise HTTPException(404)
    if a.status != "pending":
        raise HTTPException(409, f"already {a.status}")
    if c.branch_id and a.branch_id != c.branch_id:
        raise HTTPException(403, "another branch")
    case_svc.decide_approval(c.session, c.tenant, a, decision=body.decision, user=c.user, note=body.note,
                             counter_plan_id=body.counter_plan_id)
    return {"ok": True, "status": a.status}
