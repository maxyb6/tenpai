"""Seed templates: English, plus draft Burmese and Khmer.

Every local-script template is seeded with needs_native_review=True. The
console shows "Draft, needs native review" until a reviewer clears it in
Settings. Approval of content (status=approved) is the lender's sign-off on
what the message says, based on the English shadow.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.events import EventType, emit
from app.models import Template, Tenant

# key -> (category, variables)
# Transactional templates answer something the borrower just did.
CATALOGUE = {
    "pre_due_reminder": ("collections", ["borrower_name", "lender_name", "amount_due", "due_date", "pay_link"]),
    "due_day_reminder": ("collections", ["borrower_name", "lender_name", "amount_due", "pay_link"]),
    "late_3_days": ("collections", ["borrower_name", "amount_due", "days_overdue", "pay_link"]),
    "late_7_days": ("collections", ["borrower_name", "lender_name", "amount_due", "days_overdue", "pay_link"]),
    "promise_confirmation": ("transactional", ["borrower_name", "promise_amount", "promise_date", "pay_link"]),
    "promise_reminder": ("collections", ["borrower_name", "promise_amount", "promise_date", "pay_link"]),
    "promise_broken": ("collections", ["borrower_name", "promise_amount", "promise_date", "pay_link"]),
    "plan_offer": ("collections", ["borrower_name", "lender_name", "pay_link"]),
    "plan_approved": ("transactional", ["borrower_name", "plan_instalment", "plan_end_date"]),
    "plan_pending_approval": ("transactional", ["borrower_name", "sla_hours"]),
    "payment_received": ("transactional", ["borrower_name", "payment_amount", "payment_date", "reference"]),
    "visit_notice": ("collections", ["borrower_name", "lender_name", "officer_name", "visit_date", "pay_link"]),
    "complaint_received": ("transactional", ["complaint_ref", "lender_name", "sla_hours"]),
    "opt_out_confirmation": ("transactional", ["lender_name", "lender_phone"]),
    "telegram_invite": ("invite", ["lender_name", "invite_link"]),
}

EN = {
    "pre_due_reminder": "Hello {borrower_name}, this is {lender_name}. Your instalment of {amount_due} is due on {due_date}. You can pay here: {pay_link}. Thank you.",
    "due_day_reminder": "Hello {borrower_name}, your instalment of {amount_due} to {lender_name} is due today. Pay in a few taps: {pay_link}",
    "late_3_days": "Hello {borrower_name}, our records show your instalment of {amount_due} is {days_overdue} days late. If you have already paid, thank you, please ignore this message. To pay, or to tell us about a problem: {pay_link}",
    "late_7_days": "Hello {borrower_name}, your payment of {amount_due} to {lender_name} is {days_overdue} days late. If you are having difficulty, we can help with a plan that fits your situation. Open: {pay_link}",
    "promise_confirmation": "Thank you, {borrower_name}. We have noted your plan to pay {promise_amount} by {promise_date}. Pay here when you are ready: {pay_link}",
    "promise_reminder": "Hello {borrower_name}, a reminder that you planned to pay {promise_amount} by {promise_date}. Pay here: {pay_link}",
    "promise_broken": "Hello {borrower_name}, we have not received the {promise_amount} you planned to pay by {promise_date}. If something has changed, tell us and we will look at options together: {pay_link}",
    "plan_offer": "Hello {borrower_name}, {lender_name} can offer you a repayment plan that fits what you can pay now. See your options: {pay_link}",
    "plan_approved": "Your new repayment plan is confirmed: {plan_instalment} per instalment, ending {plan_end_date}. Your agreement is attached. Thank you, {borrower_name}.",
    "plan_pending_approval": "Thank you, {borrower_name}. Your plan request has been sent to your branch for approval. We will reply within {sla_hours} hours.",
    "payment_received": "Thank you, {borrower_name}. We received your payment of {payment_amount} on {payment_date}. Reference: {reference}.",
    "visit_notice": "Hello {borrower_name}, your loan officer {officer_name} from {lender_name} will visit you on {visit_date} to talk about your loan. To pay or contact us before then: {pay_link}",
    "complaint_received": "We have received your complaint (reference {complaint_ref}). A manager from {lender_name} will contact you within {sla_hours} hours.",
    "opt_out_confirmation": "You will no longer receive messages from {lender_name} on Telegram. To contact us, call {lender_phone} or speak to your loan officer.",
    "telegram_invite": "{lender_name}: check your loan balance and pay on Telegram. Tap to connect: {invite_link}",
}

MY = {
    "pre_due_reminder": "မင်္ဂလာပါ {borrower_name}။ {lender_name} မှ ဆက်သွယ်ခြင်းဖြစ်ပါသည်။ သင်၏ အရစ်ကျငွေ {amount_due} ကို {due_date} တွင် ပေးသွင်းရန် ရှိပါသည်။ ဤနေရာတွင် ပေးချေနိုင်ပါသည် - {pay_link}။ ကျေးဇူးတင်ပါသည်။",
    "due_day_reminder": "မင်္ဂလာပါ {borrower_name}။ {lender_name} သို့ ပေးသွင်းရမည့် အရစ်ကျငွေ {amount_due} သည် ယနေ့ ပေးသွင်းရမည့်နေ့ ဖြစ်ပါသည်။ ဤနေရာတွင် လွယ်ကူစွာ ပေးချေနိုင်ပါသည် - {pay_link}",
    "late_3_days": "မင်္ဂလာပါ {borrower_name}။ သင်၏ အရစ်ကျငွေ {amount_due} သည် {days_overdue} ရက် နောက်ကျနေကြောင်း ကျွန်ုပ်တို့၏ မှတ်တမ်းတွင် တွေ့ရပါသည်။ ပေးချေပြီးပါက ကျေးဇူးတင်ပါသည်၊ ဤစာကို ထည့်သွင်းစဉ်းစားရန် မလိုပါ။ ပေးချေရန် သို့မဟုတ် အခက်အခဲရှိပါက ပြောပြရန် - {pay_link}",
    "late_7_days": "မင်္ဂလာပါ {borrower_name}။ {lender_name} သို့ ပေးသွင်းရမည့် {amount_due} သည် {days_overdue} ရက် နောက်ကျနေပါသည်။ အခက်အခဲရှိနေပါက သင့်အခြေအနေနှင့် ကိုက်ညီသော ပေးချေမှုအစီအစဉ်ဖြင့် ကူညီပေးနိုင်ပါသည်။ ဖွင့်ကြည့်ရန် - {pay_link}",
    "promise_confirmation": "ကျေးဇူးတင်ပါသည် {borrower_name}။ {promise_date} နောက်ဆုံးထား၍ {promise_amount} ပေးချေရန် စီစဉ်ထားသည်ကို မှတ်သားထားပါသည်။ အဆင်သင့်ဖြစ်သည့်အခါ ဤနေရာတွင် ပေးချေနိုင်ပါသည် - {pay_link}",
    "promise_reminder": "မင်္ဂလာပါ {borrower_name}။ {promise_date} နောက်ဆုံးထား၍ {promise_amount} ပေးချေရန် စီစဉ်ထားကြောင်း သတိပေးအပ်ပါသည်။ ပေးချေရန် - {pay_link}",
    "promise_broken": "မင်္ဂလာပါ {borrower_name}။ {promise_date} နောက်ဆုံးထား၍ ပေးချေရန် စီစဉ်ထားသော {promise_amount} ကို မရရှိသေးပါ။ အခြေအနေ ပြောင်းလဲသွားပါက ကျွန်ုပ်တို့ကို ပြောပြပါ၊ ရွေးချယ်စရာများကို အတူတကွ ကြည့်ပေးပါမည် - {pay_link}",
    "plan_offer": "မင်္ဂလာပါ {borrower_name}။ {lender_name} သည် သင် ယခု ပေးနိုင်သည့် ပမာဏနှင့် ကိုက်ညီသော ပေးချေမှုအစီအစဉ်ကို ကမ်းလှမ်းနိုင်ပါသည်။ ရွေးချယ်စရာများကို ကြည့်ရန် - {pay_link}",
    "plan_approved": "သင်၏ ပေးချေမှုအစီအစဉ်အသစ်ကို အတည်ပြုပြီးပါပြီ - တစ်ရစ်လျှင် {plan_instalment}၊ {plan_end_date} တွင် ပြီးဆုံးပါမည်။ သဘောတူစာချုပ်ကို ပူးတွဲပေးပို့ထားပါသည်။ ကျေးဇူးတင်ပါသည် {borrower_name}။",
    "plan_pending_approval": "ကျေးဇူးတင်ပါသည် {borrower_name}။ သင်၏ အစီအစဉ်တောင်းဆိုချက်ကို ခွဲရုံးသို့ အတည်ပြုရန် ပေးပို့ထားပါသည်။ {sla_hours} နာရီအတွင်း ပြန်လည်အကြောင်းကြားပါမည်။",
    "payment_received": "ကျေးဇူးတင်ပါသည် {borrower_name}။ {payment_date} တွင် သင်၏ ငွေပေးချေမှု {payment_amount} ကို လက်ခံရရှိပါသည်။ ရည်ညွှန်းနံပါတ် - {reference}။",
    "visit_notice": "မင်္ဂလာပါ {borrower_name}။ {lender_name} မှ သင်၏ ချေးငွေအရာရှိ {officer_name} သည် ချေးငွေအကြောင်း ဆွေးနွေးရန် {visit_date} တွင် လာရောက်တွေ့ဆုံပါမည်။ ထိုမတိုင်မီ ပေးချေရန် သို့မဟုတ် ဆက်သွယ်ရန် - {pay_link}",
    "complaint_received": "သင်၏ တိုင်ကြားချက်ကို လက်ခံရရှိပါသည် (ရည်ညွှန်းနံပါတ် {complaint_ref})။ {lender_name} မှ မန်နေဂျာတစ်ဦးသည် {sla_hours} နာရီအတွင်း သင့်ထံ ဆက်သွယ်ပါမည်။",
    "opt_out_confirmation": "{lender_name} ထံမှ Telegram တွင် စာများ ထပ်မံပေးပို့တော့မည် မဟုတ်ပါ။ ဆက်သွယ်လိုပါက {lender_phone} သို့ ဖုန်းခေါ်ဆိုပါ သို့မဟုတ် သင်၏ ချေးငွေအရာရှိနှင့် ပြောဆိုပါ။",
    "telegram_invite": "{lender_name} - ချေးငွေလက်ကျန် ကြည့်ရန်နှင့် ပေးချေရန် Telegram တွင် ချိတ်ဆက်ပါ - {invite_link}",
}

KM = {
    "pre_due_reminder": "សួស្តី {borrower_name}។ នេះជា {lender_name}។ ប្រាក់បង់រំលស់របស់អ្នកចំនួន {amount_due} ត្រូវបង់នៅថ្ងៃ {due_date}។ អ្នកអាចបង់នៅទីនេះ៖ {pay_link}។ សូមអរគុណ។",
    "due_day_reminder": "សួស្តី {borrower_name}។ ប្រាក់បង់រំលស់ចំនួន {amount_due} ទៅ {lender_name} ត្រូវបង់នៅថ្ងៃនេះ។ បង់បានយ៉ាងងាយ៖ {pay_link}",
    "late_3_days": "សួស្តី {borrower_name}។ កំណត់ត្រារបស់យើងបង្ហាញថា ប្រាក់បង់រំលស់ចំនួន {amount_due} យឺត {days_overdue} ថ្ងៃ។ ប្រសិនបើអ្នកបានបង់រួចហើយ សូមអរគុណ។ ដើម្បីបង់ ឬប្រាប់យើងអំពីបញ្ហា៖ {pay_link}",
    "late_7_days": "សួស្តី {borrower_name}។ ការបង់ប្រាក់ចំនួន {amount_due} ទៅ {lender_name} យឺត {days_overdue} ថ្ងៃហើយ។ ប្រសិនបើអ្នកមានការលំបាក យើងអាចជួយរៀបចំផែនការបង់ប្រាក់ដែលសមនឹងស្ថានភាពរបស់អ្នក។ បើកមើល៖ {pay_link}",
    "promise_confirmation": "សូមអរគុណ {borrower_name}។ យើងបានកត់ត្រាថា អ្នកគ្រោងនឹងបង់ {promise_amount} មុនថ្ងៃ {promise_date}។ បង់នៅទីនេះពេលអ្នករួចរាល់៖ {pay_link}",
    "promise_reminder": "សួស្តី {borrower_name}។ សូមរំលឹកថា អ្នកគ្រោងនឹងបង់ {promise_amount} មុនថ្ងៃ {promise_date}។ បង់នៅទីនេះ៖ {pay_link}",
    "promise_broken": "សួស្តី {borrower_name}។ យើងមិនទាន់ទទួលបាន {promise_amount} ដែលអ្នកគ្រោងបង់មុនថ្ងៃ {promise_date} នៅឡើយទេ។ ប្រសិនបើស្ថានភាពបានផ្លាស់ប្តូរ សូមប្រាប់យើង ហើយយើងនឹងពិនិត្យជម្រើសជាមួយគ្នា៖ {pay_link}",
    "plan_offer": "សួស្តី {borrower_name}។ {lender_name} អាចផ្តល់ផែនការបង់ប្រាក់ដែលសមនឹងអ្វីដែលអ្នកអាចបង់បានឥឡូវនេះ។ មើលជម្រើសរបស់អ្នក៖ {pay_link}",
    "plan_approved": "ផែនការបង់ប្រាក់ថ្មីរបស់អ្នកត្រូវបានបញ្ជាក់៖ {plan_instalment} ក្នុងមួយលើក បញ្ចប់នៅថ្ងៃ {plan_end_date}។ កិច្ចព្រមព្រៀងត្រូវបានភ្ជាប់មកជាមួយ។ សូមអរគុណ {borrower_name}។",
    "plan_pending_approval": "សូមអរគុណ {borrower_name}។ សំណើផែនការរបស់អ្នកត្រូវបានផ្ញើទៅសាខាដើម្បីអនុម័ត។ យើងនឹងឆ្លើយតបក្នុងរយៈពេល {sla_hours} ម៉ោង។",
    "payment_received": "សូមអរគុណ {borrower_name}។ យើងបានទទួលការបង់ប្រាក់របស់អ្នកចំនួន {payment_amount} នៅថ្ងៃ {payment_date}។ លេខយោង៖ {reference}។",
    "visit_notice": "សួស្តី {borrower_name}។ មន្ត្រីឥណទានរបស់អ្នក {officer_name} មកពី {lender_name} នឹងមកជួបអ្នកនៅថ្ងៃ {visit_date} ដើម្បីពិភាក្សាអំពីប្រាក់កម្ចីរបស់អ្នក។ ដើម្បីបង់ ឬទាក់ទងយើងមុនពេលនោះ៖ {pay_link}",
    "complaint_received": "យើងបានទទួលពាក្យបណ្តឹងរបស់អ្នក (លេខយោង {complaint_ref})។ អ្នកគ្រប់គ្រងម្នាក់មកពី {lender_name} នឹងទាក់ទងអ្នកក្នុងរយៈពេល {sla_hours} ម៉ោង។",
    "opt_out_confirmation": "អ្នកនឹងមិនទទួលសារពី {lender_name} តាម Telegram ទៀតទេ។ ដើម្បីទាក់ទងយើង សូមហៅទៅ {lender_phone} ឬនិយាយជាមួយមន្ត្រីឥណទានរបស់អ្នក។",
    "telegram_invite": "{lender_name}៖ មើលសមតុល្យប្រាក់កម្ចី និងបង់ប្រាក់តាម Telegram។ ចុចដើម្បីភ្ជាប់៖ {invite_link}",
}

BUTTONS = {
    "en": {"pay": "Open my loan", "promise": "I will pay on...", "cant_pay": "I can't pay"},
    "my": {"pay": "ချေးငွေကြည့်ရန်", "promise": "ပေးမည့်ရက်", "cant_pay": "မပေးနိုင်ပါ"},
    "km": {"pay": "បើកប្រាក់កម្ចីខ្ញុំ", "promise": "ខ្ញុំនឹងបង់នៅ...", "cant_pay": "ខ្ញុំមិនអាចបង់បាន"},
}
WITH_BUTTONS = {"pre_due_reminder", "due_day_reminder", "late_3_days", "late_7_days", "promise_reminder",
                "promise_broken", "plan_offer", "visit_notice"}


def category(key: str) -> str:
    return CATALOGUE[key][0]


def _buttons(key: str, lang: str) -> list[dict]:
    if key not in WITH_BUTTONS:
        return []
    b = BUTTONS[lang]
    return [{"label": b["pay"], "action": "open_mini_app"}, {"label": b["promise"], "action": "promise"},
            {"label": b["cant_pay"], "action": "cant_pay"}]


def seed_templates(session: Session, tenant: Tenant, at: datetime, approver: str) -> int:
    local_lang, local = ("my", MY) if tenant.market == "MM" else ("km", KM)
    n = 0
    for key, (cat, variables) in CATALOGUE.items():
        channel = "sms" if cat == "invite" else "telegram"
        session.add(Template(tenant_id=tenant.id, key=key, language="en", version=1, channel=channel,
                             body=EN[key], english_shadow=EN[key], variables=variables,
                             buttons=_buttons(key, "en"), status="approved", needs_native_review=False,
                             approved_by=approver, approved_at=at, created_at=at))
        session.add(Template(tenant_id=tenant.id, key=key, language=local_lang, version=1, channel=channel,
                             body=local[key], english_shadow=EN[key], variables=variables,
                             buttons=_buttons(key, local_lang), status="approved", needs_native_review=True,
                             approved_by=approver, approved_at=at, created_at=at))
        n += 2
    session.flush()
    emit(session, tenant_id=tenant.id, type=EventType.template_changed, at=at, actor="system:seed",
         policy_version=tenant.current_policy_version,
         payload={"seeded": n, "note": "Local-script templates are drafts and need native review"})
    return n
