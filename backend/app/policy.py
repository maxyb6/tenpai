"""Lender policy. Lives in Settings, versioned in `policies`. Every decision
records the version it used. Editing creates a new version; old decisions keep
pointing at the version they were made under."""
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import EventType, emit
from app.models import Policy as PolicyRow
from app.models import Tenant


class Bucket(BaseModel):
    key: str
    label: str
    min_days: int  # days overdue, inclusive; negative = days before due
    max_days: int | None  # inclusive; None = open-ended


class BucketStrategy(BaseModel):
    bucket: str
    channel: str = "telegram"
    templates: list[str]  # sent in order, one per attempt
    attempts: int
    days_between_attempts: int
    escalate_to_visit_after_attempts: int | None
    escalate_on_broken_promise: bool = True


class Holiday(BaseModel):
    date: date
    name: str


class ContactRules(BaseModel):
    quiet_hours_start: str = "19:00"  # nothing at or after this local time
    quiet_hours_end: str = "08:00"  # ... until this local time
    max_per_day: int = 1
    max_per_week: int = 3
    sundays_off: bool = True
    holidays: list[Holiday] = Field(default_factory=list)
    stop_on: list[str] = Field(
        default_factory=lambda: [
            "opt_out",
            "open_complaint",
            "dispute",
            "vulnerability",
            "deceased",
            "manual_pause",
        ]
    )
    # Replies to something the borrower just did (promise confirmation, payment
    # receipt, complaint acknowledgement) skip quiet hours and frequency caps.
    # They still stop on opt-out and deceased.
    transactional_exempt_from_limits: bool = True
    # Only one SMS (the Telegram invite) per case. SMS is for opt-in only.
    max_sms_invites_per_case: int = 1
    third_party_contact_enabled: bool = False
    banned_phrases: dict[str, list[str]] = Field(default_factory=dict)


class ApprovalRule(BaseModel):
    kind: str
    approver_role: str
    max_amount: dict[str, int] | None = None  # by currency; above this, escalate


class PlanPolicy(BaseModel):
    max_tenor_extension_instalments: int = 6
    max_restructures_per_loan: int = 1
    min_instalment: dict[str, int]  # by currency, minor units
    max_share_of_surplus: float = 0.6  # capacity = surplus x this
    max_penalty_waiver_pct: float = 1.0
    max_interest_waiver_pct: float = 0.0
    eligible_products: list[str]
    auto_approval_ceiling: dict[str, int]  # arrears amount, by currency, minor units
    catch_up_max_instalments: int = 4
    short_relief_periods: int = 2
    short_relief_payment_share: float = 0.5


class RankingWeights(BaseModel):
    pay_likelihood: float = 0.45
    stake: float = 0.55
    # Pay-likelihood adjustments, in points on a 0-100 scale.
    on_time_ratio: float = 25.0  # full swing between 0% and 100% on time
    promises_kept: float = 15.0
    savings_stopped: float = -15.0
    telegram_responsive: float = 8.0
    telegram_unlinked: float = -5.0
    prior_restructure: float = -10.0
    repeat_borrower: float = 6.0
    savings_stopped_weeks: int = 4


class SegmentRules(BaseModel):
    nudge_min_pay_likelihood: float = 55
    visit_min_stake: float = 75
    visit_after_unanswered_attempts: int = 3
    visit_on_broken_promises: int = 2
    visit_if_unlinked: bool = True


class ControlGroup(BaseModel):
    share: float = 0.15
    # Permuted blocks within each stratum: 2 control in every 13 (15.4%). Small
    # blocks keep the split tight in small strata (a branch x bucket cell).
    block_size: int = 13


class SLAs(BaseModel):
    approval_hours: int = 24
    complaint_hours: int = 48


class PolicyData(BaseModel):
    buckets: list[Bucket]
    strategy: list[BucketStrategy]
    contact: ContactRules
    plans: PlanPolicy
    approvals: list[ApprovalRule]
    ranking: RankingWeights = Field(default_factory=RankingWeights)
    segments: SegmentRules = Field(default_factory=SegmentRules)
    control: ControlGroup = Field(default_factory=ControlGroup)
    slas: SLAs = Field(default_factory=SLAs)
    visit_cost: dict[str, int]  # per officer visit, by reporting currency
    message_cost: dict[str, int]
    fee: dict = Field(default_factory=dict)


DEFAULT_BUCKETS = [
    Bucket(key="pre_due", label="Pre-due (D-3 to D0)", min_days=-3, max_days=0),
    Bucket(key="1_7", label="1-7", min_days=1, max_days=7),
    Bucket(key="8_30", label="8-30", min_days=8, max_days=30),
    Bucket(key="31_60", label="31-60", min_days=31, max_days=60),
    Bucket(key="61_90", label="61-90", min_days=61, max_days=90),
    Bucket(key="90_plus", label="90+", min_days=91, max_days=None),
]

DEFAULT_STRATEGY = [
    BucketStrategy(bucket="pre_due", templates=["pre_due_reminder", "due_day_reminder"], attempts=2,
                   days_between_attempts=3, escalate_to_visit_after_attempts=None),
    BucketStrategy(bucket="1_7", templates=["late_3_days", "late_7_days"], attempts=2,
                   days_between_attempts=4, escalate_to_visit_after_attempts=None),
    BucketStrategy(bucket="8_30", templates=["late_7_days", "plan_offer", "visit_notice"], attempts=3,
                   days_between_attempts=5, escalate_to_visit_after_attempts=3),
    BucketStrategy(bucket="31_60", templates=["plan_offer", "visit_notice"], attempts=2,
                   days_between_attempts=5, escalate_to_visit_after_attempts=2),
    BucketStrategy(bucket="61_90", templates=["plan_offer", "visit_notice"], attempts=2,
                   days_between_attempts=7, escalate_to_visit_after_attempts=1),
    BucketStrategy(bucket="90_plus", templates=["visit_notice"], attempts=1,
                   days_between_attempts=7, escalate_to_visit_after_attempts=0),
]

BANNED_EN = [
    "police", "arrest", "jail", "prison", "court", "seize", "seizure", "confiscate",
    "land", "house will be taken", "collateral", "shame", "everyone will know",
    "your neighbours", "your family will", "village head", "blacklist",
]
BANNED_MY = ["ရဲ", "ဖမ်း", "ထောင်", "တရားရုံး", "သိမ်း", "မြေ", "အရှက်", "ရပ်ကွက်လူကြီး"]
BANNED_KM = ["ប៉ូលិស", "ចាប់ខ្លួន", "គុក", "តុលាការ", "រឹបអូស", "ដី", "ខ្មាស់"]

# Lunar holidays shift every year. These are approximate and flagged for the
# lender to confirm in Settings.
HOLIDAYS_MM = [
    Holiday(date=date(2026, 10, 25), name="Thadingyut (confirm dates)"),
    Holiday(date=date(2026, 10, 26), name="Thadingyut (confirm dates)"),
    Holiday(date=date(2026, 10, 27), name="Thadingyut (confirm dates)"),
    Holiday(date=date(2026, 11, 23), name="Tazaungdaing (confirm date)"),
    Holiday(date=date(2026, 12, 25), name="Christmas Day"),
    Holiday(date=date(2027, 1, 4), name="Independence Day"),
    Holiday(date=date(2027, 2, 12), name="Union Day"),
    Holiday(date=date(2027, 3, 2), name="Peasants' Day"),
    *[Holiday(date=date(2027, 4, d), name="Thingyan (confirm dates)") for d in range(13, 18)],
]
HOLIDAYS_KH = [
    Holiday(date=date(2026, 11, 9), name="Independence Day"),
    *[Holiday(date=date(2026, 11, d), name="Water Festival (confirm dates)") for d in (23, 24, 25)],
    Holiday(date=date(2027, 1, 7), name="Victory over Genocide Day"),
    *[Holiday(date=date(2027, 4, d), name="Khmer New Year (confirm dates)") for d in (14, 15, 16)],
    *[Holiday(date=date(2027, 9, d), name="Pchum Ben (confirm dates)") for d in (29, 30)],
]


def default_policy(market: str) -> PolicyData:
    if market == "MM":
        holidays, banned = HOLIDAYS_MM, {"en": BANNED_EN, "my": BANNED_MY}
        plans = PlanPolicy(
            min_instalment={"MMK": 20_000},
            eligible_products=["General Business Loan", "Group Loan", "Agriculture Loan"],
            auto_approval_ceiling={"MMK": 600_000},
        )
        approvals = [
            ApprovalRule(kind="plan", approver_role="branch_manager", max_amount={"MMK": 3_000_000}),
            ApprovalRule(kind="plan", approver_role="head_of_collections"),
            ApprovalRule(kind="third_party_contact", approver_role="branch_manager"),
        ]
        visit_cost, message_cost = {"MMK": 6_000}, {"MMK": 30}
        fee = {"monthly_platform_fee": 1_200_000, "success_fee_pct": 0.10, "currency": "MMK"}
    else:
        holidays, banned = HOLIDAYS_KH, {"en": BANNED_EN, "km": BANNED_KM}
        plans = PlanPolicy(
            min_instalment={"USD": 1_000, "KHR": 40_000},
            eligible_products=["Business Loan", "Group Loan", "Agriculture Loan"],
            auto_approval_ceiling={"USD": 30_000, "KHR": 1_200_000},
        )
        approvals = [
            ApprovalRule(kind="plan", approver_role="branch_manager",
                         max_amount={"USD": 150_000, "KHR": 6_000_000}),
            ApprovalRule(kind="plan", approver_role="head_of_collections"),
            ApprovalRule(kind="third_party_contact", approver_role="branch_manager"),
        ]
        visit_cost, message_cost = {"USD": 250}, {"USD": 1}
        fee = {"monthly_platform_fee": 50_000, "success_fee_pct": 0.10, "currency": "USD"}
    return PolicyData(
        buckets=DEFAULT_BUCKETS,
        strategy=DEFAULT_STRATEGY,
        contact=ContactRules(holidays=holidays, banned_phrases=banned),
        plans=plans,
        approvals=approvals,
        visit_cost=visit_cost,
        message_cost=message_cost,
        fee=fee,
    )


def current(session: Session, tenant: Tenant) -> tuple[int, PolicyData]:
    row = session.scalar(
        select(PolicyRow).where(
            PolicyRow.tenant_id == tenant.id, PolicyRow.version == tenant.current_policy_version
        )
    )
    if row is None:
        raise LookupError(f"tenant {tenant.id} has no policy")
    return row.version, PolicyData.model_validate(row.data)


def at_version(session: Session, tenant_id: str, version: int) -> PolicyData:
    row = session.scalar(
        select(PolicyRow).where(PolicyRow.tenant_id == tenant_id, PolicyRow.version == version)
    )
    return PolicyData.model_validate(row.data)


def save_new_version(
    session: Session, tenant: Tenant, data: PolicyData, *, actor: str, at: datetime, note: str | None = None
) -> int:
    version = tenant.current_policy_version + 1
    session.add(
        PolicyRow(
            tenant_id=tenant.id,
            version=version,
            data=data.model_dump(mode="json"),
            note=note,
            created_by=actor,
            created_at=at,
        )
    )
    tenant.current_policy_version = version
    session.flush()
    emit(
        session,
        tenant_id=tenant.id,
        type=EventType.policy_changed,
        at=at,
        actor=actor,
        policy_version=version,
        payload={"version": version, "note": note},
    )
    return version


def bucket_for(policy: PolicyData, days_overdue: int, days_to_next_due: int | None = None) -> str | None:
    """Overdue loans bucket by days overdue. Current loans bucket by days until the
    next instalment (pre-due D-3..D0 becomes min_days=-3, max_days=0)."""
    position = days_overdue if days_overdue > 0 else (
        -days_to_next_due if days_to_next_due is not None else None
    )
    if position is None:
        return None
    for b in policy.buckets:
        if position >= b.min_days and (b.max_days is None or position <= b.max_days):
            return b.key
    return None
