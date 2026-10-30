"""Write a generated world as Mifos X style CSV exports.

Formatting follows Mifos conventions where they are known (dates as
"dd MMMM yyyy", amounts in major units). Header names are in
`ingest.canonical.MIFOS_*`; confirm against the lender's Mifos version.
"""
import csv
from datetime import date
from pathlib import Path

from app.ingest.canonical import MIFOS_LOANS, MIFOS_SAVINGS, MIFOS_SCHEDULE
from app.money import from_minor
from app.seed.generator import World

MONEY_LOAN = {
    "principal_disbursed", "instalment_amount", "principal_outstanding", "interest_outstanding",
    "principal_overdue", "interest_overdue", "penalty_overdue", "last_repayment_amount",
    "savings_balance", "household_income", "household_expenses", "other_debt_repayments",
}
MONEY_SCHEDULE = {"principal_due", "interest_due", "total_due", "paid_amount"}
MONEY_SAVINGS = {"amount", "balance_after"}
FREQ = {"monthly": "Monthly", "fortnightly": "Every 2 Weeks"}
GENDER = {"F": "Female", "M": "Male"}


def mifos_date(d: date | None) -> str:
    return d.strftime("%d %B %Y") if d else ""


def _money(value, currency: str) -> str:
    if value is None:
        return ""
    major = from_minor(value, currency)
    return f"{major:.2f}" if isinstance(major, float) else str(major)


def _cell(key, value, currency, money_keys):
    if value is None:
        return ""
    if key in money_keys:
        return _money(value, currency)
    if isinstance(value, date):
        return mifos_date(value)
    if key == "frequency":
        return FREQ[value]
    if key == "gender":
        return GENDER[value]
    return str(value)


def file_names(market: str) -> dict[str, str]:
    m = market.lower()
    return {
        "loans": f"mifos_loans_active_{m}.csv",
        "schedule": f"mifos_repayment_schedule_{m}.csv",
        "savings": f"mifos_savings_transactions_{m}.csv",
    }


def write(world: World, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: out_dir / v for k, v in file_names(world.market).items()}
    currency_by_loan = {r["loan_external_id"]: r["currency"] for r in world.loans}
    currency_by_savings = {r["savings_account_no"]: r["currency"] for r in world.loans}

    rows = list(world.loans)
    # Bad rows go in at fixed positions so the file reads like a real export.
    for i, bad in enumerate(world.bad_rows):
        rows.insert(min(len(rows), 40 + i * 397), bad)
    with paths["loans"].open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MIFOS_LOANS.values())
        for r in rows:
            w.writerow(_cell(k, r.get(k), r["currency"], MONEY_LOAN) for k in MIFOS_LOANS)

    with paths["schedule"].open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MIFOS_SCHEDULE.values())
        for r in world.schedule:
            cur = currency_by_loan[r["loan_external_id"]]
            w.writerow(_cell(k, r.get(k), cur, MONEY_SCHEDULE) for k in MIFOS_SCHEDULE)

    with paths["savings"].open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MIFOS_SAVINGS.values())
        for r in world.savings:
            cur = currency_by_savings[r["savings_account_no"]]
            txn = {**r, "txn_type": r["txn_type"].capitalize()}
            w.writerow(_cell(k, txn.get(k), cur, MONEY_SAVINGS) for k in MIFOS_SAVINGS)
    return paths


# A non-Mifos export: renamed columns, different order, dd/mm/yyyy dates.
OTHER_HEADERS = {
    "loan_external_id": "Acct No", "client_external_id": "Customer ID", "client_name": "Customer Name",
    "phone": "Contact No", "branch": "Branch Name", "officer": "Field Officer", "product": "Product Name",
    "currency": "CCY", "disbursed_on": "Date Disbursed", "principal_disbursed": "Loan Amount",
    "principal_outstanding": "OLP", "principal_overdue": "Overdue Principal", "interest_overdue": "Overdue Interest",
    "days_overdue": "DPD", "group_name": "Centre/Group", "village": "Ward/Village", "instalment_amount": "EMI",
    "frequency": "Freq", "savings_balance": "Compulsory Savings",
}


def write_other(world: World, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"other_core_banking_export_{world.market.lower()}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(OTHER_HEADERS.values())
        for r in world.loans:
            row = []
            for k in OTHER_HEADERS:
                v = r.get(k)
                if isinstance(v, date):
                    row.append(v.strftime("%d/%m/%Y"))
                else:
                    row.append(_cell(k, v, r["currency"], MONEY_LOAN))
            w.writerow(row)
    return path
