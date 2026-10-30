"""Import: read file -> map columns -> parse -> validate -> upsert -> refresh cases.

The same pipeline runs for the seed, the demo upload and a real lender file.
"""
import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.config import LINK_SIGNING_SECRET
from app.domain.control import assign_arm, stratum_key
from app.events import EventType, emit, emit_many
from app.ingest.canonical import FIELDS_BY_KIND, Field
from app.models import (
    Borrower,
    Branch,
    Case,
    Group,
    ImportBatch,
    Loan,
    Officer,
    SavingsSnapshot,
    SavingsTransaction,
    Schedule,
    Tenant,
)
from app.money import MINOR_DIGITS, to_minor

DATE_FORMATS = ["%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d.%m.%Y", "%m/%d/%Y"]
FREQ_ALIASES = {
    "monthly": "monthly", "months": "monthly", "month": "monthly", "1 month": "monthly",
    "every 2 weeks": "fortnightly", "fortnightly": "fortnightly", "biweekly": "fortnightly",
    "bi-weekly": "fortnightly", "2 weeks": "fortnightly",
}


# ---------------------------------------------------------------------------
# Reading and mapping


def read_table(content: bytes, filename: str) -> tuple[list[str], list[dict[str, str]]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(it)]
        rows = []
        for values in it:
            if values is None or all(v is None for v in values):
                continue
            rows.append({h: ("" if v is None else v) for h, v in zip(headers, values)})
        return headers, rows
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in reader.fieldnames or []]
    rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]
    return headers, rows


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


SYNONYMS = {
    "branch": ["office", "branchname", "officename"],
    "officer": ["loanofficer", "creditofficer", "fieldofficer", "staff"],
    "client_external_id": ["clientaccountno", "clientid", "customerid", "customerno", "memberid"],
    "client_name": ["clientname", "customername", "borrowername", "membername", "name"],
    "phone": ["mobileno", "mobile", "phone", "phoneno", "mobilenumber", "contactno"],
    "loan_external_id": ["loanaccountno", "loanid", "loanno", "accountno", "loanaccount"],
    "principal_outstanding": ["principaloutstanding", "outstandingprincipal", "olp", "balanceprincipal"],
    "principal_overdue": ["principaloverdue", "overdueprincipal", "principalarrears", "principalinarrears"],
    "interest_overdue": ["interestoverdue", "overdueinterest", "interestarrears"],
    "days_overdue": ["daysinarrears", "dpd", "daysoverdue", "daysPastDue".lower(), "arrearsdays"],
    "disbursed_on": ["disbursementdate", "disburseddate", "dateofdisbursement", "disbursedon"],
    "principal_disbursed": ["principaldisbursed", "loanamount", "disbursedamount", "amountdisbursed"],
    "currency": ["currency", "ccy", "currencycode"],
    "product": ["loanproduct", "product", "productname"],
}


def suggest_mapping(headers: list[str], kind: str, saved: list[dict] | None = None) -> dict[str, str | None]:
    """canonical field -> source header. Saved mappings that cover the file win,
    then exact header matches, then normalised label and synonym matches."""
    header_set = set(headers)
    for m in saved or []:
        required = [f.key for f in FIELDS_BY_KIND[kind] if f.required]
        if all(m.get(k) in header_set for k in required):
            return {f.key: m.get(f.key) if m.get(f.key) in header_set else None for f in FIELDS_BY_KIND[kind]}
    by_norm = {_norm(h): h for h in headers}
    from app.ingest.canonical import DEFAULT_MAPPINGS

    out: dict[str, str | None] = {}
    for f in FIELDS_BY_KIND[kind]:
        default = DEFAULT_MAPPINGS[kind].get(f.key)
        candidates = [default, f.label, f.key, *SYNONYMS.get(f.key, [])]
        hit = None
        for c in candidates:
            if c and c in header_set:
                hit = c
                break
            if c and _norm(c) in by_norm:
                hit = by_norm[_norm(c)]
                break
        out[f.key] = hit
    return out


class ParseError(ValueError):
    pass


def parse_date(raw) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"unrecognised date '{s}'")


def parse_value(f: Field, raw, currency: str | None):
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if f.kind == "str":
        return str(raw).strip()
    if f.kind == "date":
        return parse_date(raw)
    if f.kind == "int":
        try:
            return int(float(str(raw).replace(",", "")))
        except ValueError:
            raise ParseError(f"not a whole number '{raw}'")
    if f.kind == "float":
        try:
            return float(str(raw).replace(",", "").replace("%", ""))
        except ValueError:
            raise ParseError(f"not a number '{raw}'")
    if f.kind == "money":
        if currency not in MINOR_DIGITS:
            raise ParseError(f"unknown currency '{currency}'")
        try:
            return to_minor(str(raw).replace(",", ""), currency)
        except ValueError:
            raise ParseError(f"not an amount '{raw}'")
    raise AssertionError(f.kind)


@dataclass
class Report:
    rows: int = 0
    accepted: int = 0
    issues: list[dict] = field(default_factory=list)

    def add(self, row: int, code: str, severity: str, message: str, key: str | None = None):
        self.issues.append({"row": row, "code": code, "severity": severity, "message": message, "key": key})

    def as_dict(self) -> dict:
        counts: dict[str, int] = defaultdict(int)
        for i in self.issues:
            counts[i["code"]] += 1
        return {
            "rows": self.rows,
            "accepted": self.accepted,
            "rejected": len({i["row"] for i in self.issues if i["severity"] == "error"}),
            "counts": dict(counts),
            "issues": self.issues[:500],
        }


ISSUE_LABELS = {
    "missing_required": "Missing required value",
    "parse_error": "Value could not be read",
    "duplicate_loan_id": "Duplicate loan account number (first row kept)",
    "negative_balance": "Negative balance",
    "future_date": "Date after the export date",
    "missing_phone": "No mobile number (borrower falls to Visit)",
    "unknown_currency": "Unknown currency",
    "unknown_loan": "Loan not in the loans file",
}


def map_rows(rows, mapping, kind, report: Report, currency_for=None) -> list[tuple[int, dict]]:
    fields = FIELDS_BY_KIND[kind]
    out = []
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        rec: dict = {}
        currency = None
        if kind == "loans":
            col = mapping.get("currency")
            currency = (str(raw.get(col, "")).strip().upper() if col else "") or None
        elif currency_for:
            currency = currency_for(raw, mapping)
        ok = True
        for f in fields:
            col = mapping.get(f.key)
            value = raw.get(col) if col else None
            try:
                rec[f.key] = parse_value(f, value, currency)
            except ParseError as e:
                if "currency" in str(e):
                    report.add(i, "unknown_currency", "error", str(e), rec.get("loan_external_id"))
                else:
                    report.add(i, "parse_error", "error", f"{f.label}: {e}", rec.get("loan_external_id"))
                ok = False
                break
            if f.required and rec[f.key] is None:
                report.add(i, "missing_required", "error", f"{f.label} is empty", rec.get("loan_external_id"))
                ok = False
                break
        if ok:
            if kind == "loans":
                rec["currency"] = currency
            out.append((i, rec))
    return out


# ---------------------------------------------------------------------------
# Anonymisation


def _h(tenant_id: str, value: str) -> str:
    return hashlib.sha256(f"{LINK_SIGNING_SECRET}|{tenant_id}|{value}".encode()).hexdigest()


def anonymise_loan_row(tenant_id: str, rec: dict) -> dict:
    """Hashes names, phones and ID numbers; keeps everything else."""
    rec = dict(rec)
    if rec.get("client_name"):
        rec["client_name"] = "Client " + _h(tenant_id, rec["client_name"])[:8]
    rec["client_name_local"] = None
    if rec.get("phone"):
        rec["phone"] = "anon:" + _h(tenant_id, rec["phone"])[:12]
    if rec.get("national_id"):
        rec["national_id"] = "anon:" + _h(tenant_id, rec["national_id"])[:12]
    return rec


# ---------------------------------------------------------------------------
# Loans


def validate_loans(mapped: list[tuple[int, dict]], as_of: date, report: Report) -> list[dict]:
    seen: set[str] = set()
    accepted = []
    for row_no, rec in mapped:
        lid = rec["loan_external_id"]
        if lid in seen:
            report.add(row_no, "duplicate_loan_id", "error", f"{lid} appears more than once", lid)
            continue
        seen.add(lid)
        negatives = [k for k in ("principal_outstanding", "principal_overdue", "interest_overdue",
                                 "principal_disbursed", "savings_balance")
                     if rec.get(k) is not None and rec[k] < 0]
        if negatives:
            report.add(row_no, "negative_balance", "error", f"{', '.join(negatives)} below zero", lid)
            continue
        future = [k for k in ("disbursed_on", "last_repayment_date", "arrears_as_of")
                  if rec.get(k) and rec[k] > as_of]
        if future:
            report.add(row_no, "future_date", "error", f"{', '.join(future)} after {as_of.isoformat()}", lid)
            continue
        if not rec.get("phone"):
            report.add(row_no, "missing_phone", "warning", "no mobile number", lid)
        if rec.get("days_overdue") is not None and rec["days_overdue"] < 0:
            rec["days_overdue"] = 0
        accepted.append(rec)
    return accepted


def _normalise_frequency(value: str | None) -> str:
    if not value:
        return "monthly"
    return FREQ_ALIASES.get(value.strip().lower(), "monthly")


def _get_or_create(session, cache, model, tenant_id, name, **extra):
    key = (model.__name__, name)
    if key in cache:
        return cache[key]
    obj = session.scalar(select(model).where(model.tenant_id == tenant_id, model.name == name))
    if obj is None:
        obj = model(tenant_id=tenant_id, name=name, **extra)
        session.add(obj)
        session.flush()
    cache[key] = obj
    return obj


def upsert_loans(session: Session, tenant: Tenant, records: list[dict], batch: ImportBatch, at: datetime,
                 actor: str) -> dict:
    cache: dict = {}
    events = []
    stats = {"new": 0, "updated": 0, "unchanged": 0}
    existing_loans = {
        l.external_id: l for l in session.scalars(select(Loan).where(Loan.tenant_id == tenant.id))
    }
    existing_borrowers = {
        b.external_id: b for b in session.scalars(select(Borrower).where(Borrower.tenant_id == tenant.id))
    }
    language = "my" if tenant.market == "MM" else "km"
    for rec in records:
        branch = _get_or_create(session, cache, Branch, tenant.id, rec["branch"],
                                code=rec["branch"][:3].upper())
        officer = None
        if rec.get("officer"):
            officer = _get_or_create(session, cache, Officer, tenant.id, rec["officer"],
                                     branch_id=branch.id, code=_h(tenant.id, rec["officer"])[:6])
        group = None
        if rec.get("group_name"):
            group = _get_or_create(session, cache, Group, tenant.id, rec["group_name"], branch_id=branch.id,
                                   officer_id=officer.id if officer else None, village=rec.get("village"))

        b = existing_borrowers.get(rec["client_external_id"])
        if b is None:
            b = Borrower(tenant_id=tenant.id, external_id=rec["client_external_id"], language=language)
            session.add(b)
            existing_borrowers[b.external_id] = b
        b.name = rec["client_name"]
        b.name_local = rec.get("client_name_local")
        b.gender = (rec.get("gender") or "")[:1].upper() or None
        b.phone = rec.get("phone")
        b.national_id = rec.get("national_id")
        b.village = rec.get("village")
        b.branch_id = branch.id
        b.officer_id = officer.id if officer else None
        b.anonymised = batch.anonymised
        session.flush()

        loan = existing_loans.get(rec["loan_external_id"])
        is_new = loan is None
        if is_new:
            loan = Loan(tenant_id=tenant.id, external_id=rec["loan_external_id"])
            session.add(loan)
            existing_loans[loan.external_id] = loan
        before = None if is_new else (loan.days_overdue, loan.principal_outstanding, loan.principal_overdue,
                                      loan.interest_overdue)
        appraisal = None
        if rec.get("household_income") is not None:
            appraisal = {k: rec.get(k) for k in ("household_income", "household_expenses", "other_debt_repayments")}
        loan.borrower_id = b.id
        loan.group_id = group.id if group else None
        loan.branch_id = branch.id
        loan.officer_id = officer.id if officer else None
        loan.product = rec["product"]
        loan.loan_type = "group" if group else "individual"
        loan.currency = rec["currency"]
        loan.principal_disbursed = rec["principal_disbursed"]
        loan.disbursed_on = rec["disbursed_on"]
        loan.interest_rate_annual = rec.get("interest_rate_annual") or 0.0
        loan.term_instalments = rec.get("term_instalments") or 0
        loan.frequency = _normalise_frequency(rec.get("frequency"))
        loan.instalment_amount = rec.get("instalment_amount") or 0
        loan.loan_cycle = rec.get("loan_cycle") or 1
        loan.principal_outstanding = rec["principal_outstanding"]
        loan.interest_outstanding = rec.get("interest_outstanding") or 0
        loan.principal_overdue = rec["principal_overdue"]
        loan.interest_overdue = rec.get("interest_overdue") or 0
        loan.penalty_overdue = rec.get("penalty_overdue") or 0
        loan.days_overdue = rec["days_overdue"]
        loan.arrears_as_of = rec.get("arrears_as_of") or batch.as_of
        loan.next_due_date = rec.get("next_due_date")
        loan.last_repayment_date = rec.get("last_repayment_date")
        loan.last_repayment_amount = rec.get("last_repayment_amount")
        loan.savings_account_no = rec.get("savings_account_no")
        loan.savings_balance = rec.get("savings_balance")
        loan.appraisal = appraisal
        loan.status = "active"
        loan.import_batch_id = batch.id
        loan.raw = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in rec.items()}
        session.flush()

        after = (loan.days_overdue, loan.principal_outstanding, loan.principal_overdue, loan.interest_overdue)
        change = "new" if is_new else ("updated" if after != before else "unchanged")
        stats[change] += 1
        events.append({
            "tenant_id": tenant.id, "type": EventType.loan_imported, "at": at, "actor": actor,
            "loan_id": loan.id, "borrower_id": b.id, "policy_version": tenant.current_policy_version,
            "payload": {
                "batch_id": batch.id, "external_id": loan.external_id, "change": change,
                "days_overdue": loan.days_overdue, "principal_outstanding": loan.principal_outstanding,
                "amount_overdue": loan.amount_overdue, "currency": loan.currency,
            },
        })
    emit_many(session, events)
    return stats


# ---------------------------------------------------------------------------
# Schedules and savings


def upsert_schedule(session: Session, tenant: Tenant, records: list[dict], report: Report) -> int:
    loans = {l.external_id: l.id for l in session.scalars(select(Loan).where(Loan.tenant_id == tenant.id))}
    rows = []
    for rec in records:
        loan_id = loans.get(rec["loan_external_id"])
        if loan_id is None:
            report.add(0, "unknown_loan", "warning", rec["loan_external_id"], rec["loan_external_id"])
            continue
        total = rec.get("total_due")
        if total is None:
            total = rec["principal_due"] + rec["interest_due"]
        rows.append({
            "loan_id": loan_id, "version": 1, "instalment_no": rec["instalment_no"], "due_date": rec["due_date"],
            "principal_due": rec["principal_due"], "interest_due": rec["interest_due"], "total_due": total,
            "paid_amount": rec.get("paid_amount") or 0,
            "paid_on": rec.get("paid_on") if (rec.get("paid_amount") or 0) >= total else None,
        })
    for chunk in _chunks(rows, 2000):
        stmt = pg_insert(Schedule).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["loan_id", "version", "instalment_no"],
            set_={c: stmt.excluded[c] for c in ("due_date", "principal_due", "interest_due", "total_due",
                                                "paid_amount", "paid_on")},
        )
        session.execute(stmt)
    return len(rows)


def upsert_savings(session: Session, tenant: Tenant, records: list[dict], as_of: date) -> int:
    borrower_by_account = dict(session.execute(
        select(Loan.savings_account_no, Loan.borrower_id).where(
            Loan.tenant_id == tenant.id, Loan.savings_account_no.is_not(None))
    ).all())
    seq: dict[tuple, int] = defaultdict(int)
    rows = []
    for rec in records:
        txn_type = (rec["txn_type"] or "").strip().lower()
        txn_type = "withdrawal" if txn_type.startswith("with") else "deposit"
        k = (rec["savings_account_no"], rec["txn_date"], txn_type, rec["amount"])
        rows.append({
            "tenant_id": tenant.id, "borrower_id": borrower_by_account.get(rec["savings_account_no"]),
            "account_no": rec["savings_account_no"], "txn_date": rec["txn_date"], "txn_type": txn_type,
            "amount": rec["amount"], "balance_after": rec.get("balance_after"), "seq": seq[k],
        })
        seq[k] += 1
    for chunk in _chunks(rows, 2000):
        session.execute(pg_insert(SavingsTransaction).values(chunk).on_conflict_do_nothing())
    rebuild_savings_snapshots(session, tenant, as_of)
    return len(rows)


def rebuild_savings_snapshots(session: Session, tenant: Tenant, as_of: date, weeks: int = 26) -> None:
    """Weekly savings position per borrower, last `weeks` weeks (Monday starts)."""
    session.execute(delete(SavingsSnapshot).where(SavingsSnapshot.tenant_id == tenant.id))
    txns = session.execute(
        select(SavingsTransaction.borrower_id, SavingsTransaction.account_no, SavingsTransaction.txn_date,
               SavingsTransaction.txn_type, SavingsTransaction.amount)
        .where(SavingsTransaction.tenant_id == tenant.id, SavingsTransaction.borrower_id.is_not(None))
        .order_by(SavingsTransaction.borrower_id, SavingsTransaction.txn_date, SavingsTransaction.id)
    ).all()
    last_monday = as_of - timedelta(days=as_of.weekday())
    week_starts = [last_monday - timedelta(weeks=w) for w in range(weeks - 1, -1, -1)]
    by_borrower: dict[int, list] = defaultdict(list)
    accounts: dict[int, str] = {}
    for t in txns:
        by_borrower[t.borrower_id].append(t)
        accounts[t.borrower_id] = t.account_no
    rows = []
    for borrower_id, items in by_borrower.items():
        balance, idx = 0, 0
        for ws in week_starts:
            we = ws + timedelta(days=7)
            dep = wd = 0
            while idx < len(items) and items[idx].txn_date < we:
                t = items[idx]
                if t.txn_type == "deposit":
                    balance += t.amount
                    if t.txn_date >= ws:
                        dep += t.amount
                else:
                    balance -= t.amount
                    if t.txn_date >= ws:
                        wd += t.amount
                idx += 1
            rows.append({"tenant_id": tenant.id, "borrower_id": borrower_id, "account_no": accounts[borrower_id],
                         "week_start": ws, "balance": balance, "deposits": dep, "withdrawals": wd})
    for chunk in _chunks(rows, 2000):
        session.execute(pg_insert(SavingsSnapshot).values(chunk))


def _chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


# ---------------------------------------------------------------------------
# Cases


def refresh_cases(session: Session, tenant: Tenant, at: datetime, actor: str = "system") -> dict:
    """Open a case for each newly overdue loan (assigning control/treatment),
    close cases whose loan is back to current, and keep buckets current."""
    version, policy = policy_mod.current(session, tenant)
    open_cases = {
        c.loan_id: c for c in session.scalars(select(Case).where(Case.tenant_id == tenant.id, Case.status == "open"))
    }
    branch_names = dict(session.execute(select(Branch.id, Branch.name).where(Branch.tenant_id == tenant.id)).all())
    loans = list(session.scalars(
        select(Loan).where(Loan.tenant_id == tenant.id, Loan.status == "active").order_by(Loan.id)
    ))
    stats = {"opened": 0, "closed_cured": 0, "bucket_changed": 0, "control": 0, "treatment": 0}
    for loan in loans:
        case = open_cases.get(loan.id)
        overdue = loan.days_overdue > 0 and loan.amount_overdue > 0
        if overdue and case is None:
            bucket = policy_mod.bucket_for(policy, loan.days_overdue)
            stratum = stratum_key(bucket, branch_names[loan.branch_id])
            arm, position = assign_arm(session, tenant.id, stratum, policy.control.share, policy.control.block_size)
            case = Case(
                tenant_id=tenant.id, loan_id=loan.id, borrower_id=loan.borrower_id, branch_id=loan.branch_id,
                officer_id=loan.officer_id, status="open", state="new", opened_at=at, currency=loan.currency,
                bucket_at_open=bucket, bucket=bucket, amount_overdue_at_open=loan.amount_overdue,
                principal_outstanding_at_open=loan.principal_outstanding, arm=arm, stratum=stratum,
                policy_version_at_open=version,
            )
            session.add(case)
            session.flush()
            common = {"tenant_id": tenant.id, "at": at, "actor": actor, "policy_version": version,
                      "case_id": case.id, "loan_id": loan.id, "borrower_id": loan.borrower_id}
            emit(session, type=EventType.case_opened, payload={
                "bucket": bucket, "days_overdue": loan.days_overdue, "amount_overdue": loan.amount_overdue,
                "principal_outstanding": loan.principal_outstanding, "currency": loan.currency,
            }, **common)
            emit(session, type=EventType.control_assigned, payload={
                "arm": arm, "stratum": stratum, "position_in_stratum": position,
                "share": policy.control.share, "block_size": policy.control.block_size,
            }, **common)
            stats["opened"] += 1
            stats[arm] += 1
        elif case is not None and not overdue:
            case.status, case.state, case.close_reason, case.closed_at = "closed", "closed", "cured", at
            emit(session, tenant_id=tenant.id, type=EventType.case_closed, at=at, actor=actor,
                 policy_version=version, case_id=case.id, loan_id=loan.id, borrower_id=loan.borrower_id,
                 payload={"reason": "cured", "source": "import"})
            stats["closed_cured"] += 1
        elif case is not None:
            bucket = policy_mod.bucket_for(policy, loan.days_overdue)
            if bucket != case.bucket:
                emit(session, tenant_id=tenant.id, type=EventType.bucket_changed, at=at, actor=actor,
                     policy_version=version, case_id=case.id, loan_id=loan.id, borrower_id=loan.borrower_id,
                     payload={"from": case.bucket, "to": bucket, "days_overdue": loan.days_overdue})
                case.bucket = bucket
                stats["bucket_changed"] += 1
    session.flush()
    return stats


# ---------------------------------------------------------------------------
# Entry point


def import_files(
    session: Session,
    tenant: Tenant,
    files: dict[str, tuple[str, bytes]],
    *,
    mappings: dict[str, dict] | None = None,
    anonymise: bool = False,
    actor: str = "system",
    as_of: date | None = None,
) -> dict:
    """files: kind -> (filename, content). `loans` is required; `schedule` and
    `savings` are optional and enrich ranking signals."""
    at = clock.now(tenant)
    as_of = as_of or clock.today(tenant)
    mappings = mappings or {}
    result: dict = {"as_of": as_of.isoformat(), "batches": {}}

    filename, content = files["loans"]
    headers, rows = read_table(content, filename)
    mapping = mappings.get("loans") or suggest_mapping(headers, "loans")
    report = Report(rows=len(rows))
    mapped = map_rows(rows, mapping, "loans", report)
    records = validate_loans(mapped, as_of, report)
    if anonymise:
        records = [anonymise_loan_row(tenant.id, r) for r in records]
    report.accepted = len(records)
    batch = ImportBatch(tenant_id=tenant.id, filename=filename, file_kind="loans", mapping=mapping,
                        anonymised=anonymise, as_of=as_of, row_count=len(rows), accepted_count=len(records),
                        created_by=actor, created_at=at)
    session.add(batch)
    session.flush()
    stats = upsert_loans(session, tenant, records, batch, at, actor)
    batch.report = {**report.as_dict(), "changes": stats}
    result["batches"]["loans"] = {"id": batch.id, **batch.report}

    currency_by_loan = {r["loan_external_id"]: r["currency"] for r in records}
    currency_by_savings = {r["savings_account_no"]: r["currency"] for r in records if r.get("savings_account_no")}
    if not currency_by_loan:
        currency_by_loan = dict(session.execute(
            select(Loan.external_id, Loan.currency).where(Loan.tenant_id == tenant.id)).all())

    for kind, lookup, key in (("schedule", currency_by_loan, "loan_external_id"),
                              ("savings", currency_by_savings, "savings_account_no")):
        if kind not in files:
            continue
        fname, fcontent = files[kind]
        headers, rows = read_table(fcontent, fname)
        mapping = mappings.get(kind) or suggest_mapping(headers, kind)
        rep = Report(rows=len(rows))
        col = mapping.get(key)

        def currency_for(raw, _m, lookup=lookup, col=col):
            return lookup.get(str(raw.get(col, "")).strip())

        recs = [r for _, r in map_rows(rows, mapping, kind, rep, currency_for)]
        b = ImportBatch(tenant_id=tenant.id, filename=fname, file_kind=kind, mapping=mapping,
                        anonymised=anonymise, as_of=as_of, row_count=len(rows), created_by=actor, created_at=at)
        session.add(b)
        session.flush()
        n = upsert_schedule(session, tenant, recs, rep) if kind == "schedule" else upsert_savings(
            session, tenant, recs, as_of)
        rep.accepted = n
        b.accepted_count = n
        b.report = rep.as_dict()
        result["batches"][kind] = {"id": b.id, **b.report}

    result["cases"] = refresh_cases(session, tenant, at, actor)
    emit(session, tenant_id=tenant.id, type=EventType.import_completed, at=at, actor=actor,
         policy_version=tenant.current_policy_version,
         payload={"as_of": as_of, "loans_batch_id": batch.id, "changes": stats, "cases": result["cases"],
                  "anonymised": anonymise,
                  "rejected": result["batches"]["loans"]["rejected"]})
    return result
