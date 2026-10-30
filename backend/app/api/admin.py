"""6.7 Results, 6.8 Compliance, 6.9 Settings."""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from app import clock
from app import policy as policy_mod
from app.api.deps import Ctx, ctx
from app.config import DATA_HOSTING_REGION, TELEGRAM_BOT_TOKEN
from app.domain.ranking import RANKER, _pct_rank, extract_features, score_open_cases, segment_for
from app.events import EventType, emit
from app.messaging.gate import RULES, banned_in
from app.messaging.templates_seed import category
from app.models import (
    Borrower,
    Case,
    ColumnMapping,
    Complaint,
    Flag,
    Message,
    Policy,
    TelegramLink,
    Template,
    User,
)
from app.policy import PolicyData
from app.services import results as results_svc

router = APIRouter(prefix="/api/t/{tenant_id}")


# ---------------------------------------------------------------------------
# Results


@router.get("/results")
def results(c: Ctx = Depends(ctx)):
    c.require("head_of_collections", "leadership")
    return results_svc.compute(c.session, c.tenant)


@router.get("/results/trace")
def results_trace(arm: str, metric: str = "cure_rate", bucket: str | None = None, c: Ctx = Depends(ctx)):
    return results_svc.trace(c.session, c.tenant, arm, bucket, metric)


# ---------------------------------------------------------------------------
# Compliance


def _message_rows(c: Ctx, status, rule, template, limit):
    s = c.session
    q = select(Message, Borrower).join(Borrower, Borrower.id == Message.borrower_id).where(
        Message.tenant_id == c.tenant.id, Message.direction == "out")
    if status:
        q = q.where(Message.status == status)
    if rule:
        q = q.where(Message.gate_rule_id == rule)
    if template:
        q = q.where(Message.template_key == template)
    if c.branch_id:
        q = q.where(Borrower.branch_id == c.branch_id)
    return s.execute(q.order_by(Message.planned_at.desc(), Message.id.desc()).limit(limit)).all()


@router.get("/compliance/messages")
def message_log(c: Ctx = Depends(ctx), status: str | None = None, rule: str | None = None,
                template: str | None = None, limit: int = 300):
    return [{"id": m.id, "borrower": b.name, "case_id": m.case_id, "template": m.template_key,
             "template_version": m.template_version, "language": m.language, "channel": m.channel,
             "status": m.status, "decision": m.gate_decision, "rule": m.gate_rule_id,
             "rule_name": RULES.get(m.gate_rule_id or ""), "policy_version": m.policy_version,
             "planned_at": m.planned_at.isoformat(), "sent_at": m.sent_at and m.sent_at.isoformat(),
             "delivered_at": m.delivered_at and m.delivered_at.isoformat(),
             "read_at": m.read_at and m.read_at.isoformat(),
             "next_allowed_at": m.next_allowed_at and m.next_allowed_at.isoformat(),
             "body": m.body, "shadow": m.body_shadow, "trace": m.gate_trace}
            for m, b in _message_rows(c, status, rule, template, min(limit, 2000))]


@router.get("/compliance/messages.csv")
def message_log_csv(c: Ctx = Depends(ctx), status: str | None = None, rule: str | None = None):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["message_id", "borrower", "case_id", "template", "template_version", "language", "channel", "status",
                "decision", "rule_id", "policy_version", "planned_at", "sent_at", "delivered_at", "read_at",
                "next_allowed_at", "body", "english"])
    for m, b in _message_rows(c, status, rule, None, 100_000):
        w.writerow([m.id, b.name, m.case_id, m.template_key, m.template_version, m.language, m.channel, m.status,
                    m.gate_decision, m.gate_rule_id, m.policy_version, m.planned_at.isoformat(),
                    m.sent_at and m.sent_at.isoformat(), m.delivered_at and m.delivered_at.isoformat(),
                    m.read_at and m.read_at.isoformat(), m.next_allowed_at and m.next_allowed_at.isoformat(),
                    m.body, m.body_shadow])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="message-log-{c.tenant.id}.csv"'})


@router.get("/compliance")
def compliance(c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    now = clock.now(t)
    blocked = s.execute(select(Message.gate_rule_id, func.count()).where(
        Message.tenant_id == t.id, Message.status == "blocked").group_by(Message.gate_rule_id)).all()
    sent = s.scalar(select(func.count(Message.id)).where(Message.tenant_id == t.id,
                                                        Message.status.in_(("sent", "delivered", "read"))))
    links = s.execute(select(TelegramLink, Borrower).join(Borrower, Borrower.id == TelegramLink.borrower_id)
                      .where(TelegramLink.tenant_id == t.id).order_by(TelegramLink.linked_at.desc())).all()
    by_method = {}
    for l, _ in links:
        by_method[l.method] = by_method.get(l.method, 0) + 1
    flags = s.execute(select(Flag, Borrower).join(Borrower, Borrower.id == Flag.borrower_id).where(
        Flag.tenant_id == t.id, Flag.kind.in_(("vulnerability", "dispute", "deceased")))
        .order_by(Flag.raised_at.desc())).all()
    reviewers = {u.id: u.name for u in s.scalars(select(User).where(User.tenant_id == t.id))}
    complaints = s.execute(select(Complaint, Borrower).join(Borrower, Borrower.id == Complaint.borrower_id)
                           .where(Complaint.tenant_id == t.id).order_by(Complaint.opened_at.desc())).all()
    from app.api.mini import CHARTER

    return {
        "sample": t.is_demo,
        "messages_sent": sent,
        "blocked_by_rule": sorted([{"rule": r, "name": RULES.get(r, r), "count": n} for r, n in blocked],
                                  key=lambda x: -x["count"]),
        "consent": {
            "linked": sum(1 for l, _ in links if l.status == "active"),
            "opted_out": sum(1 for l, _ in links if l.status == "opted_out"), "by_method": by_method,
            "recent": [{"borrower": b.name, "method": l.method, "linked_at": l.linked_at.isoformat(),
                        "status": l.status, "consent_version": l.consent_text_version,
                        "opted_out_at": l.opted_out_at and l.opted_out_at.isoformat(), "phone_verified": l.phone_verified}
                       for l, b in links[:100]],
            "opt_outs": [{"borrower": b.name, "opted_out_at": l.opted_out_at.isoformat()}
                         for l, b in links if l.status == "opted_out"],
        },
        "flags": [{"id": f.id, "borrower": b.name, "borrower_id": b.id, "case_id": f.case_id, "kind": f.kind,
                   "subtype": f.subtype, "source": f.source, "text": f.text, "active": f.active,
                   "raised_at": f.raised_at.isoformat(), "reviewer": reviewers.get(f.reviewer_user_id),
                   "reviewed_at": f.reviewed_at and f.reviewed_at.isoformat(), "outcome": f.outcome}
                  for f, b in flags[:200]],
        "complaints": [{"id": x.id, "ref": f"C-{x.id:05d}", "borrower": b.name, "case_id": x.case_id,
                        "source": x.source, "text": x.text, "status": x.status, "opened_at": x.opened_at.isoformat(),
                        "sla_due_at": x.sla_due_at.isoformat(), "overdue": x.status != "closed" and x.sla_due_at < now,
                        "resolution": x.resolution, "closed_at": x.closed_at and x.closed_at.isoformat()}
                       for x, b in complaints],
        "charter": t.brand.get("charter") or {k: [{"title": a, "body": bb} for a, bb in v] for k, v in CHARTER.items()},
    }


class ReviewBody(BaseModel):
    outcome: str
    resume: bool = False


@router.post("/compliance/flags/{flag_id}/review")
def review_flag(flag_id: int, body: ReviewBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections", "branch_manager")
    f = c.session.get(Flag, flag_id)
    if f is None or f.tenant_id != c.tenant.id:
        raise HTTPException(404)
    now = clock.now(c.tenant)
    f.reviewer_user_id, f.reviewed_at, f.outcome = c.user.id if c.user else None, now, body.outcome
    case = c.session.get(Case, f.case_id) if f.case_id else None
    if body.resume:
        f.active = False
        if case and case.automation_paused:
            case.automation_paused, case.pause_reason = False, None
            emit(c.session, tenant_id=c.tenant.id, type=EventType.automation_resumed, at=now, actor=c.actor,
                 policy_version=c.tenant.current_policy_version, case_id=case.id, borrower_id=f.borrower_id,
                 payload={"after_flag": f.id})
    emit(c.session, tenant_id=c.tenant.id, type=EventType.flag_reviewed, at=now, actor=c.actor,
         policy_version=c.tenant.current_policy_version, case_id=f.case_id, borrower_id=f.borrower_id,
         payload={"flag_id": f.id, "outcome": body.outcome, "resume": body.resume})
    if case:
        score_open_cases(c.session, c.tenant, c.actor, case_ids=[case.id])
    return {"ok": True}


class CloseBody(BaseModel):
    resolution: str


@router.post("/compliance/complaints/{complaint_id}/close")
def close_complaint(complaint_id: int, body: CloseBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections", "branch_manager")
    x = c.session.get(Complaint, complaint_id)
    if x is None or x.tenant_id != c.tenant.id or x.status == "closed":
        raise HTTPException(404)
    now = clock.now(c.tenant)
    x.status, x.resolution, x.closed_at, x.owner_user_id = "closed", body.resolution, now, c.user.id if c.user else None
    emit(c.session, tenant_id=c.tenant.id, type=EventType.complaint_closed, at=now, actor=c.actor,
         policy_version=c.tenant.current_policy_version, case_id=x.case_id, borrower_id=x.borrower_id,
         payload={"complaint_id": x.id, "resolution": body.resolution, "within_sla": now <= x.sla_due_at})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings


@router.get("/settings")
def settings(c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    version, policy = policy_mod.current(s, t)
    versions = [{"version": p.version, "note": p.note, "by": p.created_by, "at": p.created_at.isoformat()}
                for p in s.scalars(select(Policy).where(Policy.tenant_id == t.id).order_by(Policy.version.desc()))]
    templates = [{"id": x.id, "key": x.key, "language": x.language, "version": x.version, "channel": x.channel,
                  "category": category(x.key), "body": x.body, "english": x.english_shadow, "variables": x.variables,
                  "status": x.status, "needs_native_review": x.needs_native_review, "approved_by": x.approved_by,
                  "approved_at": x.approved_at and x.approved_at.isoformat()}
                 for x in s.scalars(select(Template).where(Template.tenant_id == t.id)
                                    .order_by(Template.key, Template.language, Template.version.desc()))]
    users = [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "branch_id": u.branch_id,
              "officer_id": u.officer_id} for u in s.scalars(select(User).where(User.tenant_id == t.id)
                                                               .order_by(User.role, User.name))]
    mappings = [{"name": m.name, "kind": m.file_kind, "mapping": m.mapping}
                for m in s.scalars(select(ColumnMapping).where(ColumnMapping.tenant_id == t.id))]
    return {"policy_version": version, "policy": policy.model_dump(mode="json"), "versions": versions,
            "templates": templates, "brand": t.brand, "users": users,
            "integrations": {"mappings": mappings, "payment_provider": "mock (MMQR/KHQR partner: stub)",
                             "telegram": "live bot" if TELEGRAM_BOT_TOKEN else "simulated (set TELEGRAM_BOT_TOKEN)",
                             "data_region": t.data_region_note or DATA_HOSTING_REGION},
            "rules": RULES}


class PolicyBody(BaseModel):
    data: dict
    note: str | None = None


@router.put("/settings/policy")
def save_policy(body: PolicyBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    try:
        data = PolicyData.model_validate(body.data)
    except ValidationError as e:
        raise HTTPException(400, str(e))
    version = policy_mod.save_new_version(c.session, c.tenant, data, actor=c.actor, at=clock.now(c.tenant),
                                          note=body.note)
    # New decisions use the new version; past decisions keep theirs.
    score_open_cases(c.session, c.tenant, c.actor)
    return {"version": version}


class PreviewBody(BaseModel):
    ranking: dict
    segments: dict | None = None


@router.post("/settings/ranking-preview")
def ranking_preview(body: PreviewBody, c: Ctx = Depends(ctx)):
    s, t = c.session, c.tenant
    _, current = policy_mod.current(s, t)
    proposed = current.model_copy(deep=True)
    try:
        proposed.ranking = proposed.ranking.model_validate({**current.ranking.model_dump(), **body.ranking})
        if body.segments:
            proposed.segments = proposed.segments.model_validate({**current.segments.model_dump(), **body.segments})
    except ValidationError as e:
        raise HTTPException(400, str(e))
    cases = list(s.scalars(select(Case).where(Case.tenant_id == t.id, Case.status == "open")))
    feats = extract_features(s, t, cases, current)
    od = sorted(f.amount_overdue_rep for f in feats.values())
    po = sorted(f.principal_outstanding_rep for f in feats.values())
    names = dict(s.execute(select(Borrower.id, Borrower.name).where(Borrower.id.in_([x.borrower_id for x in cases]))).all())

    def ranked(policy):
        out = []
        for case in cases:
            f = feats[case.id]
            stake = 0.6 * _pct_rank(od, f.amount_overdue_rep) + 0.4 * _pct_rank(po, f.principal_outstanding_rep)
            sc = RANKER.score(f, stake, policy)
            out.append({"case_id": case.id, "borrower": names.get(case.borrower_id), "priority": sc.priority,
                        "segment": segment_for(f, sc, policy)[0]})
        out.sort(key=lambda x: -x["priority"])
        return out

    before, after = ranked(current), ranked(proposed)
    pos_before = {x["case_id"]: i + 1 for i, x in enumerate(before)}
    seg_before = {x["case_id"]: x["segment"] for x in before}
    top = [{**x, "rank": i + 1, "was": pos_before[x["case_id"]], "segment_was": seg_before[x["case_id"]]}
           for i, x in enumerate(after[:20])]
    moved = sum(1 for x in after if seg_before[x["case_id"]] != x["segment"])
    return {"top20": top, "segment_changes": moved}


class TemplateEdit(BaseModel):
    body: str
    english: str | None = None


@router.post("/settings/templates/{template_id}/edit")
def edit_template(template_id: int, body: TemplateEdit, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    old = c.session.get(Template, template_id)
    if old is None or old.tenant_id != c.tenant.id:
        raise HTTPException(404)
    latest = c.session.scalar(select(func.max(Template.version)).where(
        Template.tenant_id == c.tenant.id, Template.key == old.key, Template.language == old.language))
    new = Template(tenant_id=c.tenant.id, key=old.key, language=old.language, version=latest + 1, channel=old.channel,
                   body=body.body, english_shadow=body.english or old.english_shadow, variables=old.variables,
                   buttons=old.buttons, status="draft", needs_native_review=old.language != "en",
                   created_at=clock.now(c.tenant))
    c.session.add(new)
    c.session.flush()
    emit(c.session, tenant_id=c.tenant.id, type=EventType.template_changed, at=clock.now(c.tenant), actor=c.actor,
         policy_version=c.tenant.current_policy_version,
         payload={"template_id": new.id, "key": new.key, "language": new.language, "version": new.version,
                  "status": "draft"})
    return {"id": new.id, "version": new.version}


@router.post("/settings/templates/{template_id}/approve")
def approve_template(template_id: int, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    x = c.session.get(Template, template_id)
    if x is None or x.tenant_id != c.tenant.id:
        raise HTTPException(404)
    _, policy = policy_mod.current(c.session, c.tenant)
    hits = banned_in(policy, x.body, x.language) + banned_in(policy, x.english_shadow or "", "en")
    if hits:
        raise HTTPException(400, f"Banned phrases: {', '.join(hits)}")
    missing = [v for v in x.variables if "{" + v + "}" not in x.body and v not in ("lender_phone",)]
    now = clock.now(c.tenant)
    x.status, x.approved_by, x.approved_at = "approved", c.user.name if c.user else "demo", now
    for older in c.session.scalars(select(Template).where(
            Template.tenant_id == c.tenant.id, Template.key == x.key, Template.language == x.language,
            Template.id != x.id, Template.status == "approved")):
        older.status = "retired"
    emit(c.session, tenant_id=c.tenant.id, type=EventType.template_changed, at=now, actor=c.actor,
         policy_version=c.tenant.current_policy_version,
         payload={"template_id": x.id, "key": x.key, "language": x.language, "version": x.version,
                  "status": "approved", "unused_variables": missing})
    return {"ok": True, "unused_variables": missing}


@router.post("/settings/templates/{template_id}/native-review")
def native_review(template_id: int, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    x = c.session.get(Template, template_id)
    if x is None or x.tenant_id != c.tenant.id:
        raise HTTPException(404)
    x.needs_native_review = False
    emit(c.session, tenant_id=c.tenant.id, type=EventType.template_changed, at=clock.now(c.tenant), actor=c.actor,
         policy_version=c.tenant.current_policy_version,
         payload={"template_id": x.id, "key": x.key, "language": x.language, "version": x.version,
                  "native_review": "passed", "reviewer": c.user.name if c.user else None})
    return {"ok": True}


@router.put("/settings/brand")
def save_brand(body: dict, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    allowed = {"lender_name", "lender_name_local", "bot_display_name", "bot_username", "colors", "logo_text",
               "lender_phone", "charter"}
    brand = {**c.tenant.brand, **{k: v for k, v in body.items() if k in allowed}}
    c.tenant.brand = brand
    emit(c.session, tenant_id=c.tenant.id, type=EventType.brand_changed, at=clock.now(c.tenant), actor=c.actor,
         policy_version=c.tenant.current_policy_version, payload={k: v for k, v in body.items() if k in allowed})
    return brand
