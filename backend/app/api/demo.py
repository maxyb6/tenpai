"""Demo panel: advance clock, trigger a borrower reply, simulate a payment,
reset the demo tenant. Demo tenants only."""
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app import clock
from app.api.deps import Ctx, ctx
from app.messaging import service as msg
from app.models import Borrower, Case, Loan, PaymentRequest
from app.payments import service as pay_svc
from app.payments.provider import provider_for
from app.services import daily

router = APIRouter(prefix="/api/t/{tenant_id}/demo")

REPLIES = {
    "my": [
        ("cant_pay", "ဒီတစ်ပတ် မပေးနိုင်သေးပါဘူး", "I can't pay this week"),
        ("will_pay", "နောက်တစ်ပတ် ပေးပါမယ်", "I will pay next week"),
        ("already_paid", "ပေးပြီးပြီ", "I already paid"),
        ("vulnerability", "အမေ ဆေးရုံတက်နေလို့ပါ", "My mother is in hospital"),
        ("vulnerability", "ရေကြီးလို့ ဆိုင်ပိတ်ထားရတယ်", "Flooding, I had to close my shop"),
        ("complaint", "ချေးငွေအရာရှိအကြောင်း တိုင်ကြားချင်ပါတယ်", "I want to make a complaint about the officer"),
        ("dispute", "ပမာဏမှားနေပါတယ်", "The amount is wrong"),
        ("stop", "စာမပို့ပါနဲ့", "Don't send messages"),
    ],
    "km": [
        ("cant_pay", "សប្តាហ៍នេះខ្ញុំមិនអាចបង់បានទេ", "I can't pay this week"),
        ("will_pay", "ខ្ញុំនឹងបង់សប្តាហ៍ក្រោយ", "I will pay next week"),
        ("already_paid", "ខ្ញុំបានបង់ហើយ", "I already paid"),
        ("vulnerability", "ម្តាយខ្ញុំសម្រាកនៅមន្ទីរពេទ្យ", "My mother is in hospital"),
        ("vulnerability", "ទឹកជំនន់ ខ្ញុំត្រូវបិទហាង", "Flooding, I had to close my shop"),
        ("complaint", "ខ្ញុំចង់ដាក់បណ្តឹងអំពីមន្ត្រី", "I want to make a complaint about the officer"),
        ("dispute", "ចំនួនខុស", "The amount is wrong"),
        ("stop", "ឈប់ផ្ញើសារ", "Stop sending messages"),
    ],
}


def _demo_only(c: Ctx):
    if not c.tenant.is_demo:
        raise HTTPException(403, "demo tenants only")


@router.get("/replies")
def replies(c: Ctx = Depends(ctx)):
    lang = "my" if c.tenant.market == "MM" else "km"
    return [{"label": l, "text": t, "en": e} for l, t, e in REPLIES[lang]]


@router.post("/advance")
def advance(c: Ctx = Depends(ctx), days: int = 1):
    _demo_only(c)
    out = []
    for _ in range(max(1, min(days, 14))):
        out.append(daily.advance_day(c.session, c.tenant, c.actor))
    return {"now": clock.local_now(c.tenant).isoformat(), "runs": out}


@router.post("/run-daily")
def run_daily(c: Ctx = Depends(ctx)):
    _demo_only(c)
    return daily.run(c.session, c.tenant, c.actor)


class SetTime(BaseModel):
    hh: int
    mm: int = 0


@router.post("/set-time")
def set_time(body: SetTime, c: Ctx = Depends(ctx)):
    """Move the clock within today, e.g. to 20:30 to show quiet hours blocking."""
    _demo_only(c)
    d = clock.today(c.tenant)
    c.tenant.demo_now = clock.local_datetime(c.tenant, d, body.hh, body.mm)
    return {"now": clock.local_now(c.tenant).isoformat()}


class ReplyBody(BaseModel):
    case_id: int
    text: str


@router.post("/reply")
def reply(body: ReplyBody, c: Ctx = Depends(ctx)):
    _demo_only(c)
    case = c.session.get(Case, body.case_id)
    if case is None or case.tenant_id != c.tenant.id:
        raise HTTPException(404)
    m = msg.receive_reply(c.session, c.tenant, c.session.get(Borrower, case.borrower_id), body.text)
    return {"message_id": m.id, "classification": m.classification, "detail": m.classification_detail}


class PayBody(BaseModel):
    case_id: int | None = None
    reference: str | None = None
    amount: int | None = None
    unmatched: bool = False


@router.post("/pay")
def simulate_payment(body: PayBody, c: Ctx = Depends(ctx)):
    """Posts a provider notification as the mock provider would."""
    _demo_only(c)
    s, t = c.session, c.tenant
    req = None
    if body.reference:
        req = s.scalars(select(PaymentRequest).where(PaymentRequest.reference == body.reference)).first()
    elif body.case_id:
        req = s.scalars(select(PaymentRequest).where(PaymentRequest.case_id == body.case_id,
                                                     PaymentRequest.status == "open")
                        .order_by(PaymentRequest.id.desc())).first()
        if req is None:
            case = s.get(Case, body.case_id)
            loan = s.get(Loan, case.loan_id)
            req, _ = pay_svc.create_request(s, t, loan, case, pay_svc.amount_due_now(s, loan), actor=c.actor)
    if req is None and not body.unmatched:
        raise HTTPException(400, "no payment request to pay")
    loan = s.get(Loan, req.loan_id) if req else None
    borrower = s.get(Borrower, loan.borrower_id) if loan else None
    payload = {
        "txn_id": "MOCK" + secrets.token_hex(5).upper(),
        "reference": None if body.unmatched else req.reference,
        "amount": body.amount or (req.amount if req else 50_000),
        "currency": req.currency if req else t.reporting_currency,
        "payer_phone": None if body.unmatched else (borrower.phone if borrower else None),
        "paid_at": clock.now(t).isoformat(),
    }
    p = pay_svc.receive(s, t, provider_for("mock").parse_notification(payload), provider="mock")
    return {"payment_id": p.id, "match_status": p.match_status, "kind": p.kind, "reference": p.reference}


@router.post("/reset")
def reset(c: Ctx = Depends(ctx), as_of: date | None = None):
    _demo_only(c)
    from app.seed.loader import seed_tenant

    market, as_of = c.tenant.market, as_of or clock.today(c.tenant)
    c.session.rollback()
    out = seed_tenant(c.session, market, as_of, write_sample=False)
    return {"ok": True, "tenant": out["tenant"], "as_of": out["as_of"]}
