from datetime import date

from sqlalchemy import select

from app import policy as policy_mod
from app.domain import plans as plans_mod
from app.domain.ranking import CaseFeatures, RulesRanker, segment_for
from app.models import Case, Event, Loan, Schedule, Tenant
from app.policy import default_policy


def _features(**kw):
    base = dict(case_id=1, bucket="8_30", days_overdue=20, amount_overdue_rep=100_000,
                principal_outstanding_rep=1_000_000, amount_overdue=100_000, currency="MMK",
                instalments_considered=6, instalments_on_time=6, promises_kept=0, promises_broken=0,
                savings_regular_before=False, weeks_since_deposit=0, telegram_linked=True,
                telegram_last_inbound_days=5, sms_invite_sent_days=None, has_phone=True, prior_restructures=0,
                loan_cycle=1, unanswered_attempts=0)
    base.update(kw)
    return CaseFeatures(**base)


def test_reason_codes_explain_the_score():
    p = default_policy("MM")
    good = RulesRanker().score(_features(), 50, p)
    bad = RulesRanker().score(_features(instalments_on_time=1, promises_kept=1, promises_broken=2,
                                        savings_regular_before=True, weeks_since_deposit=6,
                                        telegram_linked=False), 50, p)
    assert good.pay_likelihood > bad.pay_likelihood
    texts = [r["text"] for r in bad.reason_codes]
    assert "2 of 3 promises broken" in texts
    assert "Savings deposits stopped 6 weeks ago" in texts
    assert "20 days overdue" in texts
    # The sum of impacts plus the bucket base rate is the score (before clamping).
    from app.domain.ranking import BUCKET_BASE_RATE

    assert abs(BUCKET_BASE_RATE["8_30"] + sum(r["impact"] for r in bad.reason_codes) - bad.pay_likelihood) < 0.2


def test_segments():
    p = default_policy("MM")
    r = RulesRanker()
    f = _features()
    assert segment_for(f, r.score(f, 50, p), p)[0] == "nudge"
    f = _features(sensitive_flags=["vulnerability"])
    assert segment_for(f, r.score(f, 50, p), p)[0] == "sensitive"
    f = _features(telegram_linked=False, has_phone=False)
    assert segment_for(f, r.score(f, 50, p), p)[0] == "visit"
    f = _features(bucket="90_plus")
    assert segment_for(f, r.score(f, 50, p), p)[0] == "visit"
    f = _features(instalments_on_time=0, telegram_last_inbound_days=None, loan_cycle=1)
    assert segment_for(f, r.score(f, 40, p), p)[0] == "plan"


def test_scored_event_holds_exact_inputs(seeded_mm, session):
    case = session.scalars(select(Case).where(Case.tenant_id == "mm-demo", Case.last_score_event_id.is_not(None))
                           .limit(1)).one()
    ev = session.get(Event, case.last_score_event_id)
    assert ev.type == "scored"
    assert ev.payload["reason_codes"] == case.reason_codes
    assert ev.payload["priority"] == case.priority and ev.payload["segment"] == case.segment
    assert ev.payload["inputs"]["case_id"] == case.id


def _future(session, loan, today):
    return list(session.scalars(select(Schedule).where(Schedule.loan_id == loan.id, Schedule.version == 1,
                                                       Schedule.due_date >= today,
                                                       Schedule.paid_amount < Schedule.total_due)
                                .order_by(Schedule.instalment_no)))


def test_plan_options_respect_capacity_and_flag_breaches(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    _, policy = policy_mod.current(session, tenant)
    today = date(2026, 11, 5)
    loans = session.scalars(select(Loan).where(Loan.tenant_id == "mm-demo", Loan.days_overdue.between(10, 40),
                                               Loan.loan_type == "individual").limit(25)).all()
    for loan in loans:
        future = _future(session, loan, today)
        cap = int(loan.instalment_amount * 0.6)
        options = plans_mod.generate_options(loan, future, today, cap, policy)
        assert {o["type"] for o in options} == {"catch_up", "reschedule", "short_relief"}
        for o in options:
            peak = max(p["amount"] for p in o["periods"][o["relief_periods"]:])
            assert o["affordable"] == (peak <= cap)
            ext = o["extension"]
            breached = any(b["rule"] == "max_tenor_extension" for b in o["breaches"])
            assert breached == (ext > policy.plans.max_tenor_extension_instalments)
            assert o["within_policy"] == (not o["breaches"])
            # Every option pays off at least the arrears and the remaining schedule's principal.
            assert o["total_payable"] >= loan.amount_overdue


def test_catch_up_keeps_total_unchanged(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    _, policy = policy_mod.current(session, tenant)
    today = date(2026, 11, 5)
    loan = session.scalars(select(Loan).where(Loan.tenant_id == "mm-demo", Loan.days_overdue.between(10, 30),
                                              Loan.loan_type == "individual").limit(1)).one()
    future = _future(session, loan, today)
    cu = next(o for o in plans_mod.generate_options(loan, future, today, None, policy) if o["type"] == "catch_up")
    assert cu["total_payable"] == cu["original_total"]
