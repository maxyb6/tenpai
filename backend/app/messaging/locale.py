"""Borrower-facing formatting in local script."""
from datetime import date

from app.money import MINOR_DIGITS

MY_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")
KM_DIGITS = str.maketrans("0123456789", "០១២៣៤៥៦៧៨៩")


def money(amount: int, currency: str, lang: str) -> str:
    if MINOR_DIGITS[currency]:
        num = f"{amount / 100:,.2f}"
    else:
        num = f"{amount:,}"
    if lang == "my" and currency == "MMK":
        return f"{num.translate(MY_DIGITS)} ကျပ်"
    if lang == "km":
        if currency == "USD":
            return f"{num.translate(KM_DIGITS)} ដុល្លារ"
        if currency == "KHR":
            return f"{num.translate(KM_DIGITS)} រៀល"
    return f"{currency} {num}"


def day(d: date | None, lang: str) -> str:
    if d is None:
        return ""
    s = d.strftime("%d/%m/%Y")
    if lang == "my":
        return s.translate(MY_DIGITS)
    if lang == "km":
        return s.translate(KM_DIGITS)
    return d.strftime("%d %b %Y")


def number(n: int, lang: str) -> str:
    s = str(n)
    return s.translate(MY_DIGITS) if lang == "my" else s.translate(KM_DIGITS) if lang == "km" else s
