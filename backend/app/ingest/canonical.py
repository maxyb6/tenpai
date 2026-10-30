"""Canonical import fields. Any core banking export maps onto these through a
column mapping; the default mapping matches the Mifos X style export in
/sample_data. Amounts in files are major units (e.g. 12.50 USD); the importer
converts to minor units."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str  # str | int | money | date | float
    required: bool = False
    help: str = ""


LOAN_FIELDS: list[Field] = [
    Field("branch", "Branch / office", "str", True),
    Field("officer", "Loan officer", "str"),
    Field("client_external_id", "Client account no.", "str", True),
    Field("client_name", "Client name", "str", True),
    Field("client_name_local", "Client name (local script)", "str"),
    Field("gender", "Gender", "str"),
    Field("phone", "Mobile no.", "str", help="Missing phones are accepted but fall to the Visit segment"),
    Field("national_id", "National ID", "str"),
    Field("group_name", "Group name", "str", help="Blank for individual loans"),
    Field("village", "Village / ward", "str"),
    Field("loan_external_id", "Loan account no.", "str", True),
    Field("product", "Loan product", "str", True),
    Field("currency", "Currency", "str", True),
    Field("loan_cycle", "Loan cycle", "int"),
    Field("disbursed_on", "Disbursement date", "date", True),
    Field("principal_disbursed", "Principal disbursed", "money", True),
    Field("interest_rate_annual", "Annual interest rate (%)", "float"),
    Field("term_instalments", "Number of repayments", "int"),
    Field("frequency", "Repayment frequency", "str"),
    Field("instalment_amount", "Instalment amount", "money"),
    Field("principal_outstanding", "Principal outstanding", "money", True),
    Field("interest_outstanding", "Interest outstanding", "money"),
    Field("principal_overdue", "Principal overdue", "money", True),
    Field("interest_overdue", "Interest overdue", "money"),
    Field("penalty_overdue", "Penalty overdue", "money"),
    Field("days_overdue", "Days in arrears", "int", True),
    Field("arrears_as_of", "Arrears as of", "date", help="Date the core system calculated arrears"),
    Field("next_due_date", "Next due date", "date"),
    Field("last_repayment_date", "Last repayment date", "date"),
    Field("last_repayment_amount", "Last repayment amount", "money"),
    Field("savings_account_no", "Savings account no.", "str"),
    Field("savings_balance", "Savings balance", "money"),
    Field("household_income", "Household income (monthly, appraisal)", "money"),
    Field("household_expenses", "Household expenses (monthly, appraisal)", "money"),
    Field("other_debt_repayments", "Other debt repayments (monthly, appraisal)", "money"),
]

SCHEDULE_FIELDS: list[Field] = [
    Field("loan_external_id", "Loan account no.", "str", True),
    Field("instalment_no", "Installment", "int", True),
    Field("due_date", "Due date", "date", True),
    Field("principal_due", "Principal due", "money", True),
    Field("interest_due", "Interest due", "money", True),
    Field("total_due", "Total due", "money"),
    Field("paid_amount", "Total paid", "money"),
    Field("paid_on", "Paid date", "date", help="Date the instalment was fully paid"),
]

SAVINGS_FIELDS: list[Field] = [
    Field("savings_account_no", "Savings account no.", "str", True),
    Field("client_external_id", "Client account no.", "str"),
    Field("txn_date", "Transaction date", "date", True),
    Field("txn_type", "Transaction type", "str", True),
    Field("amount", "Amount", "money", True),
    Field("balance_after", "Running balance", "money"),
]

FIELDS_BY_KIND = {"loans": LOAN_FIELDS, "schedule": SCHEDULE_FIELDS, "savings": SAVINGS_FIELDS}

# Column headers in the Mifos X style export. Confirm against the lender's
# Mifos version and report definitions before the pilot.
MIFOS_LOANS = {
    "branch": "Office",
    "officer": "Loan Officer",
    "client_external_id": "Client Account No.",
    "client_name": "Client Name",
    "client_name_local": "Client Name (Local)",
    "gender": "Gender",
    "phone": "Mobile No.",
    "national_id": "National ID",
    "group_name": "Group Name",
    "village": "Village",
    "loan_external_id": "Loan Account No.",
    "product": "Loan Product",
    "currency": "Currency",
    "loan_cycle": "Loan Cycle",
    "disbursed_on": "Disbursement Date",
    "principal_disbursed": "Principal Disbursed",
    "interest_rate_annual": "Annual Interest Rate",
    "term_instalments": "Number of Repayments",
    "frequency": "Repayment Frequency",
    "instalment_amount": "Installment Amount",
    "principal_outstanding": "Principal Outstanding",
    "interest_outstanding": "Interest Outstanding",
    "principal_overdue": "Principal Overdue",
    "interest_overdue": "Interest Overdue",
    "penalty_overdue": "Penalty Overdue",
    "days_overdue": "Days in Arrears",
    "arrears_as_of": "Arrears As Of",
    "next_due_date": "Next Due Date",
    "last_repayment_date": "Last Repayment Date",
    "last_repayment_amount": "Last Repayment Amount",
    "savings_account_no": "Savings Account No.",
    "savings_balance": "Savings Balance",
    "household_income": "Household Income",
    "household_expenses": "Household Expenses",
    "other_debt_repayments": "Other Debt Repayments",
}
MIFOS_SCHEDULE = {
    "loan_external_id": "Loan Account No.",
    "instalment_no": "Installment",
    "due_date": "Due Date",
    "principal_due": "Principal Due",
    "interest_due": "Interest Due",
    "total_due": "Total Due",
    "paid_amount": "Total Paid",
    "paid_on": "Obligations Met On",
}
MIFOS_SAVINGS = {
    "savings_account_no": "Savings Account No.",
    "client_external_id": "Client Account No.",
    "txn_date": "Transaction Date",
    "txn_type": "Transaction Type",
    "amount": "Amount",
    "balance_after": "Running Balance",
}
DEFAULT_MAPPINGS = {"loans": MIFOS_LOANS, "schedule": MIFOS_SCHEDULE, "savings": MIFOS_SAVINGS}
