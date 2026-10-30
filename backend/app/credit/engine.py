"""Affordability. Uses the lender's credit engine when it is importable as
`engine` (put it at backend/engine/ or on PYTHONPATH); otherwise a stub:

    monthly_capacity = (household income - household expenses - other debt
                        repayments) x max share from policy

Inputs come from the loan appraisal in the import, updated by the borrower's
three Mini App answers, optionally confirmed by the officer.
"""
from dataclasses import dataclass


@dataclass
class CapacityInputs:
    household_income: int | None
    household_expenses: int | None
    other_debt_repayments: int | None
    source: str  # appraisal | borrower_answers | officer_confirmed
    income_changed: str | None = None  # less | more | same
    new_debt_repayments: int = 0


def capacity(borrower, inputs: CapacityInputs, max_share: float) -> dict:
    try:
        import engine  # type: ignore  # noqa: F401

        if hasattr(engine, "capacity"):
            out = engine.capacity(borrower, inputs)
            return {**out, "method": out.get("method", "engine")}
    except ImportError:
        pass
    if inputs.household_income is None:
        return {"monthly_capacity": None, "method": "stub: no income data", "inputs_used": inputs.__dict__}
    expenses = inputs.household_expenses or 0
    debt = (inputs.other_debt_repayments or 0) + (inputs.new_debt_repayments or 0)
    surplus = max(0, inputs.household_income - expenses - debt)
    return {
        "monthly_capacity": int(surplus * max_share),
        "method": f"stub: (income - expenses - debt) x {max_share:.0%}",
        "inputs_used": {**inputs.__dict__, "surplus": surplus, "max_share": max_share},
    }
