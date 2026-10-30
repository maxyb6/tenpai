"""Every number on Results traces back to events; visit outcomes feed the case."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import Case, Event, Promise, Tenant, Visit
from app.services import field as field_svc
from app.services import results as results_svc

TZ = ZoneInfo("Asia/Yangon")


def _events(session, type_, case_ids):
    return list(session.scalars(select(Event).where(Event.type == type_, Event.case_id.in_(case_ids))))


def test_results_trace_to_events(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    r = results_svc.compute(session, tenant)
    for arm in ("treatment", "control"):
        rows = results_svc.trace(session, tenant, arm, None, "cure_rate")
        ids = [x["case_id"] for x in rows]
        assert r["by_arm"][arm]["cases"] == len(ids)
        opened = _events(session, "control_assigned", ids)
        assert len(opened) == len(ids) and all(e.payload["arm"] == arm for e in opened)
        cured = {e.case_id for e in _events(session, "case_closed", ids) if e.payload["reason"] == "cured"}
        assert r["by_arm"][arm]["cured"] == len(cured)
        rolled = {e.case_id for e in _events(session, "bucket_changed", ids)}
        cases = {c.id: c for c in session.scalars(select(Case).where(Case.id.in_(ids)))}
        rolled_bal = sum(cases[i].amount_overdue_at_open for i in rolled)
        assert r["by_arm"][arm]["rolled_balance"] == rolled_bal  # MMK: reporting currency, no conversion
        # Cash collected = matched payments + amounts the import showed paid outside Tenpai.
        matched = sum(e.payload["amount"] for e in _events(session, "payment_matched", ids))
        outside = sum(e.payload.get("collected_outside_tenpai", 0) for e in _events(session, "loan_imported", ids))
        assert sum(c.collected_amount for c in cases.values()) == matched + outside
    for point in r["par_trend"]:
        if point["event_id"]:
            ev = session.get(Event, point["event_id"])
            assert ev.type == "portfolio_snapshot" and ev.payload["total"]["par30"] == point["par30"]


def test_simulated_uplift_is_modest(seeded_mm, session):
    r = results_svc.compute(session, session.get(Tenant, "mm-demo"))
    t, c = r["by_arm"]["treatment"], r["by_arm"]["control"]
    assert 0 <= t["cure_rate"] - c["cure_rate"] <= 0.15
    assert 0.10 <= c["cases"] / (c["cases"] + t["cases"]) <= 0.20


def test_visit_outcome_promise_feeds_case(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    tenant.demo_now = datetime(2026, 11, 5, 15, 0, tzinfo=TZ)
    v = session.scalars(select(Visit).where(Visit.tenant_id == "mm-demo", Visit.status == "assigned")).first()
    field_svc.record_outcome(session, tenant, v, outcome="promised", actor="officer:test", notes="ok",
                             promise_amount=20_000, promise_date=date(2026, 11, 12), photo_b64=None, lat=16.8, lng=96.1)
    assert v.status == "completed" and v.promise_id
    p = session.get(Promise, v.promise_id)
    assert p.source == "officer" and p.amount == 20_000
    ev = session.scalars(select(Event).where(Event.type == "visit_outcome", Event.case_id == v.case_id)
                         .order_by(Event.id.desc())).first()
    assert ev.payload["outcome"] == "promised" and ev.payload["gps"] == [16.8, 96.1]


def test_hardship_visit_pauses_automation(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    tenant.demo_now = datetime(2026, 11, 5, 15, 0, tzinfo=TZ)
    v = session.scalars(select(Visit).where(Visit.tenant_id == "mm-demo", Visit.status == "assigned")
                        .offset(1)).first()
    field_svc.record_outcome(session, tenant, v, outcome="hardship", actor="officer:test", notes="flood")
    case = session.get(Case, v.case_id)
    assert case.automation_paused and case.pause_reason == "vulnerability"
