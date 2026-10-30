"""Case actions: promises, plans and approvals, visits, calls, flags, pauses."""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.domain import plans as plans_mod
from app.events import EventType, emit
from app.messaging import service as msg
from app.models import Approval, Borrower, Case, Loan, Officer, Plan, Promise, Schedule, Tenant, User, Visit


def _common(tenant: Tenant, case: Case, at: datetime, actor: str) -> dict:
    return dict(tenant_id=tenant.id, at=at, actor=actor, policy_version=tenant.current_policy_version,
                case_id=case.id, loan_id=case.loan_id, borrower_id=case.borrower_id)


def record_promise(session: Session, tenant: Tenant, case: Case, *, amount: int, due: date, source: str,
                   actor: str, notify: bool = True) -> Promise:
    at = clock.now(tenant)
    p = Promise(tenant_id=tenant.id, case_id=case.id, loan_id=case.loan_id, amount=amount, due_date=due,
                source=source, status="open", created_at=at)
    session.add(p)
    session.flush()
    emit(session, type=EventType.ptp_created, payload={"promise_id": p.id, "amount": amount, "due_date": due,
                                                       "source": source}, **_common(tenant, case, at, actor))
    case.state = "promised"
    case.next_action = f"Promise due {due.isoformat()}"
    if notify:
        borrower = session.get(Borrower, case.borrower_id)
        msg.send(session, tenant, borrower=borrower, case=case, key="promise_confirmation", at=at, as_reply=True,
                 extra={"promise_amount": amount, "promise_date": due})
    return p


def accept_plan(session: Session, tenant: Tenant, plan: Plan, *, actor: str, officer_note: str | None = None) -> dict:
    version, policy = policy_mod.current(session, tenant)
    at = clock.now(tenant)
    case = session.get(Case, plan.case_id)
    borrower = session.get(Borrower, case.borrower_id)
    plan.accepted_at = at
    for other in session.scalars(select(Plan).where(Plan.generation_id == plan.generation_id, Plan.id != plan.id)):
        other.status = "superseded"
    emit(session, type=EventType.plan_accepted, payload={
        "plan_id": plan.id, "type": plan.option_type, "within_policy": plan.within_policy,
        "breaches": plan.breaches, "new_instalment": plan.details["new_instalment"]},
        **_common(tenant, case, at, actor))
    if plan.within_policy:
        activate_plan(session, tenant, plan, actor="system", at=at)
        return {"status": "approved", "plan_id": plan.id}
    plan.status = "pending_approval"
    role = plans_mod.approver_role(policy, plan)
    appr = Approval(tenant_id=tenant.id, case_id=case.id, branch_id=case.branch_id, plan_id=plan.id, kind="plan",
                    status="pending", breaches=plan.breaches, officer_note=officer_note, requested_at=at,
                    sla_due_at=at + timedelta(hours=policy.slas.approval_hours))
    session.add(appr)
    session.flush()
    emit(session, type=EventType.approval_requested, payload={
        "approval_id": appr.id, "plan_id": plan.id, "approver_role": role, "breaches": plan.breaches,
        "sla_due_at": appr.sla_due_at}, **_common(tenant, case, at, actor))
    case.state = "plan_pending"
    case.next_action = "Plan awaiting approval"
    # Automatic holding message so the borrower is not left waiting in silence.
    msg.send(session, tenant, borrower=borrower, case=case, key="plan_pending_approval", at=at, as_reply=True,
             extra={"sla_hours": policy.slas.approval_hours})
    return {"status": "pending_approval", "plan_id": plan.id, "approval_id": appr.id}


def activate_plan(session: Session, tenant: Tenant, plan: Plan, *, actor: str, at: datetime) -> None:
    case = session.get(Case, plan.case_id)
    loan = session.get(Loan, plan.loan_id)
    borrower = session.get(Borrower, case.borrower_id)
    plan.status = "active"
    # The new schedule is a new version; the lender's original stays as it was.
    current = session.scalar(select(Schedule.version).where(Schedule.loan_id == loan.id)
                             .order_by(Schedule.version.desc()).limit(1)) or 1
    for period in plan.details["periods"]:
        session.add(Schedule(loan_id=loan.id, version=current + 1, instalment_no=period["no"],
                             due_date=date.fromisoformat(period["due_date"]), principal_due=0, interest_due=0,
                             total_due=period["amount"], paid_amount=0))
    case.state = "plan_active"
    case.next_action = "Plan active: monitor instalments"
    from app.services import agreements

    path = agreements.generate(session, tenant, plan)
    emit(session, type=EventType.agreement_generated, payload={"plan_id": plan.id, "file": path,
                                                               "language": borrower.language},
         **_common(tenant, case, at, actor))
    msg.send(session, tenant, borrower=borrower, case=case, key="plan_approved", at=at, as_reply=True,
             extra={"plan_instalment": plan.details["new_instalment"],
                    "plan_end_date": date.fromisoformat(plan.details["new_end_date"])})


def decide_approval(session: Session, tenant: Tenant, appr: Approval, *, decision: str, user: User | None,
                    note: str | None = None, counter_plan_id: int | None = None) -> Approval:
    at = clock.now(tenant)
    case = session.get(Case, appr.case_id)
    actor = f"user:{user.id}" if user else "user:demo"
    appr.status = {"approve": "approved", "reject": "rejected", "counter": "countered"}[decision]
    appr.decided_at, appr.decided_by, appr.decision_note = at, user.id if user else None, note
    appr.counter_plan_id = counter_plan_id
    emit(session, type=EventType.approval_decided, payload={
        "approval_id": appr.id, "plan_id": appr.plan_id, "decision": appr.status, "note": note,
        "approver": user.name if user else None, "approver_role": user.role if user else None,
        "counter_plan_id": counter_plan_id, "within_sla": at <= appr.sla_due_at},
        **_common(tenant, case, at, actor))
    plan = session.get(Plan, appr.plan_id) if appr.plan_id else None
    if decision == "approve" and plan:
        activate_plan(session, tenant, plan, actor=actor, at=at)
    elif decision == "reject" and plan:
        plan.status = "rejected"
        case.state = "contacting"
        case.next_action = "Plan rejected: officer to call"
    elif decision == "counter" and plan:
        plan.status = "rejected"
        counter = session.get(Plan, counter_plan_id) if counter_plan_id else None
        if counter:
            counter.status = "offered"
        case.state = "plan_offered"
        case.next_action = "Counter-offer sent"
        borrower = session.get(Borrower, case.borrower_id)
        msg.send(session, tenant, borrower=borrower, case=case, key="plan_offer", at=at, as_reply=True)
    return appr


def next_working_day(tenant: Tenant, policy, d: date) -> date:
    holidays = {h.date for h in policy.contact.holidays}
    d = d + timedelta(days=1)
    while d.weekday() == 6 or d in holidays:
        d += timedelta(days=1)
    return d


def assign_visit(session: Session, tenant: Tenant, case: Case, *, actor: str, for_date: date | None = None,
                 officer_id: int | None = None, notify: bool = True) -> Visit:
    _, policy = policy_mod.current(session, tenant)
    at = clock.now(tenant)
    existing = session.scalars(select(Visit).where(Visit.case_id == case.id, Visit.status == "assigned")).first()
    if existing:
        return existing
    for_date = for_date or next_working_day(tenant, policy, clock.today(tenant))
    v = Visit(tenant_id=tenant.id, case_id=case.id, borrower_id=case.borrower_id,
              officer_id=officer_id or case.officer_id, assigned_for=for_date, priority=case.priority,
              status="assigned", assigned_at=at)
    session.add(v)
    session.flush()
    emit(session, type=EventType.visit_assigned, payload={"visit_id": v.id, "officer_id": v.officer_id,
                                                          "for": for_date}, **_common(tenant, case, at, actor))
    case.state = "visit"
    case.next_action = f"Visit {for_date.isoformat()}"
    if notify and case.arm == "treatment":
        borrower = session.get(Borrower, case.borrower_id)
        msg.send(session, tenant, borrower=borrower, case=case, key="visit_notice", at=at,
                 extra={"visit_date": for_date})
    return v


def log_call(session: Session, tenant: Tenant, case: Case, *, outcome: str, note: str | None, actor: str):
    at = clock.now(tenant)
    emit(session, type=EventType.call_logged, payload={"outcome": outcome, "note": note},
         **_common(tenant, case, at, actor))
    case.last_contact_at = at


def flag_sensitive(session: Session, tenant: Tenant, case: Case, *, kind: str, note: str | None, actor: str):
    at = clock.now(tenant)
    msg.raise_flag(session, tenant, borrower_id=case.borrower_id, case=case, kind=kind, subtype=None,
                   source="manager", text=note, at=at, actor=actor)
    msg.pause_case(session, tenant, case, kind if kind in ("vulnerability", "dispute", "deceased") else "manual_pause",
                   at, actor)


def set_paused(session: Session, tenant: Tenant, case: Case, *, paused: bool, actor: str, reason: str = "manual_pause"):
    at = clock.now(tenant)
    if paused:
        msg.pause_case(session, tenant, case, reason, at, actor)
    elif case.automation_paused:
        case.automation_paused, case.pause_reason = False, None
        emit(session, type=EventType.automation_resumed, payload={}, **_common(tenant, case, at, actor))


def officer_name(session: Session, officer_id: int | None) -> str | None:
    o = session.get(Officer, officer_id) if officer_id else None
    return o.name if o else None
