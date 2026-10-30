"""Restructure plan generator.

Up to three options, each checked against policy:
  catch_up      regular instalment plus arrears spread over the next N instalments
  reschedule    arrears capitalised, tenor extended (up to policy max), lower instalment
  short_relief  reduced payments for 1-2 periods, then resume with tenor extended

The borrower never sees an option above their capacity. Options outside
policy can still be offered; accepting one goes to the approver's queue with
the exact breach.
"""
import math
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.credit.engine import CapacityInputs, capacity
from app.events import EventType, emit
from app.models import Borrower, Case, Loan, Plan, Schedule, Tenant
from app.money import round_cash
from app.policy import PolicyData
from app.seed.generator import add_months, period_rate

LABELS = {"catch_up": "Catch up", "reschedule": "Reschedule", "short_relief": "Short relief"}


def _next_dates(first: date, freq: str, n: int) -> list[date]:
    return [add_months(first, i) if freq == "monthly" else first + timedelta(days=14 * i) for i in range(n)]


def _annuity(balance: int, rate: float, n: int, currency: str) -> int:
    if n <= 0:
        return balance
    if rate == 0:
        return round_cash(balance / n, currency)
    return round_cash(balance * rate / (1 - (1 + rate) ** -n), currency)


def _amortise(balance: int, rate: float, n: int, currency: str) -> list[int]:
    inst = _annuity(balance, rate, n, currency)
    out, b = [], balance
    for i in range(n):
        interest = int(round(b * rate))
        if i == n - 1:
            out.append(b + interest)
        else:
            out.append(inst)
            b = b + interest - inst
    return out


def per_period(monthly: int | None, freq: str) -> int | None:
    if monthly is None:
        return None
    return monthly if freq == "monthly" else int(monthly * 12 / 26)


def generate_options(loan: Loan, future: list[Schedule], today: date, cap_period: int | None,
                     policy: PolicyData) -> list[dict]:
    cur, freq = loan.currency, loan.frequency
    rate = period_rate(loan.interest_rate_annual, freq)
    arrears = loan.amount_overdue
    n_rem = len(future)
    first_due = future[0].due_date if future else _next_dates(today, freq, 2)[1]
    plans_cfg = policy.plans
    options = []

    def finish(kind: str, amounts: list[int], extension: int, relief: int = 0, capitalised: bool = False) -> dict:
        dates = _next_dates(first_due, freq, len(amounts))
        regular = amounts[relief:] or amounts
        typical = max(set(regular), key=regular.count)
        breaches = []
        if extension > plans_cfg.max_tenor_extension_instalments:
            breaches.append({"rule": "max_tenor_extension", "label": "Max tenor extension",
                             "limit": plans_cfg.max_tenor_extension_instalments, "value": extension,
                             "over": extension - plans_cfg.max_tenor_extension_instalments, "unit": "instalments"})
        is_restructure = capitalised or extension > 0
        if is_restructure and loan.restructure_count >= plans_cfg.max_restructures_per_loan:
            breaches.append({"rule": "max_restructures", "label": "Max restructures per loan",
                             "limit": plans_cfg.max_restructures_per_loan, "value": loan.restructure_count + 1,
                             "over": loan.restructure_count + 1 - plans_cfg.max_restructures_per_loan,
                             "unit": "restructures"})
        min_inst = plans_cfg.min_instalment.get(cur, 0)
        if min(amounts) < min_inst:
            breaches.append({"rule": "min_instalment", "label": "Minimum instalment", "limit": min_inst,
                             "value": min(amounts), "over": min_inst - min(amounts), "unit": cur})
        if loan.product not in plans_cfg.eligible_products:
            breaches.append({"rule": "eligible_products", "label": "Eligible products", "limit": None,
                             "value": loan.product, "over": None, "unit": None})
        ceiling = plans_cfg.auto_approval_ceiling.get(cur)
        if ceiling is not None and arrears > ceiling:
            breaches.append({"rule": "auto_approval_ceiling", "label": "Auto-approval ceiling (arrears)",
                             "limit": ceiling, "value": arrears, "over": arrears - ceiling, "unit": cur})
        peak = max(amounts[relief:]) if amounts[relief:] else max(amounts)
        return {
            "type": kind, "label": LABELS[kind],
            "new_instalment": typical, "peak_instalment": peak, "first_payment": amounts[0],
            "relief_periods": relief, "relief_instalment": amounts[0] if relief else None,
            "extension": extension, "instalments": len(amounts),
            "new_end_date": dates[-1].isoformat(), "total_payable": sum(amounts),
            "original_total": arrears + sum(s.total_due - s.paid_amount for s in future),
            "original_instalment": loan.instalment_amount, "arrears": arrears,
            "periods": [{"no": i + 1, "due_date": d.isoformat(), "amount": a} for i, (d, a) in enumerate(zip(dates, amounts))],
            "within_policy": not breaches, "breaches": breaches,
            "affordable": cap_period is None or peak <= cap_period,
            "capacity_per_period": cap_period, "currency": cur, "frequency": freq,
        }

    # Catch-up: tenor unchanged unless fewer instalments remain than the spread.
    n = max(1, min(plans_cfg.catch_up_max_instalments, max(n_rem, 1)))
    span = max(n_rem, n)
    share = arrears / n
    amounts = []
    for i in range(span):
        base = (future[i].total_due - future[i].paid_amount) if i < n_rem else 0
        amounts.append(round_cash(base + (share if i < n else 0), cur))
    amounts[-1] += arrears + sum(s.total_due - s.paid_amount for s in future) - sum(amounts)
    options.append(finish("catch_up", amounts, extension=max(0, n - n_rem)))

    # Reschedule: capitalise arrears interest and penalties; extend to fit capacity.
    balance = loan.principal_outstanding + loan.interest_overdue + loan.penalty_overdue
    hard_max = plans_cfg.max_tenor_extension_instalments + 12
    chosen = None
    for ext in range(0, hard_max + 1):
        periods = max(1, n_rem) + ext
        inst = _annuity(balance, rate, periods, cur)
        if cap_period is None and ext == min(3, plans_cfg.max_tenor_extension_instalments) or \
                cap_period is not None and inst <= cap_period and inst < loan.instalment_amount:
            chosen = ext
            break
    if chosen is None:
        chosen = hard_max
    amounts = _amortise(balance, rate, max(1, n_rem) + chosen, cur)
    options.append(finish("reschedule", amounts, extension=max(1, n_rem) + chosen - n_rem, capitalised=True))

    # Short relief: reduced payments, then re-amortise the rest.
    p = plans_cfg.short_relief_periods
    reduced = round_cash(loan.instalment_amount * plans_cfg.short_relief_payment_share, cur)
    b = float(balance)
    for _ in range(p):
        b = b * (1 + rate) - reduced
    b = int(max(0, b))
    m_min = max(1, n_rem - p)
    chosen_m = None
    for m in range(m_min, m_min + hard_max + 1):
        inst = _annuity(b, rate, m, cur)
        if inst <= loan.instalment_amount and (cap_period is None or inst <= cap_period):
            chosen_m = m
            break
    chosen_m = chosen_m or m_min + hard_max
    amounts = [reduced] * p + _amortise(b, rate, chosen_m, cur)
    options.append(finish("short_relief", amounts, extension=p + chosen_m - n_rem, relief=p, capitalised=True))
    return options


def capacity_for(session: Session, tenant: Tenant, loan: Loan, borrower: Borrower, answers: dict | None,
                 policy: PolicyData) -> dict:
    appraisal = loan.appraisal or {}
    income = appraisal.get("household_income")
    source = "appraisal" if income is not None else "none"
    changed = (answers or {}).get("income_changed")
    if answers:
        if answers.get("income_now") is not None and (changed in ("less", "more") or income is None):
            income = int(answers["income_now"])
        source = "borrower_answers"
    inputs = CapacityInputs(
        household_income=income,
        household_expenses=appraisal.get("household_expenses") if appraisal.get("household_expenses") is not None
        else (int(income * 0.6) if income else None),
        other_debt_repayments=appraisal.get("other_debt_repayments", 0),
        source=source, income_changed=changed,
        new_debt_repayments=int((answers or {}).get("new_debt_repayments") or 0),
    )
    return capacity(borrower, inputs, policy.plans.max_share_of_surplus)


def generate_for_case(session: Session, tenant: Tenant, case: Case, *, answers: dict | None, actor: str) -> list[Plan]:
    version, policy = policy_mod.current(session, tenant)
    at = clock.now(tenant)
    today = clock.today(tenant)
    loan = session.get(Loan, case.loan_id)
    borrower = session.get(Borrower, case.borrower_id)
    current_version = session.scalar(select(Schedule.version).where(Schedule.loan_id == loan.id)
                                      .order_by(Schedule.version.desc()).limit(1)) or 1
    future = list(session.scalars(select(Schedule).where(
        Schedule.loan_id == loan.id, Schedule.version == current_version, Schedule.due_date >= today,
        Schedule.paid_amount < Schedule.total_due).order_by(Schedule.instalment_no)))
    cap = capacity_for(session, tenant, loan, borrower, answers, policy)
    cap_period = per_period(cap["monthly_capacity"], loan.frequency)
    options = generate_options(loan, future, today, cap_period, policy)

    # Supersede earlier offers that were never taken up.
    for old in session.scalars(select(Plan).where(Plan.case_id == case.id, Plan.status == "offered")):
        old.status = "superseded"
    gen = str(uuid.uuid4())
    plans = []
    for o in options:
        p = Plan(tenant_id=tenant.id, case_id=case.id, loan_id=loan.id, generation_id=gen, option_type=o["type"],
                 status="offered", details=o, capacity=cap, within_policy=o["within_policy"],
                 breaches=o["breaches"], policy_version=version, created_at=at)
        session.add(p)
        plans.append(p)
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.plan_options_generated, at=at, actor=actor,
         policy_version=version, case_id=case.id, loan_id=loan.id, borrower_id=borrower.id,
         payload={"generation_id": gen, "capacity": cap, "answers": answers,
                  "options": [{"plan_id": p.id, "type": p.option_type, "new_instalment": p.details["new_instalment"],
                               "peak_instalment": p.details["peak_instalment"], "extension": p.details["extension"],
                               "within_policy": p.within_policy, "affordable": p.details["affordable"],
                               "breaches": p.breaches} for p in plans]})
    case.state = "plan_offered"
    return plans


def approver_role(policy: PolicyData, plan: Plan) -> str:
    arrears = plan.details.get("arrears", 0)
    for rule in policy.approvals:
        if rule.kind != "plan":
            continue
        cap = (rule.max_amount or {}).get(plan.details["currency"])
        if rule.max_amount is None or cap is None or arrears <= cap:
            return rule.approver_role
    return "head_of_collections"
