"""Money in minor units. MMK and KHR have no decimals; USD is cents."""

MINOR_DIGITS = {"MMK": 0, "KHR": 0, "USD": 2}
# Instalments are rounded to a sensible cash amount.
ROUND_TO = {"MMK": 100, "KHR": 100, "USD": 1}


def to_minor(amount: float | int | str, currency: str) -> int:
    return int(round(float(amount) * 10 ** MINOR_DIGITS[currency]))


def from_minor(amount: int, currency: str) -> float | int:
    digits = MINOR_DIGITS[currency]
    return amount if digits == 0 else amount / 10**digits


def round_cash(amount: float, currency: str) -> int:
    step = ROUND_TO[currency]
    return int(round(amount / step) * step)


def fmt(amount: int | None, currency: str) -> str:
    if amount is None:
        return ""
    if MINOR_DIGITS[currency] == 0:
        return f"{currency} {amount:,}"
    return f"{currency} {amount / 100:,.2f}"


def to_reporting(amount: int, currency: str, reporting: str, fx: dict) -> int:
    """fx holds units of `currency` per one unit of reporting currency, e.g. {"KHR": 4050}."""
    if currency == reporting:
        return amount
    major = from_minor(amount, currency) / fx[currency]
    return to_minor(major, reporting)
