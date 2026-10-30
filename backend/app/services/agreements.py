"""Plan agreement PDF in the borrower's language on the lender's letterhead,
with the English shadow for lender staff."""
from datetime import date
from html import escape

from sqlalchemy.orm import Session

from app.config import ROOT
from app.messaging import locale
from app.models import Borrower, Case, Loan, Plan, Tenant
from app.services.pdf import base_css, letterhead, render

AGREEMENTS_DIR = ROOT / "uploads" / "agreements"

TEXT = {
    "en": {
        "title": "Repayment plan agreement", "borrower": "Borrower", "loan": "Loan account",
        "plan": "Plan", "instalment": "Instalment", "end": "Final instalment", "total": "Total to pay",
        "schedule": "New schedule", "no": "No.", "due": "Due date", "amount": "Amount",
        "terms": "This plan replaces the remaining schedule of the loan above from the first date shown. "
                 "Other terms of your loan agreement stay the same. If you cannot pay an instalment, "
                 "contact us before the due date and we will look at options with you.",
        "sign_b": "Borrower", "sign_l": "For the lender",
        "types": {"catch_up": "Catch up", "reschedule": "Reschedule", "short_relief": "Short relief"},
    },
    "my": {
        "title": "ပြန်လည်ပေးချေမှု အစီအစဉ် သဘောတူစာချုပ်", "borrower": "ချေးငွေရယူသူ", "loan": "ချေးငွေအကောင့်",
        "plan": "အစီအစဉ်", "instalment": "အရစ်ကျငွေ", "end": "နောက်ဆုံးအရစ်", "total": "စုစုပေါင်း ပေးချေရမည့်ငွေ",
        "schedule": "ပေးချေမှုဇယား အသစ်", "no": "စဉ်", "due": "ပေးသွင်းရမည့်ရက်", "amount": "ပမာဏ",
        "terms": "ဤအစီအစဉ်သည် အထက်ပါ ချေးငွေ၏ ကျန်ရှိသော ပေးချေမှုဇယားကို ပထမရက်စွဲမှစ၍ အစားထိုးပါသည်။ "
                 "ချေးငွေသဘောတူစာချုပ်၏ အခြားစည်းကမ်းချက်များ မပြောင်းလဲပါ။ အရစ်ကျငွေ မပေးနိုင်ပါက "
                 "ပေးသွင်းရမည့်ရက်မတိုင်မီ ဆက်သွယ်ပါ၊ ရွေးချယ်စရာများကို အတူတကွ ကြည့်ပေးပါမည်။",
        "sign_b": "ချေးငွေရယူသူ", "sign_l": "ချေးငွေပေးသူကိုယ်စား",
        "types": {"catch_up": "ကျန်ငွေ ခွဲပေးခြင်း", "reschedule": "ပေးချေမှုကာလ တိုးခြင်း",
                  "short_relief": "ခေတ္တ သက်သာခွင့်"},
    },
    "km": {
        "title": "កិច្ចព្រមព្រៀងផែនការបង់ប្រាក់", "borrower": "អ្នកខ្ចី", "loan": "គណនីប្រាក់កម្ចី",
        "plan": "ផែនការ", "instalment": "ប្រាក់បង់មួយលើក", "end": "ការបង់ចុងក្រោយ", "total": "សរុបត្រូវបង់",
        "schedule": "តារាងបង់ប្រាក់ថ្មី", "no": "ល.រ", "due": "ថ្ងៃត្រូវបង់", "amount": "ចំនួន",
        "terms": "ផែនការនេះជំនួសតារាងបង់ប្រាក់ដែលនៅសល់នៃប្រាក់កម្ចីខាងលើ ចាប់ពីកាលបរិច្ឆេទដំបូង។ "
                 "លក្ខខណ្ឌផ្សេងទៀតនៃកិច្ចសន្យាប្រាក់កម្ចីរបស់អ្នកនៅដដែល។ ប្រសិនបើអ្នកមិនអាចបង់បាន "
                 "សូមទាក់ទងយើងមុនថ្ងៃត្រូវបង់ ហើយយើងនឹងពិនិត្យជម្រើសជាមួយអ្នក។",
        "sign_b": "អ្នកខ្ចី", "sign_l": "តំណាងអ្នកឱ្យខ្ចី",
        "types": {"catch_up": "បង់តាមទាន់", "reschedule": "ពន្យារពេលបង់", "short_relief": "សម្រាលបណ្តោះអាសន្ន"},
    },
}


def _section(t: dict, lang: str, borrower: Borrower, loan: Loan, plan: Plan) -> str:
    d = plan.details
    name = (borrower.name_local or borrower.name) if lang != "en" else borrower.name
    rows = "".join(
        f"<tr><td class='num'>{locale.number(p['no'], lang)}</td>"
        f"<td>{locale.day(date.fromisoformat(p['due_date']), lang)}</td>"
        f"<td class='num'>{locale.money(p['amount'], loan.currency, lang)}</td></tr>" for p in d["periods"])
    return f"""
    <h1>{t['title']}</h1>
    <table style="width:auto; margin-bottom:6px">
      <tr><td>{t['borrower']}</td><td><b>{escape(name)}</b></td></tr>
      <tr><td>{t['loan']}</td><td>{escape(loan.external_id)}</td></tr>
      <tr><td>{t['plan']}</td><td>{t['types'][plan.option_type]}</td></tr>
      <tr><td>{t['instalment']}</td><td>{locale.money(d['new_instalment'], loan.currency, lang)}</td></tr>
      <tr><td>{t['end']}</td><td>{locale.day(date.fromisoformat(d['new_end_date']), lang)}</td></tr>
      <tr><td>{t['total']}</td><td>{locale.money(d['total_payable'], loan.currency, lang)}</td></tr>
    </table>
    <p>{t['terms']}</p>
    <h2>{t['schedule']}</h2>
    <table><tr><th class="num">{t['no']}</th><th>{t['due']}</th><th class="num">{t['amount']}</th></tr>{rows}</table>
    <div style="display:flex; gap:40px; margin-top:28px">
      <div style="flex:1; border-top:1px solid #2F3E46; padding-top:3px">{t['sign_b']}</div>
      <div style="flex:1; border-top:1px solid #2F3E46; padding-top:3px">{t['sign_l']}</div>
    </div>"""


def generate(session: Session, tenant: Tenant, plan: Plan) -> str:
    case = session.get(Case, plan.case_id)
    loan = session.get(Loan, plan.loan_id)
    borrower = session.get(Borrower, case.borrower_id)
    lang = borrower.language if borrower.language in TEXT else "en"
    sample = '<p><span class="sample">SAMPLE DATA</span></p>' if tenant.is_demo else ""
    html = f"""<html><head><meta charset="utf-8"><style>{base_css(tenant)}
      .shadow {{ page-break-before: always; }} .shadow h1::after {{ content: ' (English copy for lender staff)';
      font-size: 8pt; color: #52796F; }}</style></head><body>
      {letterhead(tenant, f"Plan #{plan.id}<br>{plan.accepted_at.date().isoformat() if plan.accepted_at else ''}")}
      {sample}{_section(TEXT[lang], lang, borrower, loan, plan)}
      {'' if lang == 'en' else '<div class="shadow">' + _section(TEXT['en'], 'en', borrower, loan, plan) + '</div>'}
    </body></html>"""
    AGREEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = AGREEMENTS_DIR / f"{tenant.id}-plan-{plan.id}.pdf"
    path.write_bytes(render(html))
    return str(path.relative_to(ROOT))
