"""PDFs on the lender's letterhead. Noto Sans Myanmar and Khmer are embedded
(SIL Open Font License) so local script renders on any machine."""
from html import escape
from pathlib import Path

from app.models import Tenant
from app.money import fmt

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def base_css(tenant: Tenant) -> str:
    primary = tenant.brand.get("colors", {}).get("primary", "#2F3E46")
    faces = "".join(
        f"@font-face {{ font-family: '{fam}'; src: url('file://{FONTS / f'{file}.ttf'}'); font-weight: {w}; }}"
        for fam, file, w in [
            ("Noto Sans Myanmar", "NotoSansMyanmar-Regular", 400), ("Noto Sans Myanmar", "NotoSansMyanmar-Bold", 700),
            ("Noto Sans Khmer", "NotoSansKhmer-Regular", 400), ("Noto Sans Khmer", "NotoSansKhmer-Bold", 700),
        ]
    )
    return f"""
    {faces}
    @page {{ size: A4; margin: 14mm 14mm 16mm 14mm;
             @bottom-left {{ content: element(footer); }} }}
    body {{ font-family: Inter, 'Noto Sans Myanmar', 'Noto Sans Khmer', sans-serif; font-size: 8.6pt;
            color: #2F3E46; }}
    .lh {{ display: flex; align-items: center; justify-content: space-between;
           border-bottom: 2px solid {primary}; padding-bottom: 6px; margin-bottom: 10px; }}
    .lh .mark {{ width: 26px; height: 26px; border-radius: 6px; background: {primary}; color: #fff;
                 font-weight: 700; font-size: 14pt; text-align: center; line-height: 26px; display: inline-block;
                 vertical-align: middle; margin-right: 8px; }}
    .lh .name {{ font-size: 12pt; font-weight: 700; vertical-align: middle; }}
    .lh .local {{ font-size: 8pt; color: #52796F; }}
    .lh .meta {{ text-align: right; font-size: 7.5pt; color: #354F52; }}
    h1 {{ font-size: 12pt; margin: 4px 0 6px; }}
    h2 {{ font-size: 9.5pt; margin: 10px 0 4px; color: #354F52; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; font-weight: 600; color: #52796F; border-bottom: 1px solid #CAD2C5; padding: 2px 4px;
          font-size: 7.5pt; }}
    td {{ border-bottom: 1px solid #E6EAE3; padding: 2px 4px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .tiles {{ display: flex; gap: 6px; }}
    .tile {{ flex: 1; border: 1px solid #CAD2C5; border-radius: 4px; padding: 5px 7px; }}
    .tile .v {{ font-size: 12pt; font-weight: 700; }}
    .tile .l {{ font-size: 7pt; color: #52796F; }}
    .sample {{ background: #F3E9D2; color: #7A5A1E; padding: 3px 6px; border-radius: 3px; font-size: 7.5pt;
               font-weight: 600; display: inline-block; }}
    .footer {{ position: running(footer); font-size: 6.5pt; color: #84A98C; }}
    """


def letterhead(tenant: Tenant, title_right: str) -> str:
    b = tenant.brand
    return f"""
    <div class="lh">
      <div><span class="mark">{escape(b.get('logo_text', b.get('lender_name', '?')[:1]))}</span>
           <span class="name">{escape(b.get('lender_name', tenant.name))}</span>
           <div class="local">{escape(b.get('lender_name_local') or '')}</div></div>
      <div class="meta">{title_right}</div>
    </div>"""


def render(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def health_check_pdf(tenant: Tenant, hc: dict) -> bytes:
    rep = hc["reporting_currency"]
    s = hc["summary"]
    sample = '<span class="sample">SAMPLE DATA</span>' if tenant.is_demo else ""
    fx_note = ""
    if hc["fx"]:
        fx_note = " Converted to " + rep + " at " + ", ".join(f"{v:,} {k}/{rep}" for k, v in hc["fx"].items()) + "."
    buckets = "".join(
        f"<tr><td>{escape(b['label'])}</td><td class='num'>{b['loans']:,}</td>"
        f"<td class='num'>{fmt(b['amount_overdue'], rep) if b['key'] != 'pre_due' else 'due soon'}</td></tr>"
        for b in hc["buckets"])
    branches = "".join(
        f"<tr><td>{escape(r['name'])}</td><td class='num'>{r['loans']:,}</td><td class='num'>{fmt(r['outstanding'], rep)}</td>"
        f"<td class='num'>{_pct(r['par1'])}</td><td class='num'>{_pct(r['par30'])}</td>"
        f"<td class='num'>{_pct(r['par90'])}</td></tr>" for r in hc["par"]["by_branch"])
    visits = "".join(
        f"<tr><td class='num'>{v['rank']}</td><td>{escape(v['borrower'])}</td><td>{escape(v['village'] or '')}</td>"
        f"<td>{escape(v['officer'] or '')}</td><td class='num'>{v['days_overdue']}</td>"
        f"<td class='num'>{fmt(v['amount_overdue'], v['currency'])}</td>"
        f"<td>{escape('; '.join(v['reasons'][:2]))}</td></tr>" for v in hc["visit_list"][:12])
    n_unposted = sum(1 for u in hc["unposted"] if u["kind"] == "repayment_after_arrears_run")
    n_savings = sum(1 for u in hc["unposted"] if u["kind"] == "savings_cover_arrears")
    html = f"""<html><head><meta charset="utf-8"><style>{base_css(tenant)}</style></head><body>
    {letterhead(tenant, f"Portfolio health check<br>Book as of {hc['as_of']}")}
    <div class="footer">Prepared with Tenpai for {escape(tenant.brand.get('lender_name', tenant.name))}.
      PARn = principal of loans more than n days overdue / total principal outstanding. Amounts in {rep}.{fx_note}</div>
    <h1>How bad is the book today? {sample}</h1>
    <div class="tiles">
      <div class="tile"><div class="v">{_pct(s['par30'])}</div><div class="l">PAR30</div></div>
      <div class="tile"><div class="v">{_pct(s['par1'])}</div><div class="l">PAR1</div></div>
      <div class="tile"><div class="v">{_pct(s['par90'])}</div><div class="l">PAR90</div></div>
      <div class="tile"><div class="v">{s['overdue_loans']:,}</div><div class="l">Overdue loans of {s['active_loans']:,}</div></div>
      <div class="tile"><div class="v">{fmt(s['amount_overdue'], rep)}</div><div class="l">Amount overdue</div></div>
      <div class="tile"><div class="v">{_pct(s['telegram_link_rate_overdue'])}</div><div class="l">Overdue borrowers on Telegram</div></div>
    </div>
    <div style="display:flex; gap:14px">
      <div style="flex:1"><h2>Overdue by bucket</h2><table>
        <tr><th>Bucket</th><th class="num">Loans</th><th class="num">Amount overdue</th></tr>{buckets}</table></div>
      <div style="flex:1.6"><h2>PAR by branch</h2><table>
        <tr><th>Branch</th><th class="num">Loans</th><th class="num">Outstanding</th><th class="num">PAR1</th>
        <th class="num">PAR30</th><th class="num">PAR90</th></tr>{branches}</table></div>
    </div>
    <h2>Check before chasing</h2>
    <p>{n_unposted} loans show a repayment after the arrears calculation date: their arrears may already be paid.
       {n_savings} more have savings balances that cover the full arrears.</p>
    <h2>Top of the visit list (full list of 50 in the download)</h2>
    <table><tr><th class="num">#</th><th>Borrower</th><th>Village / ward</th><th>Officer</th>
      <th class="num">Days</th><th class="num">Overdue</th><th>Why</th></tr>{visits}</table>
    </body></html>"""
    return render(html)
