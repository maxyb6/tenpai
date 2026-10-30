"""Ranking v1: rules with visible reason codes.

Three parts, kept apart so an ML model can replace the middle one:

1. `extract_features` builds `CaseFeatures` from the book and the event log.
2. A `Ranker` turns features into pay likelihood, stake and reason codes.
3. `segment_for` maps scores and flags to Nudge / Plan / Visit / Sensitive.

`score_open_cases` runs all three and writes a `scored` event per case holding
the exact inputs and outputs, so the reason codes on screen are the ones that
drove the decision.
"""
from bisect import bisect_left
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app import policy as policy_mod
from app.events import EventType, emit
from app.models import Borrower, Case, Flag, Loan, Message, Promise, SavingsSnapshot, Schedule, TelegramLink, Tenant
from app.money import fmt, to_reporting
from app.policy import PolicyData

BUCKET_BASE_RATE = {"pre_due": 90, "1_7": 78, "8_30": 58, "31_60": 38, "61_90": 24, "90_plus": 12}
ON_TIME_GRACE_DAYS = 3
SENSITIVE_FLAG_KINDS = {"vulnerability", "dispute", "complaint", "deceased", "lender_tag"}


@dataclass
class CaseFeatures:
    case_id: int
    bucket: str
    days_overdue: int
    amount_overdue_rep: int  # reporting currency, minor units
    principal_outstanding_rep: int
    amount_overdue: int
    currency: str
    instalments_considered: int
    instalments_on_time: int
    promises_kept: int
    promises_broken: int
    savings_regular_before: bool
    weeks_since_deposit: int | None
    telegram_linked: bool
    telegram_last_inbound_days: int | None
    sms_invite_sent_days: int | None
    has_phone: bool
    prior_restructures: int
    loan_cycle: int
    unanswered_attempts: int
    sensitive_flags: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    pay_likelihood: float
    stake: float
    priority: float
    reason_codes: list[dict]
    ranker: str


class Ranker(Protocol):
    name: str

    def score(self, f: CaseFeatures, stake: float, policy: PolicyData) -> ScoreResult: ...


def _reason(code: str, text: str, impact: float = 0.0) -> dict:
    return {"code": code, "text": text, "impact": round(impact, 1)}


class RulesRanker:
    name = "rules-v1"

    def score(self, f: CaseFeatures, stake: float, policy: PolicyData) -> ScoreResult:
        w = policy.ranking
        pl = float(BUCKET_BASE_RATE.get(f.bucket, 30))
        reasons = [_reason("days_overdue", f"{f.days_overdue} days overdue", 0)]

        if f.instalments_considered:
            ratio = f.instalments_on_time / f.instalments_considered
            adj = w.on_time_ratio * (ratio - 0.5)
            pl += adj
            reasons.append(_reason("on_time", f"{f.instalments_on_time} of last {f.instalments_considered} "
                                   f"instalments paid on time", adj))
        if f.promises_kept + f.promises_broken:
            n = f.promises_kept + f.promises_broken
            adj = w.promises_kept * (f.promises_kept / n - 0.5)
            pl += adj
            text = (f"{f.promises_broken} of {n} promises broken" if f.promises_broken
                    else f"{f.promises_kept} of {n} promises kept")
            reasons.append(_reason("promises", text, adj))
        if f.savings_regular_before and f.weeks_since_deposit is not None \
                and f.weeks_since_deposit >= w.savings_stopped_weeks:
            pl += w.savings_stopped
            reasons.append(_reason("savings_stopped",
                                   f"Savings deposits stopped {f.weeks_since_deposit} weeks ago", w.savings_stopped))
        if f.telegram_linked:
            if f.telegram_last_inbound_days is not None and f.telegram_last_inbound_days <= 60:
                pl += w.telegram_responsive
                reasons.append(_reason("telegram_responsive",
                                       f"On Telegram, replied {f.telegram_last_inbound_days} days ago",
                                       w.telegram_responsive))
            else:
                reasons.append(_reason("telegram_linked", "On Telegram, no recent replies", 0))
        else:
            pl += w.telegram_unlinked
            reasons.append(_reason("telegram_unlinked", "Not on Telegram", w.telegram_unlinked))
        if f.prior_restructures:
            pl += w.prior_restructure
            reasons.append(_reason("prior_restructure", f"Restructured {f.prior_restructures}x before",
                                   w.prior_restructure))
        if f.loan_cycle >= 2:
            pl += w.repeat_borrower
            reasons.append(_reason("repeat_borrower", f"Repeat borrower (cycle {f.loan_cycle})", w.repeat_borrower))
        if f.unanswered_attempts:
            reasons.append(_reason("unanswered", f"{f.unanswered_attempts} messages unanswered", 0))
        if stake >= 90:
            reasons.append(_reason("stake_high", "Amount at stake in top 10% of overdue book", 0))
        elif stake >= 75:
            reasons.append(_reason("stake_high", "Amount at stake in top 25% of overdue book", 0))
        pl = max(0.0, min(100.0, pl))
        total = w.pay_likelihood + w.stake
        # Priority = need for intervention: money at stake, weighted against how
        # likely the borrower is to cure on their own.
        priority = (w.stake * stake + w.pay_likelihood * (100 - pl)) / total
        return ScoreResult(round(pl, 1), round(stake, 1), round(priority, 1), reasons, self.name)


RANKER: Ranker = RulesRanker()


def segment_for(f: CaseFeatures, s: ScoreResult, policy: PolicyData) -> tuple[str, str]:
    """Returns (segment, rule that decided it)."""
    rules = policy.segments
    if f.sensitive_flags:
        return "sensitive", f"flag:{','.join(sorted(f.sensitive_flags))}"
    strategy = next((x for x in policy.strategy if x.bucket == f.bucket), None)
    if strategy and strategy.escalate_to_visit_after_attempts is not None \
            and f.unanswered_attempts >= strategy.escalate_to_visit_after_attempts:
        return "visit", f"strategy:{f.bucket}:escalate_after_{strategy.escalate_to_visit_after_attempts}"
    if not f.telegram_linked and rules.visit_if_unlinked:
        if not f.has_phone:
            return "visit", "no_digital_channel"
        if f.sms_invite_sent_days is not None and f.sms_invite_sent_days >= 3:
            return "visit", "telegram_invite_unanswered"
    if f.unanswered_attempts >= rules.visit_after_unanswered_attempts:
        return "visit", "unanswered_attempts"
    if f.promises_broken >= rules.visit_on_broken_promises:
        return "visit", "broken_promises"
    if s.stake >= rules.visit_min_stake and s.pay_likelihood < rules.nudge_min_pay_likelihood:
        return "visit", "high_stake_low_likelihood"
    if s.pay_likelihood >= rules.nudge_min_pay_likelihood:
        return "nudge", "likely_to_self_cure"
    return "plan", "unlikely_to_pay_in_full"


def next_action_for(segment: str, f: CaseFeatures) -> str:
    if segment == "sensitive":
        return "Manager review"
    if segment == "visit":
        return "Officer visit"
    if not f.telegram_linked:
        return "Send Telegram invite (SMS)" if f.sms_invite_sent_days is None else "Await Telegram opt-in"
    return "Send reminder" if segment == "nudge" else "Offer plan"


def _pct_rank(sorted_values: list[int], v: int) -> float:
    if len(sorted_values) <= 1:
        return 100.0
    return 100.0 * bisect_left(sorted_values, v) / (len(sorted_values) - 1)


def extract_features(session: Session, tenant: Tenant, cases: list[Case], policy: PolicyData) -> dict[int, CaseFeatures]:
    today = clock.today(tenant)
    now = clock.now(tenant)
    loan_ids = [c.loan_id for c in cases]
    borrower_ids = [c.borrower_id for c in cases]
    loans = {l.id: l for l in session.scalars(select(Loan).where(Loan.id.in_(loan_ids)))}

    sched = defaultdict(list)
    for s in session.scalars(select(Schedule).where(Schedule.loan_id.in_(loan_ids), Schedule.version == 1,
                                                    Schedule.due_date < today).order_by(Schedule.due_date)):
        sched[s.loan_id].append(s)

    snaps = defaultdict(list)
    for s in session.scalars(select(SavingsSnapshot).where(SavingsSnapshot.borrower_id.in_(borrower_ids))
                             .order_by(SavingsSnapshot.week_start)):
        snaps[s.borrower_id].append(s)

    links = {l.borrower_id: l for l in session.scalars(
        select(TelegramLink).where(TelegramLink.borrower_id.in_(borrower_ids), TelegramLink.status == "active"))}

    promises = defaultdict(lambda: [0, 0])
    for p in session.scalars(select(Promise).where(Promise.loan_id.in_(loan_ids))):
        if p.status == "kept":
            promises[p.loan_id][0] += 1
        elif p.status in ("broken", "partial"):
            promises[p.loan_id][1] += 1

    case_ids = [c.id for c in cases]
    outbound = defaultdict(list)
    inbound_last = {}
    sms_invites = {}
    for m in session.scalars(select(Message).where(Message.case_id.in_(case_ids)).order_by(Message.id)):
        if m.direction == "out" and m.status in ("sent", "delivered", "read"):
            if m.template_key == "telegram_invite":
                sms_invites[m.case_id] = m.sent_at
            else:
                outbound[m.case_id].append(m.sent_at)
        elif m.direction == "in":
            inbound_last[m.case_id] = m.planned_at

    phones = dict(session.execute(select(Borrower.id, Borrower.phone).where(Borrower.id.in_(borrower_ids))).all())

    flags = defaultdict(set)
    for fl in session.scalars(select(Flag).where(Flag.borrower_id.in_(borrower_ids), Flag.active.is_(True))):
        if fl.kind in SENSITIVE_FLAG_KINDS:
            flags[fl.borrower_id].add(fl.kind)

    out = {}
    for c in cases:
        loan = loans[c.loan_id]
        # Payment behaviour before the current arrears began: the last 6
        # instalments that fell due before the oldest unpaid one.
        arrears_start = today - timedelta(days=loan.days_overdue) if loan.days_overdue > 0 else today
        recent = [s for s in sched[loan.id] if s.due_date < arrears_start][-6:]
        on_time = sum(1 for s in recent if s.paid_on and s.paid_on <= s.due_date + timedelta(days=ON_TIME_GRACE_DAYS))

        regular_before, weeks_since = False, None
        ss = snaps[c.borrower_id]
        if ss:
            dep_weeks = [i for i, s in enumerate(ss) if s.deposits > 0]
            if dep_weeks:
                last = dep_weeks[-1]
                weeks_since = len(ss) - 1 - last
                window = ss[max(0, last - 11):last + 1]
                regular_before = sum(1 for s in window if s.deposits > 0) >= 3
            else:
                weeks_since = len(ss)

        link = links.get(c.borrower_id)
        last_in = inbound_last.get(c.id) or (link.last_inbound_at if link else None)
        unanswered = sum(1 for t in outbound[c.id] if last_in is None or t > last_in)
        if c.automation_paused and c.pause_reason == "manual_pause":
            flags[c.borrower_id].add("lender_tag")

        out[c.id] = CaseFeatures(
            case_id=c.id,
            bucket=c.bucket,
            days_overdue=loan.days_overdue,
            amount_overdue=loan.amount_overdue,
            currency=loan.currency,
            amount_overdue_rep=to_reporting(loan.amount_overdue, loan.currency, tenant.reporting_currency, tenant.fx),
            principal_outstanding_rep=to_reporting(loan.principal_outstanding, loan.currency,
                                                   tenant.reporting_currency, tenant.fx),
            instalments_considered=len(recent),
            instalments_on_time=on_time,
            promises_kept=promises[loan.id][0],
            promises_broken=promises[loan.id][1],
            savings_regular_before=regular_before,
            weeks_since_deposit=weeks_since,
            telegram_linked=link is not None,
            telegram_last_inbound_days=(now - last_in).days if last_in else None,
            sms_invite_sent_days=(now - sms_invites[c.id]).days if c.id in sms_invites else None,
            has_phone=bool(phones.get(c.borrower_id)),
            prior_restructures=loan.restructure_count,
            loan_cycle=loan.loan_cycle,
            unanswered_attempts=unanswered,
            sensitive_flags=sorted(flags[c.borrower_id]),
        )
    return out


def score_open_cases(session: Session, tenant: Tenant, actor: str = "system",
                     case_ids: list[int] | None = None) -> int:
    version, policy = policy_mod.current(session, tenant)
    at = clock.now(tenant)
    all_open = list(session.scalars(select(Case).where(Case.tenant_id == tenant.id, Case.status == "open")))
    if not all_open:
        return 0
    feats = extract_features(session, tenant, all_open, policy)
    # Stake is normalised within the open overdue book.
    overdue_sorted = sorted(f.amount_overdue_rep for f in feats.values())
    outstanding_sorted = sorted(f.principal_outstanding_rep for f in feats.values())
    targets = [c for c in all_open if case_ids is None or c.id in case_ids]
    for c in targets:
        f = feats[c.id]
        stake = 0.6 * _pct_rank(overdue_sorted, f.amount_overdue_rep) + \
            0.4 * _pct_rank(outstanding_sorted, f.principal_outstanding_rep)
        s = RANKER.score(f, stake, policy)
        segment, rule = segment_for(f, s, policy)
        ev = emit(session, tenant_id=tenant.id, type=EventType.scored, at=at, actor=actor, policy_version=version,
                  case_id=c.id, loan_id=c.loan_id, borrower_id=c.borrower_id,
                  payload={"ranker": s.ranker, "inputs": asdict(f), "pay_likelihood": s.pay_likelihood,
                           "stake": s.stake, "priority": s.priority, "reason_codes": s.reason_codes,
                           "segment": segment, "segment_rule": rule})
        if segment != c.segment:
            emit(session, tenant_id=tenant.id, type=EventType.segment_changed, at=at, actor=actor,
                 policy_version=version, case_id=c.id, loan_id=c.loan_id, borrower_id=c.borrower_id,
                 payload={"from": c.segment, "to": segment, "rule": rule, "score_event_id": ev.id})
            c.segment = segment
        c.pay_likelihood, c.stake, c.priority = s.pay_likelihood, s.stake, s.priority
        c.reason_codes = s.reason_codes
        c.last_score_event_id = ev.id
        c.next_action = next_action_for(segment, f)
        if segment == "sensitive":
            c.state = "sensitive"
    session.flush()
    return len(targets)


def describe_amount(amount: int, currency: str) -> str:
    return fmt(amount, currency)
