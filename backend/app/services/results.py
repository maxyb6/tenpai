"""Results: treatment vs control, PAR30 trend, cost, fee. Computed from cases
and events only, with the working shown so every number can be traced.

Definitions:
  PAR30         principal of loans with any instalment > 30 days overdue / total principal
  cure rate     cases returned to current / cases opened (per arm, bucket at open)
  recovery rate cash collected on cases / amount overdue at case open
  roll rate     share of opening balance whose case moved to a later bucket
  promise kept  promises kept / promises resolved
  days to cure  mean days from case open to cure, cured cases only
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.models import Case, Event, Message, Promise, Tenant, Visit
from app.money import to_reporting
from app.services.health import health_check

BUCKET_ORDER = ["pre_due", "1_7", "8_30", "31_60", "61_90", "90_plus"]


def compute(session: Session, tenant: Tenant, weeks: int = 8) -> dict:
    version, policy = policy_mod.current(session, tenant)
    now = clock.now(tenant)
    # From the start of the local day 8 weeks back, so the first day's openings count.
    start = clock.local_datetime(tenant, (clock.local_now(tenant) - timedelta(weeks=weeks)).date(), 0)
    rep, fx = tenant.reporting_currency, tenant.fx
    r = lambda amount, cur: to_reporting(amount, cur, rep, fx)  # noqa: E731

    cases = list(session.scalars(select(Case).where(Case.tenant_id == tenant.id, Case.opened_at >= start)))
    ids = [c.id for c in cases]
    rolled = set(session.scalars(select(Event.case_id).where(
        Event.tenant_id == tenant.id, Event.type == "bucket_changed", Event.case_id.in_(ids))))
    promises = defaultdict(lambda: {"kept": 0, "broken": 0})
    for case_id, status in session.execute(select(Promise.case_id, Promise.status).where(Promise.case_id.in_(ids))):
        if status == "kept":
            promises[case_id]["kept"] += 1
        elif status in ("broken", "partial"):
            promises[case_id]["broken"] += 1
    visits = dict(session.execute(select(Visit.case_id, func.count(Visit.id)).where(
        Visit.case_id.in_(ids), Visit.status == "completed").group_by(Visit.case_id)).all())
    messages = dict(session.execute(select(Message.case_id, func.count(Message.id)).where(
        Message.case_id.in_(ids), Message.direction == "out",
        Message.status.in_(("sent", "delivered", "read"))).group_by(Message.case_id)).all())

    def agg(group: list[Case]) -> dict:
        n = len(group)
        cured = [c for c in group if c.close_reason == "cured"]
        opening = sum(r(c.amount_overdue_at_open, c.currency) for c in group)
        collected = sum(r(min(c.collected_amount, c.amount_overdue_at_open), c.currency) for c in group)
        rolled_bal = sum(r(c.amount_overdue_at_open, c.currency) for c in group if c.id in rolled)
        kept = sum(promises[c.id]["kept"] for c in group)
        resolved = kept + sum(promises[c.id]["broken"] for c in group)
        days = [(c.closed_at - c.opened_at).days for c in cured]
        return {
            "cases": n, "cured": len(cured), "cure_rate": round(len(cured) / n, 4) if n else None,
            "opening_balance": opening, "collected": collected,
            "recovery_rate": round(collected / opening, 4) if opening else None,
            "rolled_balance": rolled_bal, "roll_rate": round(rolled_bal / opening, 4) if opening else None,
            "promises_kept": kept, "promises_resolved": resolved,
            "promise_kept_rate": round(kept / resolved, 4) if resolved else None,
            "days_to_cure": round(sum(days) / len(days), 1) if days else None,
            "visits": sum(visits.get(c.id, 0) for c in group),
            "messages": sum(messages.get(c.id, 0) for c in group),
        }

    by_arm = {arm: agg([c for c in cases if c.arm == arm]) for arm in ("treatment", "control")}
    by_bucket = []
    for b in BUCKET_ORDER:
        group = [c for c in cases if c.bucket_at_open == b]
        if not group:
            continue
        by_bucket.append({"bucket": b, **{arm: agg([c for c in group if c.arm == arm])
                                          for arm in ("treatment", "control")}})

    # PAR30 trend from weekly portfolio snapshots plus today's health check.
    snaps = session.scalars(select(Event).where(Event.tenant_id == tenant.id, Event.type == "portfolio_snapshot",
                                                Event.created_at >= start - timedelta(days=1))
                            .order_by(Event.created_at))
    trend = [{"date": e.payload["as_of"], "par30": e.payload["total"]["par30"], "par1": e.payload["total"]["par1"],
              "par90": e.payload["total"]["par90"], "event_id": e.id} for e in snaps]
    hc = health_check(session, tenant)
    today = clock.today(tenant).isoformat()
    if not trend or trend[-1]["date"] != today:
        trend.append({"date": today, "par30": hc["summary"]["par30"], "par1": hc["summary"]["par1"],
                      "par90": hc["summary"]["par90"], "event_id": None})

    # Cost: officer visits avoided relative to the control group's visit rate.
    t, c = by_arm["treatment"], by_arm["control"]
    visit_cost = policy.visit_cost.get(rep, 0)
    msg_cost = policy.message_cost.get(rep, 0)
    ctrl_rate = c["visits"] / c["cases"] if c["cases"] else 0
    treat_rate = t["visits"] / t["cases"] if t["cases"] else 0
    avoided = max(0.0, (ctrl_rate - treat_rate) * t["cases"])
    treat_cost = t["visits"] * visit_cost + t["messages"] * msg_cost
    ctrl_cost = c["visits"] * visit_cost + c["messages"] * msg_cost
    cost = {
        "visit_cost": visit_cost, "message_cost": msg_cost, "currency": rep,
        "control_visit_rate": round(ctrl_rate, 3), "treatment_visit_rate": round(treat_rate, 3),
        "visits_avoided": round(avoided, 1), "visit_cost_avoided": int(avoided * visit_cost),
        "messages_sent": t["messages"],
        "treatment_cost_per_unit_recovered": round(treat_cost / t["collected"], 4) if t["collected"] else None,
        "control_cost_per_unit_recovered": round(ctrl_cost / c["collected"], 4) if c["collected"] else None,
    }

    # Fee: monthly platform fee + success fee % x incremental cash.
    fee_cfg = policy.fee
    uplift = (t["recovery_rate"] or 0) - (c["recovery_rate"] or 0)
    incremental = max(0, int(uplift * t["opening_balance"]))
    months = weeks / 4.345
    platform = int(fee_cfg.get("monthly_platform_fee", 0) * months)
    success = int(incremental * fee_cfg.get("success_fee_pct", 0))
    fee = {
        "formula": "monthly platform fee x months + success fee % x incremental cash",
        "incremental_formula": "(treated recovery rate - control recovery rate) x treated overdue balance at case open",
        "treated_recovery_rate": t["recovery_rate"], "control_recovery_rate": c["recovery_rate"],
        "uplift": round(uplift, 4), "treated_opening_balance": t["opening_balance"],
        "incremental_cash": incremental, "monthly_platform_fee": fee_cfg.get("monthly_platform_fee", 0),
        "months": round(months, 2), "platform_fee": platform, "success_fee_pct": fee_cfg.get("success_fee_pct", 0),
        "success_fee": success, "total": platform + success, "currency": rep,
    }
    return {
        "simulated": tenant.is_demo, "window_start": start.isoformat(), "as_of": now.isoformat(),
        "reporting_currency": rep, "policy_version": version,
        "by_arm": by_arm, "by_bucket": by_bucket, "par_trend": trend, "cost": cost, "fee": fee,
        "telegram_link_rate": hc["summary"]["telegram_link_rate_overdue"],
        "trace": {"cases": len(cases), "case_events": "case_opened, control_assigned, case_closed, bucket_changed",
                  "promise_events": "ptp_created, ptp_kept, ptp_broken", "visit_events": "visit_outcome",
                  "message_events": "message_sent", "par_events": "portfolio_snapshot"},
    }


def trace(session: Session, tenant: Tenant, arm: str, bucket: str | None, metric: str, weeks: int = 8) -> list[dict]:
    """The cases behind a number, with the event that decided each one."""
    start = clock.local_datetime(tenant, (clock.local_now(tenant) - timedelta(weeks=weeks)).date(), 0)
    q = select(Case).where(Case.tenant_id == tenant.id, Case.opened_at >= start, Case.arm == arm)
    if bucket:
        q = q.where(Case.bucket_at_open == bucket)
    out = []
    for c in session.scalars(q.order_by(Case.opened_at)):
        closed = session.scalars(select(Event).where(Event.case_id == c.id, Event.type == "case_closed")).first()
        out.append({"case_id": c.id, "opened_at": c.opened_at.isoformat(), "bucket_at_open": c.bucket_at_open,
                    "amount_overdue_at_open": c.amount_overdue_at_open, "collected": c.collected_amount,
                    "currency": c.currency, "close_reason": c.close_reason,
                    "closed_event_id": closed.id if closed else None})
    return out
