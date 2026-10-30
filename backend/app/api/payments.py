"""6.6 Payments: requests, received, matched, unmatched, reversed; posting files."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app import clock
from app.api.deps import Ctx, ctx
from app.events import EventType, emit
from app.models import Borrower, Case, Loan, Payment, PaymentRequest, PostingBatch, PostingBatchRow
from app.payments import posting
from app.payments import service as pay_svc

router = APIRouter(prefix="/api/t/{tenant_id}")


@router.get("/payments")
def payments(c: Ctx = Depends(ctx), status: str | None = None):
    s, t = c.session, c.tenant
    exported = set(s.scalars(select(PostingBatchRow.payment_id)))
    counts = dict(s.execute(select(Payment.match_status, func.count()).where(Payment.tenant_id == t.id)
                            .group_by(Payment.match_status)).all())
    q = select(Payment).where(Payment.tenant_id == t.id)
    if status:
        q = q.where(Payment.match_status == status)
    rows = []
    for p in s.scalars(q.order_by(Payment.paid_at.desc()).limit(300)):
        loan = s.get(Loan, p.loan_id) if p.loan_id else None
        b = s.get(Borrower, loan.borrower_id) if loan else None
        rows.append({"id": p.id, "paid_at": p.paid_at.isoformat(), "amount": p.amount, "currency": p.currency,
                     "reference": p.reference, "txn": p.external_txn_id, "provider": p.provider,
                     "payer_phone": p.payer_phone, "status": p.match_status, "method": p.match_method, "kind": p.kind,
                     "loan": loan.external_id if loan else None, "borrower": b.name if b else None,
                     "case_id": p.case_id, "exported": p.id in exported})
    req_counts = dict(s.execute(select(PaymentRequest.status, func.count()).where(
        PaymentRequest.tenant_id == t.id).group_by(PaymentRequest.status)).all())
    batches = [{"id": b.id, "created_at": b.created_at.isoformat(), "from": b.date_from.isoformat(),
                "to": b.date_to.isoformat(), "rows": b.row_count, "file": b.file_name, "by": b.created_by}
               for b in s.scalars(select(PostingBatch).where(PostingBatch.tenant_id == t.id)
                                  .order_by(PostingBatch.id.desc()))]
    pending_export = len([p for p in posting.exportable(s, t, date.min, date.max)])
    return {"counts": {"requests": sum(req_counts.values()), "requests_open": req_counts.get("open", 0),
                       "received": sum(counts.values()), **counts, "awaiting_export": pending_export},
            "items": rows, "batches": batches, "columns": posting.DEFAULT_COLUMNS, "sample": t.is_demo,
            "today": clock.today(t).isoformat()}


class MatchBody(BaseModel):
    loan_external_id: str


@router.post("/payments/{payment_id}/match")
def manual_match(payment_id: int, body: MatchBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections", "branch_manager")
    p = c.session.get(Payment, payment_id)
    if p is None or p.tenant_id != c.tenant.id or p.match_status != "unmatched":
        raise HTTPException(404, "unmatched payment not found")
    loan = c.session.scalars(select(Loan).where(Loan.tenant_id == c.tenant.id,
                                                Loan.external_id == body.loan_external_id)).first()
    if loan is None:
        raise HTTPException(404, "loan not found")
    pay_svc.match(c.session, c.tenant, p, loan.id, "manual", actor=c.actor)
    return {"ok": True, "kind": p.kind}


@router.post("/payments/{payment_id}/reverse")
def reverse(payment_id: int, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    p = c.session.get(Payment, payment_id)
    if p is None or p.tenant_id != c.tenant.id or p.match_status == "reversed":
        raise HTTPException(404)
    exported = c.session.scalar(select(func.count()).select_from(PostingBatchRow).where(
        PostingBatchRow.payment_id == p.id))
    prev = p.match_status
    p.match_status = "reversed"
    if p.case_id and prev == "matched":
        case = c.session.get(Case, p.case_id)
        case.collected_amount = max(0, case.collected_amount - p.amount)
    emit(c.session, tenant_id=c.tenant.id, type=EventType.payment_reversed, at=clock.now(c.tenant), actor=c.actor,
         policy_version=c.tenant.current_policy_version, case_id=p.case_id, loan_id=p.loan_id,
         payload={"payment_id": p.id, "amount": p.amount, "was": prev, "already_exported": bool(exported)})
    return {"ok": True, "already_exported": bool(exported),
            "note": "Already in a posting file: reverse it in Mifos too" if exported else None}


class BatchBody(BaseModel):
    date_from: date
    date_to: date
    columns: list[dict] | None = None


@router.post("/posting-batches")
def create_batch(body: BatchBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections", "branch_manager")
    try:
        b = posting.create_batch(c.session, c.tenant, body.date_from, body.date_to, c.actor, body.columns)
    except posting.NothingToExport as e:
        raise HTTPException(409, str(e))
    return {"id": b.id, "rows": b.row_count, "file": b.file_name}


@router.get("/posting-batches/{batch_id}.csv")
def batch_csv(batch_id: int, c: Ctx = Depends(ctx)):
    b = c.session.get(PostingBatch, batch_id)
    if b is None or b.tenant_id != c.tenant.id:
        raise HTTPException(404)
    return Response(b.content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{b.file_name}"'})


@router.get("/restructure-export.csv")
def restructure(c: Ctx = Depends(ctx)):
    content = posting.restructure_export(c.session, c.tenant, c.actor)
    return Response(content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="restructures-{c.tenant.id}.csv"'})
