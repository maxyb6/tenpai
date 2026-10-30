"""Deterministic sample book.

`generate(market, as_of)` returns the same world for the same inputs. The world
is expressed as rows in canonical import form (minor units, dates), plus the
things that are not in a core banking export (staff, users, Telegram links).
`mifos_export.write` turns it into the sample Mifos X CSVs, and the seed loader
imports those CSVs through the same pipeline a real lender file goes through.

Everything here is fictional and labelled as sample data.
"""
import calendar
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.money import round_cash
from app.seed import names

N_LOANS = 1500
N_GROUPS = 120
GROUP_SIZE = 5
OFFICERS_PER_BRANCH = 4

BUCKET_WEIGHTS = [((1, 7), 0.32), ((8, 30), 0.30), ((31, 60), 0.08), ((61, 90), 0.05), ((91, 400), 0.25)]

TENANTS = {
    "MM": {
        "id": "mm-demo",
        "name": "Padonmar Microfinance (Sample)",
        "market": "MM",
        "timezone": "Asia/Yangon",
        "reporting_currency": "MMK",
        "fx": {},
        "brand": {
            "lender_name": "Padonmar Microfinance",
            "lender_name_local": "ပဒုမ္မာ အသေးစားငွေရေးကြေးရေး",
            "bot_display_name": "Padonmar Microfinance",
            "bot_username": "padonmar_sample_bot",
            "colors": {"primary": "#8C2F39", "accent": "#D9A441", "background": "#FBF7F2"},
            "logo_text": "P",
            "lender_phone": "+95 1 000 0000 (sample)",
        },
        "language": "my",
    },
    "KH": {
        "id": "kh-demo",
        "name": "Mlis Microfinance (Sample)",
        "market": "KH",
        "timezone": "Asia/Phnom_Penh",
        "reporting_currency": "USD",
        "fx": {"KHR": 4050},
        "brand": {
            "lender_name": "Mlis Microfinance",
            "lender_name_local": "ម្លិះ មីក្រូហិរញ្ញវត្ថុ",
            "bot_display_name": "Mlis Microfinance",
            "bot_username": "mlis_sample_bot",
            "colors": {"primary": "#1F4E79", "accent": "#E0A526", "background": "#F5F8FB"},
            "logo_text": "M",
            "lender_phone": "+855 23 000 000 (sample)",
        },
        "language": "km",
    },
}

# product, loan_type, currency, frequency, terms, principal range (major), step (major), annual rate
PRODUCTS = {
    "MM": {
        "individual": [
            (0.7, "General Business Loan", "MMK", "monthly", [12], (500_000, 3_000_000), 50_000, 28.0),
            (0.3, "Agriculture Loan", "MMK", "monthly", [6, 9], (300_000, 1_500_000), 50_000, 28.0),
        ],
        "group": ("Group Loan", "MMK", "fortnightly", [24], (200_000, 800_000), 50_000, 28.0),
    },
    "KH": {
        "individual": [
            (0.65, "Business Loan", "USD", "monthly", [12, 18, 24], (500, 5_000), 50, 18.0),
            (0.35, "Agriculture Loan", "KHR", "monthly", [12], (2_000_000, 12_000_000), 100_000, 18.0),
        ],
        "group": ("Group Loan", "KHR", "fortnightly", [24], (800_000, 3_000_000), 100_000, 18.0),
    },
}
MINOR = {"MMK": 1, "KHR": 1, "USD": 100}


@dataclass
class World:
    market: str
    as_of: date
    tenant: dict
    branches: list[dict]
    officers: list[dict]
    users: list[dict]
    loans: list[dict] = field(default_factory=list)
    schedule: list[dict] = field(default_factory=list)
    savings: list[dict] = field(default_factory=list)
    telegram: list[dict] = field(default_factory=list)
    # Extra rows that exist only in the CSV, to exercise validation.
    bad_rows: list[dict] = field(default_factory=list)
    # 8 weeks of case history: openings in order, with the arm the real
    # assignment will give them and the simulated outcome.
    history: dict = field(default_factory=dict)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def due_date(first_due: date, freq: str, i: int) -> date:
    """Due date of instalment i (1-indexed)."""
    return add_months(first_due, i - 1) if freq == "monthly" else first_due + timedelta(days=14 * (i - 1))


def period_rate(annual_pct: float, freq: str) -> float:
    return annual_pct / 100 / 12 if freq == "monthly" else annual_pct / 100 * 14 / 365


def annuity_schedule(principal: int, annual_pct: float, n: int, freq: str, currency: str, first_due: date):
    r = period_rate(annual_pct, freq)
    inst = round_cash(principal * r / (1 - (1 + r) ** -n), currency)
    rows, balance = [], principal
    for i in range(1, n + 1):
        interest = int(round(balance * r))
        principal_part = balance if i == n else min(balance, inst - interest)
        balance -= principal_part
        rows.append({
            "instalment_no": i,
            "due_date": due_date(first_due, freq, i),
            "principal_due": principal_part,
            "interest_due": interest,
            "total_due": principal_part + interest,
        })
    return inst, rows


def generate(market: str, as_of: date, seed: int = 7) -> World:
    rng = random.Random(f"tenpai:{market}:{seed}:{as_of.isoformat()}")
    cfg = TENANTS[market]
    branch_defs = names.MM_BRANCHES if market == "MM" else names.KH_BRANCHES

    used_names: set[str] = set()

    def person(gender: str, older: bool) -> tuple[str, str]:
        for _ in range(200):
            if market == "MM":
                pool = names.MM_SYLLABLES_F if gender == "F" else names.MM_SYLLABLES_M
                parts = rng.sample(pool, rng.choice([2, 2, 3]))
                hon = names.MM_HONORIFIC[f"{gender}_{'old' if older else 'young'}"]
                roman = f"{hon[0]} " + " ".join(p[0] for p in parts)
                local = hon[1] + "".join(p[1] for p in parts)
            else:
                fam = rng.choice(names.KH_FAMILY)
                given = rng.choice(names.KH_GIVEN_F if gender == "F" else names.KH_GIVEN_M)
                roman, local = f"{fam[0]} {given[0]}", f"{fam[1]} {given[1]}"
            if roman not in used_names or market == "KH" and len(used_names) > 250:
                used_names.add(roman)
                return roman, local
        return roman, local

    branches, officers, users = [], [], []
    for b_idx, b in enumerate(branch_defs):
        branches.append({"code": b["code"], "name": b["name"], "name_local": b["name_local"],
                         "villages": b["villages"]})
        for o in range(OFFICERS_PER_BRANCH):
            g = rng.choice("FM")
            nm, nm_local = person(g, older=False)
            officers.append({
                "code": f"{b['code']}-O{o + 1}",
                "name": nm,
                "name_local": nm_local,
                "branch": b["name"],
                "phone": fake_phone(market, rng),
            })
        mgr, mgr_local = person(rng.choice("FM"), older=True)
        users.append({"name": mgr, "role": "branch_manager", "branch": b["name"],
                      "email": f"bm.{b['code'].lower()}@sample.invalid"})
    hoc, _ = person("F", older=True)
    ceo, _ = person("M", older=True)
    cfo, _ = person("F", older=True)
    users = [
        {"name": hoc, "role": "head_of_collections", "email": "collections@sample.invalid"},
        {"name": ceo, "role": "leadership", "email": "ceo@sample.invalid", "title": "CEO"},
        {"name": cfo, "role": "leadership", "email": "cfo@sample.invalid", "title": "CFO"},
        *users,
        *[{"name": o["name"], "role": "credit_officer", "branch": o["branch"], "officer": o["name"],
           "email": f"{o['code'].lower()}@sample.invalid"} for o in officers],
    ]

    world = World(market=market, as_of=as_of, tenant=cfg, branches=branches, officers=officers, users=users)
    officers_by_branch = {b["name"]: [o for o in officers if o["branch"] == b["name"]] for b in branches}

    loan_seq = 0
    client_seq = 0

    def next_ids():
        nonlocal loan_seq, client_seq
        loan_seq += 1
        client_seq += 1
        prefix = "MM" if market == "MM" else "KH"
        return (f"{prefix}-C{client_seq:06d}", f"{prefix}-L{loan_seq:07d}", f"{prefix}-S{client_seq:06d}")

    def draw_bucket_days() -> int:
        x, acc = rng.random(), 0.0
        for (lo, hi), w in BUCKET_WEIGHTS:
            acc += w
            if x <= acc:
                return rng.randint(lo, hi)
        return rng.randint(91, 400)

    # --- group loans ---------------------------------------------------------
    gp = PRODUCTS[market]["group"]
    for g in range(N_GROUPS):
        b = branches[g % len(branches)]
        officer = rng.choice(officers_by_branch[b["name"]])
        village = rng.choice(b["villages"])
        product, currency, freq, terms, (lo, hi), step, rate = gp
        term = rng.choice(terms)
        # Group position: how many instalments have fallen due, and how soon the next one is.
        last_due_idx = rng.randint(1, term - 1)
        next_due_in = rng.randint(0, 13)
        first_due = as_of + timedelta(days=next_due_in) - timedelta(days=14 * last_due_idx)
        disbursed = first_due - timedelta(days=14)
        group_name = f"{village} Group {g + 1:03d}"
        group_shock = rng.random() < 0.15
        for _ in range(GROUP_SIZE):
            principal = rng.randrange(lo, hi + 1, step) * MINOR[currency]
            if group_shock and rng.random() < 0.7:
                # Missed from instalment j onwards; recent misses are more common.
                j = max(1, last_due_idx - min(int(rng.expovariate(0.35)), last_due_idx - 1))
                state = ("overdue", j)
            else:
                state = ("current", None)
            _make_loan(world, rng, next_ids(), person, b, officer, village, group_name, product, currency,
                       freq, term, principal, rate, first_due, disbursed, state)

    # --- individual loans ----------------------------------------------------
    n_individual = N_LOANS - N_GROUPS * GROUP_SIZE
    for _ in range(n_individual):
        b = rng.choice(branches)
        officer = rng.choice(officers_by_branch[b["name"]])
        village = rng.choice(b["villages"])
        x, acc = rng.random(), 0.0
        for weight, *spec in PRODUCTS[market]["individual"]:
            acc += weight
            if x <= acc:
                break
        product, currency, freq, terms, (lo, hi), step, rate = spec
        term = rng.choice(terms)
        principal = rng.randrange(lo, hi + 1, step) * MINOR[currency]
        if rng.random() < 0.12:
            days = draw_bucket_days()
            oldest_unpaid_due = as_of - timedelta(days=days)
            k = rng.randint(1, max(1, term - 1))
            first_due = add_months(oldest_unpaid_due, -(k - 1))
            state = ("overdue", k)
        else:
            n_due = rng.randint(1, term - 1)
            next_due = as_of + timedelta(days=rng.randint(0, 29))
            first_due = add_months(next_due, -n_due)
            state = ("current", None)
        disbursed = add_months(first_due, -1)
        _make_loan(world, rng, next_ids(), person, b, officer, village, None, product, currency,
                   freq, term, principal, rate, first_due, disbursed, state)

    _history(world, rng)
    _inject_quality_issues(world, rng)
    return world


def fake_phone(market: str, rng: random.Random) -> str:
    # Deliberately unallocated ranges: +95 9 000..., +855 00...
    return f"+959000{rng.randint(0, 999_999):06d}" if market == "MM" else f"+85500{rng.randint(0, 999_999):06d}"


def _make_loan(world, rng, ids, person, branch, officer, village, group_name, product, currency, freq, term,
               principal, rate, first_due, disbursed, state):
    as_of = world.as_of
    market = world.market
    client_id, loan_id, savings_no = ids
    gender = "F" if rng.random() < 0.88 else "M"
    name, name_local = person(gender, older=rng.random() < 0.6)
    inst, rows = annuity_schedule(principal, rate, term, freq, currency, first_due)

    overdue = state[0] == "overdue"
    oldest_unpaid = state[1] if overdue else None
    # Discipline drives on-time history. Overdue borrowers were more often late before they stopped.
    late_prob = rng.uniform(0.25, 0.6) if overdue else rng.choice([0.02, 0.05, 0.1, 0.3])

    paid_principal = paid_interest = 0
    last_pay_date, last_pay_amount = None, None
    partial_paid = 0
    for r in rows:
        r["paid_amount"], r["paid_on"] = 0, None
        if r["due_date"] > as_of:
            continue
        if overdue and r["instalment_no"] >= oldest_unpaid:
            continue
        if r["due_date"] < as_of or rng.random() < 0.3:  # some pay on the due day itself
            late = rng.randint(1, 12) if rng.random() < late_prob else -rng.randint(0, 1)
            paid_on = min(r["due_date"] + timedelta(days=late), as_of)
            r["paid_amount"], r["paid_on"] = r["total_due"], paid_on
            paid_principal += r["principal_due"]
            paid_interest += r["interest_due"]
            if last_pay_date is None or paid_on > last_pay_date:
                last_pay_date, last_pay_amount = paid_on, r["total_due"]

    if overdue and rng.random() < 0.25:
        r = rows[oldest_unpaid - 1]
        partial_paid = round_cash(r["total_due"] * rng.uniform(0.2, 0.6), currency)
        span = max(0, (as_of - r["due_date"]).days)
        pay_date = r["due_date"] + timedelta(days=rng.randint(0, span))
        r["paid_amount"] = partial_paid
        # Interest first, then principal.
        paid_interest += min(partial_paid, r["interest_due"])
        paid_principal += max(0, partial_paid - r["interest_due"])
        if last_pay_date is None or pay_date > last_pay_date:
            last_pay_date, last_pay_amount = pay_date, partial_paid

    due_rows = [r for r in rows if r["due_date"] <= as_of]
    unpaid_due = [r for r in due_rows if r["paid_amount"] < r["total_due"]]
    # Due today and not yet paid is not overdue.
    overdue_rows = [r for r in unpaid_due if r["due_date"] < as_of]
    principal_overdue = interest_overdue = 0
    for r in overdue_rows:
        paid = r["paid_amount"]
        int_paid = min(paid, r["interest_due"])
        interest_overdue += r["interest_due"] - int_paid
        principal_overdue += r["principal_due"] - (paid - int_paid)
    days_overdue = (as_of - overdue_rows[0]["due_date"]).days if overdue_rows else 0
    future = [r for r in rows if r["paid_amount"] < r["total_due"] and r["due_date"] >= as_of]
    next_due = future[0]["due_date"] if future else None
    total_interest = sum(r["interest_due"] for r in rows)

    # Monthly-equivalent instalment for appraisal.
    monthly_inst = inst if freq == "monthly" else inst * 26 / 12
    appraisal = None
    if rng.random() < 0.8:
        surplus = monthly_inst / rng.uniform(0.35, 0.6)
        e, d = rng.uniform(0.5, 0.7), rng.uniform(0.0, 0.12)
        income = surplus / (1 - e - d)
        appraisal = {
            "household_income": round_cash(income, currency),
            "household_expenses": round_cash(income * e, currency),
            "other_debt_repayments": round_cash(income * d, currency),
        }

    # --- savings: compulsory deposit at disbursement, then at each repayment meeting
    savings_txns = []
    balance = round_cash(principal * 0.05, currency)
    savings_txns.append({"txn_date": disbursed, "txn_type": "deposit", "amount": balance, "balance_after": balance})
    regular = round_cash(principal * (0.01 if freq == "monthly" else 0.005), currency)
    stopped_weeks = None
    if overdue and (days_overdue > 30 and rng.random() < 0.7 or days_overdue > 7 and rng.random() < 0.35):
        stopped_weeks = min(26, days_overdue // 7 + rng.randint(1, 4))
    elif not overdue and rng.random() < 0.06:
        stopped_weeks = rng.randint(4, 9)  # early warning on a current loan
    stop_date = as_of - timedelta(weeks=stopped_weeks) if stopped_weeks else None
    for r in rows:
        if r["paid_on"] and r["paid_amount"] >= r["total_due"]:
            if stop_date and r["paid_on"] >= stop_date:
                continue
            if rng.random() < 0.9:
                balance += regular
                savings_txns.append({"txn_date": r["paid_on"], "txn_type": "deposit", "amount": regular,
                                     "balance_after": balance})
            if rng.random() < 0.04 and balance > regular * 3:
                w = round_cash(balance * rng.uniform(0.2, 0.5), currency)
                balance -= w
                savings_txns.append({"txn_date": r["paid_on"], "txn_type": "withdrawal", "amount": w,
                                     "balance_after": balance})
    for t in savings_txns:
        world.savings.append({"savings_account_no": savings_no, "client_external_id": client_id, **t})

    phone = fake_phone(market, rng)
    cycle = rng.choices([1, 2, 3, 4, 5, 6], weights=[30, 25, 18, 12, 9, 6])[0]
    world.loans.append({
        "branch": branch["name"],
        "officer": officer["name"],
        "client_external_id": client_id,
        "client_name": name,
        "client_name_local": name_local,
        "gender": gender,
        "phone": phone,
        "national_id": f"SAMPLE-ID-{client_id[-6:]}",
        "group_name": group_name,
        "village": village,
        "loan_external_id": loan_id,
        "product": product,
        "currency": currency,
        "loan_cycle": cycle,
        "disbursed_on": disbursed,
        "principal_disbursed": principal,
        "interest_rate_annual": rate,
        "term_instalments": term,
        "frequency": freq,
        "instalment_amount": inst,
        "principal_outstanding": principal - paid_principal,
        "interest_outstanding": total_interest - paid_interest,
        "principal_overdue": principal_overdue,
        "interest_overdue": interest_overdue,
        "penalty_overdue": 0,
        "days_overdue": days_overdue,
        "arrears_as_of": as_of,
        "next_due_date": next_due,
        "last_repayment_date": last_pay_date,
        "last_repayment_amount": last_pay_amount,
        "savings_account_no": savings_no,
        "savings_balance": balance,
        **(appraisal or {"household_income": None, "household_expenses": None, "other_debt_repayments": None}),
    })
    for r in rows:
        world.schedule.append({"loan_external_id": loan_id, **r})

    # --- Telegram (Tenpai-side state, not in the core banking export)
    link_p = (0.5 if market == "MM" else 0.56) * (0.6 if days_overdue > 90 else 1.0)
    if rng.random() < link_p:
        method = rng.choices(["disbursement_qr", "officer_visit", "sms_deeplink"], weights=[60, 30, 10])[0]
        linked_on = min(as_of - timedelta(days=1), disbursed + timedelta(days=rng.randint(0, 60)))
        responsive = rng.random() < (0.65 if not overdue else 0.4)
        world.telegram.append({
            "client_external_id": client_id,
            "method": method,
            "linked_on": linked_on,
            "last_inbound_on": as_of - timedelta(days=rng.randint(1, 45)) if responsive else None,
        })


def _inject_quality_issues(world: World, rng: random.Random):
    """Realistic problems a first export usually has. Missing phones are real rows;
    the rest exist only in the CSV and the importer must catch them."""
    for row in rng.sample(world.loans, 3):
        row["phone"] = None
    overdue = [r for r in world.loans if r["days_overdue"] > 0]
    current = [r for r in world.loans if r["days_overdue"] == 0]

    # Repayments recorded after the arrears run: the arrears fields are stale.
    for row in rng.sample(overdue, 8):
        row["arrears_as_of"] = world.as_of - timedelta(days=2)
        row["last_repayment_date"] = world.as_of - timedelta(days=1)
        row["last_repayment_amount"] = row["principal_overdue"] + row["interest_overdue"]

    dup = dict(rng.choice(current))
    dup["principal_outstanding"] = dup["principal_outstanding"] + 10_000 * MINOR[dup["currency"]]
    neg = dict(rng.choice(current))
    neg["loan_external_id"] = neg["loan_external_id"].replace("-L", "-L9")
    neg["client_external_id"] = neg["client_external_id"].replace("-C", "-C9")
    neg["principal_outstanding"] = -abs(neg["principal_outstanding"])
    fut = dict(rng.choice(current))
    fut["loan_external_id"] = fut["loan_external_id"].replace("-L", "-L8")
    fut["client_external_id"] = fut["client_external_id"].replace("-C", "-C8")
    fut["disbursed_on"] = world.as_of + timedelta(days=12)
    world.bad_rows = [dup, neg, fut]


# ---------------------------------------------------------------------------
# History: 8 weeks of overdue episodes, decided together with the export so the
# two never contradict each other.

HISTORY_DAYS = 56
EPISODE_RATE = 0.2
DEEP_RATE = 0.1
DEEP_CURE = {"treatment": (0.88, 42, 12.0), "control": (0.74, 46, 16.0)}
# Simulated outcomes. Modest uplift: treatment cures a little more often and faster,
# mostly for borrowers Tenpai can reach on Telegram.
CURE = {("treatment", True): (0.93, 5.0), ("treatment", False): (0.88, 8.0), ("control", None): (0.85, 9.5)}


def loan_state(row: dict, rows: list[dict], as_of: date) -> dict:
    """Recompute a loan's arrears fields from its schedule as of a date."""
    principal_paid = interest_paid = 0
    last = (None, None)
    for r in rows:
        paid = r["paid_amount"]
        if not paid:
            continue
        int_paid = min(paid, r["interest_due"])
        interest_paid += int_paid
        principal_paid += paid - int_paid
        if r["paid_on"] and (last[0] is None or r["paid_on"] > last[0]):
            last = (r["paid_on"], r["paid_amount"])
    overdue_rows = [r for r in rows if r["due_date"] < as_of and r["paid_amount"] < r["total_due"]]
    p_over = i_over = 0
    for r in overdue_rows:
        int_paid = min(r["paid_amount"], r["interest_due"])
        i_over += r["interest_due"] - int_paid
        p_over += r["principal_due"] - (r["paid_amount"] - int_paid)
    future = [r for r in rows if r["paid_amount"] < r["total_due"] and r["due_date"] >= as_of]
    return {
        "principal_outstanding": row["principal_disbursed"] - principal_paid,
        "interest_outstanding": sum(r["interest_due"] for r in rows) - interest_paid,
        "principal_overdue": p_over, "interest_overdue": i_over,
        "days_overdue": (as_of - overdue_rows[0]["due_date"]).days if overdue_rows else 0,
        "next_due_date": future[0]["due_date"] if future else None,
        "last_repayment_date": last[0] if last[0] else row["last_repayment_date"],
        "last_repayment_amount": last[1] if last[0] else row["last_repayment_amount"],
    }


def _bucket(days: int) -> str:
    from app.policy import DEFAULT_BUCKETS

    for b in DEFAULT_BUCKETS:
        if b.min_days >= 1 and days >= b.min_days and (b.max_days is None or days <= b.max_days):
            return b.key
    return "1_7"


def _history(world: World, rng: random.Random) -> None:
    from app.domain.control import block_layout, stratum_key
    from app.policy import ControlGroup

    as_of = world.as_of
    t0 = as_of - timedelta(days=HISTORY_DAYS)
    ctrl = ControlGroup()
    sched: dict[str, list[dict]] = {}
    for r in world.schedule:
        sched.setdefault(r["loan_external_id"], []).append(r)
    linked = {t["client_external_id"] for t in world.telegram}

    openings = []
    for loan in world.loans:
        rows = sched[loan["loan_external_id"]]
        if loan["days_overdue"] > 0:
            first_unpaid = (as_of - timedelta(days=loan["days_overdue"]))
            open_date = max(t0, first_unpaid + timedelta(days=1))
            openings.append({"loan": loan["loan_external_id"], "kind": "overdue", "open_date": open_date,
                             "first_unpaid": first_unpaid, "branch": loan["branch"],
                             "linked": loan["client_external_id"] in linked})
            continue
        deep = [r for r in rows if t0 - timedelta(days=75) <= r["due_date"] <= t0 - timedelta(days=20)
                and r["paid_on"] and r["paid_amount"] >= r["total_due"]]
        if deep and rng.random() < DEEP_RATE:
            # Went past 30 days, then recovered: what keeps a real book's PAR30 from only rising.
            r = rng.choice(deep)
            openings.append({"loan": loan["loan_external_id"], "kind": "episode", "deep": True,
                             "open_date": max(t0, r["due_date"] + timedelta(days=1)), "first_unpaid": r["due_date"],
                             "instalment_no": r["instalment_no"], "branch": loan["branch"],
                             "linked": loan["client_external_id"] in linked})
            continue
        eligible = [r for r in rows if t0 < r["due_date"] <= as_of - timedelta(days=3) and r["paid_on"]
                    and r["paid_amount"] >= r["total_due"]]
        if eligible and rng.random() < EPISODE_RATE:
            r = rng.choice(eligible)
            openings.append({"loan": loan["loan_external_id"], "kind": "episode", "open_date": r["due_date"] + timedelta(days=1),
                             "first_unpaid": r["due_date"], "instalment_no": r["instalment_no"],
                             "branch": loan["branch"], "linked": loan["client_external_id"] in linked})
    openings.sort(key=lambda o: (o["open_date"], o["loan"]))

    positions: dict[str, int] = {}
    loans_by_id = {l["loan_external_id"]: l for l in world.loans}
    for o in openings:
        o["days_at_open"] = (o["open_date"] - o["first_unpaid"]).days
        o["bucket"] = _bucket(o["days_at_open"])
        o["stratum"] = stratum_key(o["bucket"], o["branch"])
        pos = positions.get(o["stratum"], 0)
        positions[o["stratum"]] = pos + 1
        o["arm"] = block_layout(world.tenant["id"], o["stratum"], pos // ctrl.block_size, ctrl.share,
                                ctrl.block_size)[pos % ctrl.block_size]
        if o["kind"] != "episode":
            o["cure_date"] = None
            continue
        if o.get("deep"):
            p, base, mean_days = DEEP_CURE[o["arm"]]
            days = base + int(rng.expovariate(1 / mean_days))
        else:
            p, mean_days = CURE[(o["arm"], o["linked"])] if o["arm"] == "treatment" else CURE[("control", None)]
            days = 2 + int(rng.expovariate(1 / mean_days))
        cure = o["first_unpaid"] + timedelta(days=days)
        loan = loans_by_id[o["loan"]]
        rows = sched[o["loan"]]
        if rng.random() < p and cure < as_of:
            o["cure_date"] = cure
            for r in rows:
                if r["instalment_no"] >= o["instalment_no"] and r["due_date"] <= cure and r["paid_on"] \
                        and r["paid_on"] < cure:
                    r["paid_on"] = cure
        else:
            # Never cured: the loan is overdue in today's export.
            o["cure_date"] = None
            o["kind"] = "episode_uncured"
            for r in rows:
                if r["instalment_no"] >= o["instalment_no"] and r["due_date"] < as_of:
                    r["paid_amount"], r["paid_on"] = 0, None
        loan.update(loan_state(loan, rows, as_of))
    world.history = {"t0": t0, "openings": openings}
