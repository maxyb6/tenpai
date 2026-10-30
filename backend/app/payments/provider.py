"""Payment providers. Tenpai never holds money: borrowers pay into the lender's
own account at the partner bank or wallet provider; Tenpai only issues the
request (reference, QR, deeplink) and reads the provider's notification."""
import base64
import io
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass
class PaymentIn:
    external_txn_id: str
    reference: str | None
    amount: int
    currency: str
    payer_phone: str | None
    paid_at: datetime
    raw: dict


class PaymentProvider(Protocol):
    name: str

    def create_request(self, *, tenant_id: str, loan_external_id: str, amount: int, currency: str,
                       now: datetime) -> dict: ...

    def parse_notification(self, payload: dict) -> PaymentIn: ...

    def import_statement(self, content: bytes, filename: str) -> list[PaymentIn]: ...


def qr_png_b64(payload: str) -> str:
    import qrcode

    img = qrcode.make(payload, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class MockProvider:
    """Demo provider. A unique reference per request, a QR image and a wallet
    deeplink. The demo panel's "simulate payment" posts a notification here."""

    name = "mock"

    def create_request(self, *, tenant_id, loan_external_id, amount, currency, now):
        reference = "TP" + secrets.token_hex(4).upper()
        payload = f"MOCKQR|{tenant_id}|{reference}|{amount}|{currency}"
        return {
            "reference": reference,
            "qr_payload": payload,
            "qr_png": qr_png_b64(payload),
            "deeplink": f"mockwallet://pay?ref={reference}&amount={amount}&ccy={currency}",
            "expires_at": now + timedelta(days=3),
        }

    def parse_notification(self, payload: dict) -> PaymentIn:
        return PaymentIn(
            external_txn_id=str(payload["txn_id"]), reference=payload.get("reference"),
            amount=int(payload["amount"]), currency=payload["currency"], payer_phone=payload.get("payer_phone"),
            paid_at=datetime.fromisoformat(payload["paid_at"]), raw=payload,
        )

    def import_statement(self, content: bytes, filename: str) -> list[PaymentIn]:
        import csv

        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        return [self.parse_notification(r) for r in rows]


class MMQRProvider(MockProvider):
    """TODO: MMQR via a licensed Myanmar bank or wallet partner. Needs the
    partner's merchant QR spec (EMVCo-based), callback signature scheme and
    settlement statement format."""

    name = "mmqr"


class KHQRProvider(MockProvider):
    """TODO: KHQR through a Bakong-connected partner bank. Needs the partner's
    KHQR merchant account, Bakong transaction status API access and the
    callback format."""

    name = "khqr"


PROVIDERS = {"mock": MockProvider(), "mmqr": MMQRProvider(), "khqr": KHQRProvider()}


def provider_for(name: str = "mock") -> PaymentProvider:
    return PROVIDERS.get(name, PROVIDERS["mock"])
