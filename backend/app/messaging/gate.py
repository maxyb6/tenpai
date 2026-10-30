"""The send gate. Every outbound message passes through `check`. It returns
allowed or blocked, the rule that decided, the policy version, a trace of
every rule evaluated, and the next time the message could be sent."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.messaging.templates_seed import category
from app.models import Borrower, Case, Complaint, Flag, Message, TelegramLink, Template, Tenant
from app.policy import PolicyData

SENT_STATUSES = ("sent", "delivered", "read")
STOP_FLAGS = {"dispute": "dispute", "vulnerability": "vulnerability", "deceased": "deceased"}

RULES = {
    "CR-01": "Template approved",
    "CR-02": "Control group gets the lender's existing process",
    "CR-03": "Automation stopped (opt-out, complaint, dispute, vulnerability, deceased, manual pause)",
    "CR-04": "Channel available and opted in",
    "CR-05": "Borrower only, no third parties",
    "CR-06": "No contact on listed holidays",
    "CR-07": "No contact on Sundays",
    "CR-08": "Quiet hours",
    "CR-09": "Max outbound per day",
    "CR-10": "Max outbound per week",
    "CR-11": "No banned phrases",
    "CR-12": "No contact for anonymised records",
}


@dataclass
class Decision:
    allowed: bool
    rule_id: str | None
    reason: str | None
    policy_version: int
    trace: list[dict] = field(default_factory=list)
    next_allowed_at: datetime | None = None
    exempt_limits: bool = False

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "rule_id": self.rule_id, "reason": self.reason,
                "policy_version": self.policy_version, "trace": self.trace,
                "next_allowed_at": self.next_allowed_at.isoformat() if self.next_allowed_at else None}


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _time_rules(policy: PolicyData, local: datetime) -> tuple[str, str] | None:
    """Rules that depend only on the clock: holiday, Sunday, quiet hours."""
    c = policy.contact
    if any(h.date == local.date() for h in c.holidays):
        name = next(h.name for h in c.holidays if h.date == local.date())
        return "CR-06", f"{local.date().isoformat()} is a listed holiday ({name})"
    if c.sundays_off and local.weekday() == 6:
        return "CR-07", "Sunday"
    start, end = _hhmm(c.quiet_hours_end), _hhmm(c.quiet_hours_start)  # allowed window [end of quiet, start of quiet)
    if not (start <= local.time() < end):
        return "CR-08", f"{local.strftime('%H:%M')} is outside {c.quiet_hours_end}-{c.quiet_hours_start} local time"
    return None


def _sent_between(session: Session, borrower_id: int, start: datetime, end: datetime) -> list[datetime]:
    """Outbound messages that count toward frequency caps."""
    rows = session.execute(
        select(Message.sent_at, Message.template_key).where(
            Message.borrower_id == borrower_id, Message.direction == "out",
            Message.status.in_(SENT_STATUSES), Message.sent_at >= start, Message.sent_at < end)
    ).all()
    return sorted(t for t, key in rows if key is None or category(key) != "transactional")


def _limit_rules(session, policy, borrower_id, at, tz) -> tuple[str, str, datetime] | None:
    c = policy.contact
    local = at.astimezone(tz)
    day_start = datetime.combine(local.date(), time(0), tz)
    today = _sent_between(session, borrower_id, day_start, day_start + timedelta(days=1))
    if len(today) >= c.max_per_day:
        return "CR-09", f"{len(today)} sent today (max {c.max_per_day})", day_start + timedelta(days=1)
    week = _sent_between(session, borrower_id, at - timedelta(days=7), at + timedelta(seconds=1))
    if len(week) >= c.max_per_week:
        return "CR-10", f"{len(week)} sent in the last 7 days (max {c.max_per_week})", \
            week[len(week) - c.max_per_week] + timedelta(days=7)
    return None


def next_allowed(session: Session, policy: PolicyData, borrower_id: int, after: datetime, tz: ZoneInfo,
                 exempt_limits: bool) -> datetime | None:
    """Earliest time at or after `after` that passes all clock and frequency rules."""
    window_start = _hhmm(policy.contact.quiet_hours_end)
    t = after
    for _ in range(400):
        local = t.astimezone(tz)
        tr = _time_rules(policy, local)
        if tr:
            same_day_later = tr[0] == "CR-08" and local.time() < window_start
            day = local.date() if same_day_later else local.date() + timedelta(days=1)
            t = datetime.combine(day, window_start, tz)
            continue
        if not exempt_limits:
            lr = _limit_rules(session, policy, borrower_id, t, tz)
            if lr:
                t = max(lr[2], t + timedelta(minutes=1))
                continue
        return t
    return None


def check(
    session: Session,
    tenant: Tenant,
    policy: PolicyData,
    policy_version: int,
    *,
    borrower: Borrower,
    case: Case | None,
    template: Template,
    rendered: str,
    channel: str,
    at: datetime,
    recipient: str = "borrower",
    as_reply: bool = False,
) -> Decision:
    """as_reply: the message answers something the borrower just sent or did,
    so it is treated as transactional."""
    tz = ZoneInfo(tenant.timezone)
    local = at.astimezone(tz)
    cat = "transactional" if as_reply and category(template.key) != "invite" else category(template.key)
    exempt = cat == "transactional" and policy.contact.transactional_exempt_from_limits
    trace: list[dict] = []
    failures: list[tuple[str, str]] = []

    def rule(rule_id: str, ok: bool, detail: str, exempted: bool = False):
        trace.append({"rule": rule_id, "name": RULES[rule_id],
                      "result": "exempt" if exempted else ("pass" if ok else "block"), "detail": detail})
        if not ok and not exempted:
            failures.append((rule_id, detail))

    # CR-01: lender approval. Draft translations may only be sent from demo tenants.
    approved = template.status == "approved"
    native_ok = not template.needs_native_review or tenant.is_demo
    rule("CR-01", approved and native_ok,
         f"{template.key} v{template.version} ({template.language}) status={template.status}"
         + (", needs native review" if template.needs_native_review else ""))

    # CR-02: control group.
    in_control = case is not None and case.arm == "control"
    rule("CR-02", not in_control or cat == "transactional",
         "control case" if in_control else "treatment case" if case else "no case")

    # CR-03: automation stops.
    stops = []
    link = session.scalars(select(TelegramLink).where(TelegramLink.borrower_id == borrower.id)
                           .order_by(TelegramLink.id.desc())).first()
    if link and link.status == "opted_out" and template.key != "opt_out_confirmation":
        stops.append("opt_out")
    open_complaints = session.scalar(select(func.count(Complaint.id)).where(
        Complaint.borrower_id == borrower.id, Complaint.status != "closed")) or 0
    if open_complaints and template.key != "complaint_received":
        stops.append("open_complaint")
    active_flags = set(session.scalars(select(Flag.kind).where(Flag.borrower_id == borrower.id,
                                                               Flag.active.is_(True))))
    for kind in STOP_FLAGS:
        if kind in active_flags and (kind == "deceased" or cat != "transactional"):
            stops.append(kind)
    if case is not None and case.automation_paused and cat != "transactional":
        reason = case.pause_reason if case.pause_reason in policy.contact.stop_on else "manual_pause"
        stops.append(reason)
    stops = [s for s in stops if s in policy.contact.stop_on]
    rule("CR-03", not stops, ", ".join(stops) if stops else "none")

    # CR-04: channel.
    if channel == "telegram":
        ok = link is not None and link.status == "active" or (template.key == "opt_out_confirmation" and link)
        rule("CR-04", bool(ok), f"telegram link: {link.status if link else 'none'}")
    elif channel == "sms":
        invites = session.scalar(select(func.count(Message.id)).where(
            Message.case_id == (case.id if case else None), Message.channel == "sms",
            Message.status.in_(SENT_STATUSES))) or 0
        ok = (cat == "invite" and bool(borrower.phone) and invites < policy.contact.max_sms_invites_per_case
              and not (link and link.status == "active"))
        rule("CR-04", ok, f"sms is for opt-in invites only; phone={'yes' if borrower.phone else 'no'}, "
                          f"invites sent={invites}")
    else:
        rule("CR-04", False, f"unknown channel {channel}")

    # CR-05: third parties.
    rule("CR-05", recipient == "borrower", f"recipient={recipient}")

    # CR-06..08: clock rules.
    tr = _time_rules(policy, local)
    for rid in ("CR-06", "CR-07", "CR-08"):
        hit = tr is not None and tr[0] == rid
        rule(rid, not hit, tr[1] if hit else "ok", exempted=hit and exempt)

    # CR-09..10: frequency caps across channels.
    lr = _limit_rules(session, policy, borrower.id, at, tz)
    for rid in ("CR-09", "CR-10"):
        hit = lr is not None and lr[0] == rid
        rule(rid, not hit, lr[1] if hit else "ok", exempted=hit and exempt)

    # CR-11: banned phrases (also enforced when a template is approved).
    lowered = rendered.lower()
    banned = [p for lang in ("en", template.language) for p in policy.contact.banned_phrases.get(lang, [])
              if p.lower() in lowered]
    rule("CR-11", not banned, ", ".join(banned) if banned else "none")

    # CR-12: anonymised records have no real contact details.
    rule("CR-12", not borrower.anonymised, "anonymised" if borrower.anonymised else "ok")

    if not failures:
        return Decision(True, None, None, policy_version, trace, exempt_limits=exempt)
    rule_id, detail = failures[0]
    timing_only = all(r in ("CR-06", "CR-07", "CR-08", "CR-09", "CR-10") for r, _ in failures)
    nxt = next_allowed(session, policy, borrower.id, at, tz, exempt) if timing_only else None
    return Decision(False, rule_id, f"{RULES[rule_id]}: {detail}", policy_version, trace, nxt, exempt)


def banned_in(policy: PolicyData, text: str, language: str) -> list[str]:
    lowered = text.lower()
    return [p for lang in ("en", language) for p in policy.contact.banned_phrases.get(lang, [])
            if p.lower() in lowered]
