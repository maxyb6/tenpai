"""Portfolio health check. The free tier: must stand on its own after one import."""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.models import Borrower, Branch, Case, Loan, Officer, TelegramLink, Tenant
from app.money import to_reporting

PAR_THRESHOLDS = (0, 30, 90)  # PARn = principal of loans more than n days overdue / total principal


def health_check(session: Session, tenant: Tenant) -> dict:
    version, policy = policy_mod.current(session, tenant)
    today = clock.today(tenant)
    rep = tenant.reporting_currency
    loans = list(session.scalars(select(Loan).where(Loan.tenant_id == tenant.id, Loan.status == "active")))
    branches = {b.id: b for b in session.scalars(select(Branch).where(Branch.tenant_id == tenant.id))}
    officers = {o.id: o for o in session.scalars(select(Officer).where(Officer.tenant_id == tenant.id))}
    borrowers = {b.id: b for b in session.scalars(select(Borrower).where(Borrower.tenant_id == tenant.id))}
    linked = set(session.scalars(select(TelegramLink.borrower_id).where(
        TelegramLink.tenant_id == tenant.id, TelegramLink.status == "active")))

    def r(amount, cur):
        return to_reporting(amount, cur, rep, tenant.fx)

    buckets = {b.key: {"key": b.key, "label": b.label, "loans": 0, "amount_overdue": 0, "principal_outstanding": 0}
               for b in policy.buckets}
    par_groups = {"total": defaultdict(lambda: defaultdict(int)),
                  "branch": defaultdict(lambda: defaultdict(int)),
                  "officer": defaultdict(lambda: defaultdict(int))}
    total_outstanding = 0
    currencies = defaultdict(int)
    for loan in loans:
        out = r(loan.principal_outstanding, loan.currency)
        total_outstanding += out
        currencies[loan.currency] += 1
        days_to_due = (loan.next_due_date - today).days if loan.next_due_date else None
        key = policy_mod.bucket_for(policy, loan.days_overdue, days_to_due)
        if key:
            b = buckets[key]
            b["loans"] += 1
            b["amount_overdue"] += r(loan.amount_overdue, loan.currency)
            b["principal_outstanding"] += out
        for level, gid in (("total", "all"), ("branch", loan.branch_id), ("officer", loan.officer_id)):
            g = par_groups[level][gid]
            g["outstanding"] += out
            g["loans"] += 1
            for t in PAR_THRESHOLDS:
                if loan.days_overdue > t:
                    g[f"par{t or 1}"] += out
                    g[f"par{t or 1}_loans"] += 1

    def par_row(gid, g, name, extra=None):
        row = {"id": gid, "name": name, "loans": g["loans"], "outstanding": g["outstanding"], **(extra or {})}
        for t in PAR_THRESHOLDS:
            k = f"par{t or 1}"
            row[k] = round(g[k] / g["outstanding"], 4) if g["outstanding"] else 0.0
            row[f"{k}_amount"] = g[k]
            row[f"{k}_loans"] = g[f"{k}_loans"]
        return row

    par_total = par_row("all", par_groups["total"]["all"], "All branches")
    par_branch = sorted((par_row(i, g, branches[i].name) for i, g in par_groups["branch"].items()),
                        key=lambda x: -x["par30"])
    par_officer = sorted(
        (par_row(i, g, officers[i].name if i in officers else "Unassigned",
                 {"branch": branches[officers[i].branch_id].name if i in officers else None})
         for i, g in par_groups["officer"].items()),
        key=lambda x: -x["par30"])

    # Ranked visit list: open cases by priority, sensitive cases excluded (a manager owns them).
    cases = list(session.scalars(select(Case).where(Case.tenant_id == tenant.id, Case.status == "open",
                                                    Case.segment != "sensitive")
                                 .order_by(Case.priority.desc().nulls_last()).limit(50)))
    loan_by_id = {l.id: l for l in loans}
    visit_list = []
    for rank, c in enumerate(cases, start=1):
        loan, b = loan_by_id.get(c.loan_id), borrowers[c.borrower_id]
        if loan is None:
            continue
        visit_list.append({
            "rank": rank, "case_id": c.id, "borrower_id": b.id, "borrower": b.name, "borrower_local": b.name_local,
            "phone": b.phone, "village": b.village, "branch": branches[loan.branch_id].name,
            "officer": officers[loan.officer_id].name if loan.officer_id in officers else None,
            "loan": loan.external_id, "days_overdue": loan.days_overdue, "bucket": c.bucket,
            "amount_overdue": loan.amount_overdue, "currency": loan.currency, "priority": c.priority,
            "segment": c.segment, "telegram": b.id in linked,
            "reasons": [x["text"] for x in (c.reason_codes or []) if x["code"] != "days_overdue"][:3],
        })

    # Payments that appear unposted.
    unposted = []
    for loan in loans:
        if loan.amount_overdue <= 0:
            continue
        b = borrowers[loan.borrower_id]
        base = {"loan": loan.external_id, "loan_id": loan.id, "borrower": b.name, "borrower_id": b.id,
                "branch": branches[loan.branch_id].name, "amount_overdue": loan.amount_overdue,
                "currency": loan.currency, "days_overdue": loan.days_overdue}
        if loan.last_repayment_date and loan.arrears_as_of and loan.last_repayment_date > loan.arrears_as_of:
            unposted.append({**base, "kind": "repayment_after_arrears_run",
                             "detail": f"Repayment of {loan.last_repayment_amount or 0} on "
                                       f"{loan.last_repayment_date.isoformat()}, arrears calculated "
                                       f"{loan.arrears_as_of.isoformat()}",
                             "last_repayment_date": loan.last_repayment_date.isoformat(),
                             "last_repayment_amount": loan.last_repayment_amount,
                             "arrears_as_of": loan.arrears_as_of.isoformat()})
        elif loan.days_overdue > 7 and loan.savings_balance and loan.savings_balance >= loan.amount_overdue:
            unposted.append({**base, "kind": "savings_cover_arrears",
                             "detail": "Savings balance covers the full arrears",
                             "savings_balance": loan.savings_balance})

    overdue_loans = [l for l in loans if l.days_overdue > 0]
    overdue_linked = sum(1 for l in overdue_loans if l.borrower_id in linked)
    return {
        "as_of": today.isoformat(),
        "reporting_currency": rep,
        "fx": tenant.fx,
        "currencies": dict(currencies),
        "policy_version": version,
        "summary": {
            "active_loans": len(loans),
            "outstanding": total_outstanding,
            "overdue_loans": len(overdue_loans),
            "amount_overdue": sum(r(l.amount_overdue, l.currency) for l in overdue_loans),
            "par1": par_total["par1"], "par30": par_total["par30"], "par90": par_total["par90"],
            "telegram_link_rate_overdue": round(overdue_linked / len(overdue_loans), 4) if overdue_loans else 0,
            "telegram_link_rate_book": round(len(linked) / len(loans), 4) if loans else 0,
            "missing_phone": sum(1 for l in loans if not borrowers[l.borrower_id].phone),
        },
        "buckets": list(buckets.values()),
        "par": {"total": par_total, "by_branch": par_branch, "by_officer": par_officer},
        "visit_list": visit_list,
        "unposted": unposted,
        "unposted_total": sum(r(u["amount_overdue"], u["currency"]) for u in unposted
                              if u["kind"] == "repayment_after_arrears_run"),
    }


def visit_list_csv(hc: dict) -> str:
    import csv
    import io

    from app.money import from_minor

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Rank", "Borrower", "Borrower (local)", "Phone", "Village", "Branch", "Officer", "Loan",
                "Days overdue", "Amount overdue", "Currency", "Segment", "On Telegram", "Reasons"])
    for v in hc["visit_list"]:
        w.writerow([v["rank"], v["borrower"], v["borrower_local"] or "", v["phone"] or "", v["village"] or "",
                    v["branch"], v["officer"] or "", v["loan"], v["days_overdue"],
                    from_minor(v["amount_overdue"], v["currency"]), v["currency"], v["segment"],
                    "yes" if v["telegram"] else "no", "; ".join(v["reasons"])])
    return buf.getvalue()
