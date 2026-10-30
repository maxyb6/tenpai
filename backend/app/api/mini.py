"""Borrower-facing Mini App API. Only the lender's brand appears in anything
returned here. Every request is authorised by a signed per-borrower token."""
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.domain import plans as plans_mod
from app.domain.ranking import score_open_cases
from app.messaging import links, locale
from app.messaging import service as msg
from app.models import Borrower, Case, Loan, Message, PaymentRequest, Plan, Promise, Tenant
from app.payments import service as pay_svc
from app.payments.provider import qr_png_b64
from app.services import cases as case_svc

router = APIRouter(prefix="/api/mini/{token}")

CHARTER = {
    "en": [
        ("How we contact you", "Through our Telegram account and your loan officer. Only you, never your family, "
                               "neighbours or group, unless you agree."),
        ("When we won't", "Not before 8am or after 7pm, not on Sundays or public holidays, and no more than once "
                          "a day or three times a week."),
        ("Your right to a plan", "If you cannot pay, you can ask for a plan that fits what you can afford. "
                                 "We will look at it fairly."),
        ("How to complain", "Tap 'Make a complaint' below or type 'complaint' in the chat. A manager will reply "
                            "within 48 hours."),
    ],
    "my": [
        ("ကျွန်ုပ်တို့ ဆက်သွယ်ပုံ", "ကျွန်ုပ်တို့၏ Telegram အကောင့်နှင့် သင်၏ ချေးငွေအရာရှိမှတစ်ဆင့်သာ ဖြစ်ပါသည်။ သင်သဘောမတူဘဲ "
                                    "သင်၏ မိသားစု၊ အိမ်နီးချင်း သို့မဟုတ် အဖွဲ့ဝင်များကို ဆက်သွယ်မည်မဟုတ်ပါ။"),
        ("ဆက်သွယ်မည်မဟုတ်သည့်အချိန်", "နံနက် ၈ နာရီမတိုင်မီ၊ ညနေ ၇ နာရီနောက်ပိုင်း၊ တနင်္ဂနွေနေ့နှင့် ရုံးပိတ်ရက်များတွင် "
                                         "ဆက်သွယ်မည်မဟုတ်ပါ။ တစ်နေ့ တစ်ကြိမ်ထက်၊ တစ်ပတ် သုံးကြိမ်ထက် ပိုမည်မဟုတ်ပါ။"),
        ("အစီအစဉ် တောင်းဆိုခွင့်", "မပေးနိုင်ပါက သင်တတ်နိုင်သည့် အစီအစဉ်ကို တောင်းဆိုနိုင်ပါသည်။ မျှတစွာ စဉ်းစားပေးပါမည်။"),
        ("တိုင်ကြားနည်း", "အောက်ပါ 'တိုင်ကြားရန်' ကို နှိပ်ပါ သို့မဟုတ် chat တွင် 'တိုင်ကြား' ဟု ရိုက်ပါ။ မန်နေဂျာတစ်ဦးက "
                          "၄၈ နာရီအတွင်း ပြန်ကြားပါမည်။"),
    ],
    "km": [
        ("របៀបដែលយើងទាក់ទងអ្នក", "តាមរយៈគណនី Telegram របស់យើង និងមន្ត្រីឥណទានរបស់អ្នក។ មានតែអ្នកប៉ុណ្ណោះ "
                                "មិនមែនគ្រួសារ អ្នកជិតខាង ឬក្រុមរបស់អ្នកទេ លុះត្រាតែអ្នកយល់ព្រម។"),
        ("ពេលដែលយើងមិនទាក់ទង", "មិនមុនម៉ោង ៨ ព្រឹក ឬក្រោយម៉ោង ៧ ល្ងាច មិនថ្ងៃអាទិត្យ ឬថ្ងៃបុណ្យ "
                               "ហើយមិនលើសពីម្តងក្នុងមួយថ្ងៃ ឬបីដងក្នុងមួយសប្តាហ៍។"),
        ("សិទ្ធិស្នើសុំផែនការ", "ប្រសិនបើអ្នកមិនអាចបង់បាន អ្នកអាចស្នើសុំផែនការដែលសមនឹងលទ្ធភាពរបស់អ្នក។"),
        ("របៀបដាក់ពាក្យបណ្តឹង", "ចុច 'ដាក់ពាក្យបណ្តឹង' ខាងក្រោម ឬវាយ 'បណ្តឹង' ក្នុង chat។ "
                               "អ្នកគ្រប់គ្រងនឹងឆ្លើយតបក្នុងរយៈពេល ៤៨ ម៉ោង។"),
    ],
}


def _open(token: str):
    try:
        tenant_id, borrower_id, case_id = links.read_token(token)
    except ValueError as e:
        raise HTTPException(403, str(e))
    s = SessionLocal()
    tenant = s.get(Tenant, tenant_id)
    borrower = s.get(Borrower, borrower_id)
    if tenant is None or borrower is None or borrower.tenant_id != tenant.id:
        s.close()
        raise HTTPException(404)
    case = s.get(Case, case_id) if case_id else None
    if case is None or case.status != "open":
        case = s.scalars(select(Case).where(Case.borrower_id == borrower.id, Case.status == "open")).first() or case
    return s, tenant, borrower, case


def _loan(s, borrower, case):
    if case:
        return s.get(Loan, case.loan_id)
    return s.scalars(select(Loan).where(Loan.borrower_id == borrower.id, Loan.status == "active")).first()


def _money(amount, currency, lang):
    return {"value": amount, "text": locale.money(amount, currency, lang), "en": locale.money(amount, currency, "en")}


def _plan_view(p: Plan, lang: str) -> dict:
    d, cur = p.details, p.details["currency"]
    return {
        "id": p.id, "type": p.option_type, "status": p.status, "within_policy": p.within_policy,
        "instalment": _money(d["new_instalment"], cur, lang),
        "relief": _money(d["relief_instalment"], cur, lang) if d.get("relief_instalment") else None,
        "relief_periods": d["relief_periods"], "instalments": d["instalments"],
        "end_date": {"value": d["new_end_date"], "text": locale.day(date.fromisoformat(d["new_end_date"]), lang)},
        "total": _money(d["total_payable"], cur, lang), "frequency": d["frequency"],
    }


def _state(s, tenant, borrower, case, lang):
    loan = _loan(s, borrower, case)
    arrears = pay_svc.outstanding_arrears(s, loan) if loan else 0
    plans = []
    if case:
        plans = [p for p in s.scalars(select(Plan).where(Plan.case_id == case.id).order_by(Plan.id))
                 if p.status in ("offered", "pending_approval", "active", "approved")]
    offered = [p for p in plans if p.status == "offered" and p.details.get("affordable")]
    pending = next((p for p in plans if p.status == "pending_approval"), None)
    active = next((p for p in plans if p.status == "active"), None)
    promise = s.scalars(select(Promise).where(Promise.case_id == (case.id if case else -1), Promise.status == "open")
                        .order_by(Promise.id.desc())).first()
    brand = tenant.brand
    return {
        "lang": lang,
        "brand": {"name": brand.get("lender_name"), "name_local": brand.get("lender_name_local"),
                  "logo_text": brand.get("logo_text"), "colors": brand.get("colors"),
                  "phone": brand.get("lender_phone")},
        "sample": tenant.is_demo,
        "borrower": {"name": borrower.name_local or borrower.name, "name_en": borrower.name},
        "loan": {"external_id": loan.external_id, "currency": loan.currency,
                 "arrears": _money(arrears, loan.currency, lang),
                 "instalment": _money(loan.instalment_amount, loan.currency, lang),
                 "outstanding": _money(loan.principal_outstanding, loan.currency, lang),
                 "days_overdue": loan.days_overdue,
                 "next_due": {"value": loan.next_due_date and loan.next_due_date.isoformat(),
                              "text": locale.day(loan.next_due_date, lang)}} if loan else None,
        "promise": {"amount": _money(promise.amount, loan.currency, lang),
                    "date": locale.day(promise.due_date, lang)} if promise else None,
        "plans": [_plan_view(p, lang) for p in offered],
        "pending_plan": _plan_view(pending, lang) if pending else None,
        "active_plan": _plan_view(active, lang) if active else None,
        "charter": [{"title": a, "body": b} for a, b in CHARTER.get(lang, CHARTER["en"])],
        "charter_en": [{"title": a, "body": b} for a, b in CHARTER["en"]],
        "can_contact": case is not None and case.arm == "treatment",
    }


@router.get("")
def view(token: str, lang: str | None = None):
    s, tenant, borrower, case = _open(token)
    try:
        msg.mark_read(s, tenant, borrower.id, clock.now(tenant))
        out = _state(s, tenant, borrower, case, lang or borrower.language)
        s.commit()
        return out
    finally:
        s.close()


class PayBody(BaseModel):
    amount: int | None = None


@router.post("/pay")
def pay(token: str, body: PayBody):
    s, tenant, borrower, case = _open(token)
    try:
        loan = _loan(s, borrower, case)
        amount = body.amount or pay_svc.outstanding_arrears(s, loan) or loan.instalment_amount
        req, out = pay_svc.create_request(s, tenant, loan, case, amount, actor="borrower")
        s.commit()
        return {"reference": req.reference, "amount": _money(amount, loan.currency, borrower.language),
                "deeplink": req.deeplink, "qr_png": out["qr_png"], "expires_at": req.expires_at.isoformat()}
    finally:
        s.close()


class PromiseBody(BaseModel):
    amount: int
    due_date: date


@router.post("/promise")
def promise(token: str, body: PromiseBody):
    s, tenant, borrower, case = _open(token)
    try:
        if case is None:
            raise HTTPException(400, "nothing overdue")
        max_days = 14
        today = clock.today(tenant)
        if not today <= body.due_date <= date.fromordinal(today.toordinal() + max_days):
            raise HTTPException(400, f"date must be within {max_days} days")
        case_svc.record_promise(s, tenant, case, amount=body.amount, due=body.due_date, source="mini_app",
                                actor="borrower")
        score_open_cases(s, tenant, "borrower", case_ids=[case.id])
        out = _state(s, tenant, borrower, case, borrower.language)
        s.commit()
        return out
    finally:
        s.close()


class CantPayBody(BaseModel):
    income_changed: str  # less | more | same
    income_now: int | None = None
    new_debt_repayments: int | None = 0


@router.post("/cant-pay")
def cant_pay(token: str, body: CantPayBody):
    s, tenant, borrower, case = _open(token)
    try:
        if case is None:
            raise HTTPException(400, "nothing overdue")
        plans = plans_mod.generate_for_case(s, tenant, case, answers=body.model_dump(), actor="borrower")
        lang = borrower.language
        visible = [_plan_view(p, lang) for p in plans if p.details.get("affordable")]
        hidden = len(plans) - len(visible)
        if not visible:
            # Nothing fits what they can pay: a person takes over, not a machine.
            case_svc.assign_visit(s, tenant, case, actor="system", notify=False)
            case.next_action = "No affordable plan: officer to discuss"
        score_open_cases(s, tenant, "borrower", case_ids=[case.id])
        s.commit()
        return {"plans": visible, "hidden_above_capacity": hidden}
    finally:
        s.close()


@router.post("/plans/{plan_id}/accept")
def accept(token: str, plan_id: int):
    s, tenant, borrower, case = _open(token)
    try:
        plan = s.get(Plan, plan_id)
        if plan is None or case is None or plan.case_id != case.id or plan.status != "offered":
            raise HTTPException(404, "plan not available")
        if not plan.details.get("affordable"):
            raise HTTPException(400, "plan not available")
        result = case_svc.accept_plan(s, tenant, plan, actor="borrower")
        score_open_cases(s, tenant, "borrower", case_ids=[case.id])
        out = {"result": result, **_state(s, tenant, borrower, case, borrower.language)}
        s.commit()
        return out
    finally:
        s.close()


class TextBody(BaseModel):
    text: str


@router.post("/complaint")
def complaint(token: str, body: TextBody):
    s, tenant, borrower, case = _open(token)
    try:
        c = msg.open_complaint(s, tenant, borrower=borrower, case=case, text=body.text, source="mini_app",
                               at=clock.now(tenant), actor="borrower")
        s.commit()
        return {"reference": f"C-{c.id:05d}"}
    finally:
        s.close()


@router.post("/chat")
def chat(token: str, body: TextBody):
    """Simulated Telegram: the borrower types a reply to the lender's bot."""
    s, tenant, borrower, case = _open(token)
    try:
        m = msg.receive_reply(s, tenant, borrower, body.text)
        s.commit()
        return {"message_id": m.id, "classification": m.classification}
    finally:
        s.close()


@router.get("/chat")
def chat_log(token: str):
    s, tenant, borrower, case = _open(token)
    try:
        rows = s.scalars(select(Message).where(Message.borrower_id == borrower.id, Message.channel != "sms",
                                               Message.status.in_(("sent", "delivered", "read", "received")))
                         .order_by(Message.planned_at, Message.id))
        return {"brand": tenant.brand.get("bot_display_name"), "lang": borrower.language,
                "messages": [{"id": m.id, "direction": m.direction, "body": m.body, "shadow": m.body_shadow,
                              "at": (m.sent_at or m.planned_at).isoformat(), "status": m.status,
                              "buttons": _buttons(s, m)} for m in rows]}
    finally:
        s.close()


def _buttons(s, m: Message) -> list:
    if m.direction != "out" or not m.template_id:
        return []
    from app.models import Template

    t = s.get(Template, m.template_id)
    return t.buttons if t else []
