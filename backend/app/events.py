"""The event log.

`emit` is the only way anything is written to `events`. Services call it in the
same transaction as the projection change it explains, so the log and the
screens can never disagree.
"""
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event


class EventType(StrEnum):
    loan_imported = "loan_imported"
    import_completed = "import_completed"
    case_opened = "case_opened"
    control_assigned = "control_assigned"
    scored = "scored"
    segment_changed = "segment_changed"
    bucket_changed = "bucket_changed"
    message_planned = "message_planned"
    message_blocked = "message_blocked"
    message_sent = "message_sent"
    message_delivered = "message_delivered"
    message_read = "message_read"
    reply_received = "reply_received"
    reply_classified = "reply_classified"
    telegram_linked = "telegram_linked"
    opted_out = "opted_out"
    ptp_created = "ptp_created"
    ptp_kept = "ptp_kept"
    ptp_broken = "ptp_broken"
    plan_options_generated = "plan_options_generated"
    plan_accepted = "plan_accepted"
    approval_requested = "approval_requested"
    approval_decided = "approval_decided"
    agreement_generated = "agreement_generated"
    payment_requested = "payment_requested"
    payment_received = "payment_received"
    payment_matched = "payment_matched"
    payment_exported = "payment_exported"
    visit_assigned = "visit_assigned"
    visit_outcome = "visit_outcome"
    complaint_opened = "complaint_opened"
    complaint_closed = "complaint_closed"
    flag_raised = "flag_raised"
    automation_paused = "automation_paused"
    automation_resumed = "automation_resumed"
    case_closed = "case_closed"
    call_logged = "call_logged"
    policy_changed = "policy_changed"
    template_changed = "template_changed"
    brand_changed = "brand_changed"
    clock_advanced = "clock_advanced"


def emit(
    session: Session,
    *,
    tenant_id: str,
    type: EventType | str,
    at: datetime,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
    policy_version: int | None = None,
    case_id: int | None = None,
    loan_id: int | None = None,
    borrower_id: int | None = None,
) -> Event:
    event = Event(
        tenant_id=tenant_id,
        type=str(type),
        created_at=at,
        actor=actor,
        payload=_jsonable(payload or {}),
        policy_version=policy_version,
        case_id=case_id,
        loan_id=loan_id,
        borrower_id=borrower_id,
    )
    session.add(event)
    session.flush()
    return event


def emit_many(session: Session, rows: list[dict[str, Any]]) -> None:
    """Bulk insert for imports. Each row has the same keys as `emit`'s arguments."""
    if not rows:
        return
    from sqlalchemy import insert

    session.execute(
        insert(Event),
        [
            {
                "tenant_id": r["tenant_id"],
                "type": str(r["type"]),
                "created_at": r["at"],
                "actor": r.get("actor", "system"),
                "payload": _jsonable(r.get("payload") or {}),
                "policy_version": r.get("policy_version"),
                "case_id": r.get("case_id"),
                "loan_id": r.get("loan_id"),
                "borrower_id": r.get("borrower_id"),
            }
            for r in rows
        ],
    )


def events_for(session: Session, tenant_id: str, **filters) -> list[Event]:
    q = select(Event).where(Event.tenant_id == tenant_id)
    for key, value in filters.items():
        q = q.where(getattr(Event, key) == value)
    return list(session.scalars(q.order_by(Event.id)))


def _jsonable(value):
    """Dates and other simple types to JSON-safe values."""
    from datetime import date

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
