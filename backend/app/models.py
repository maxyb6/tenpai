"""Tables.

Two kinds of table live here:

* `events` is the source of truth. Append-only, enforced by a Postgres trigger
  (see the initial migration). Every action in Tenpai writes an event.
* Everything else is either reference data imported from the lender's core
  banking system (borrowers, loans, schedules, savings) or a projection that
  services update in the same transaction as the event that caused the change
  (cases, messages, plans, ...). Projections carry the id of the event that
  last changed them where that matters for tracing.

Money is stored as integers in the currency's minor unit: MMK and KHR have no
decimals, USD is stored in cents.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    market: Mapped[str] = mapped_column(String(2))  # MM | KH
    timezone: Mapped[str] = mapped_column(String(64))
    reporting_currency: Mapped[str] = mapped_column(String(3))
    # lender_name, lender_name_local, logo_svg, bot_display_name, bot_username,
    # colors {primary, accent, background}
    brand: Mapped[dict] = mapped_column(JSONB, default=dict)
    # fx rates to reporting currency, minor-unit aware: {"KHR": 4050}
    fx: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Demo clock. Null means wall-clock time.
    demo_now: Mapped[datetime | None] = _ts(nullable=True)
    current_policy_version: Mapped[int] = mapped_column(Integer, default=0)
    data_region_note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    name_local: Mapped[str | None] = mapped_column(String(200))


class Officer(Base):
    __tablename__ = "officers"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    name_local: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    # head_of_collections | branch_manager | credit_officer | leadership
    role: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("officers.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Group(Base):
    """Joint-liability lending group."""

    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("officers.id"))
    name: Mapped[str] = mapped_column(String(200))
    village: Mapped[str | None] = mapped_column(String(200))


class Borrower(Base):
    __tablename__ = "borrowers"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))  # client account no.
    name: Mapped[str] = mapped_column(String(200))
    name_local: Mapped[str | None] = mapped_column(String(200))
    gender: Mapped[str | None] = mapped_column(String(1))
    national_id: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    village: Mapped[str | None] = mapped_column(String(200))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("officers.id"))
    language: Mapped[str] = mapped_column(String(8))  # my | km | en
    anonymised: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))  # loan account no.
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("officers.id"))
    product: Mapped[str] = mapped_column(String(100))
    loan_type: Mapped[str] = mapped_column(String(16))  # individual | group
    currency: Mapped[str] = mapped_column(String(3))
    principal_disbursed: Mapped[int] = mapped_column(BigInteger)
    disbursed_on: Mapped[date] = mapped_column(Date)
    interest_rate_annual: Mapped[float] = mapped_column(Float)
    term_instalments: Mapped[int] = mapped_column(Integer)
    frequency: Mapped[str] = mapped_column(String(16))  # monthly | fortnightly
    instalment_amount: Mapped[int] = mapped_column(BigInteger)
    loan_cycle: Mapped[int] = mapped_column(Integer, default=1)
    principal_outstanding: Mapped[int] = mapped_column(BigInteger)
    interest_outstanding: Mapped[int] = mapped_column(BigInteger, default=0)
    principal_overdue: Mapped[int] = mapped_column(BigInteger, default=0)
    interest_overdue: Mapped[int] = mapped_column(BigInteger, default=0)
    penalty_overdue: Mapped[int] = mapped_column(BigInteger, default=0)
    days_overdue: Mapped[int] = mapped_column(Integer, default=0)
    arrears_as_of: Mapped[date | None] = mapped_column(Date)
    next_due_date: Mapped[date | None] = mapped_column(Date)
    last_repayment_date: Mapped[date | None] = mapped_column(Date)
    last_repayment_amount: Mapped[int | None] = mapped_column(BigInteger)
    savings_account_no: Mapped[str | None] = mapped_column(String(64))
    savings_balance: Mapped[int | None] = mapped_column(BigInteger)
    # household_income, household_expenses, other_debt_repayments (monthly, minor units)
    appraisal: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="active")
    restructure_count: Mapped[int] = mapped_column(Integer, default=0)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    raw: Mapped[dict | None] = mapped_column(JSONB)  # last imported row as received
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())

    @property
    def amount_overdue(self) -> int:
        return self.principal_overdue + self.interest_overdue + self.penalty_overdue


class Schedule(Base):
    """Repayment schedule. version 1 is the lender's original; a restructure adds
    a new version rather than editing the old one."""

    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("loan_id", "version", "instalment_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    instalment_no: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    principal_due: Mapped[int] = mapped_column(BigInteger)
    interest_due: Mapped[int] = mapped_column(BigInteger)
    total_due: Mapped[int] = mapped_column(BigInteger)
    paid_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_on: Mapped[date | None] = mapped_column(Date)  # date fully paid


class SavingsTransaction(Base):
    __tablename__ = "savings_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_no", "txn_date", "txn_type", "amount", "seq"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    borrower_id: Mapped[int | None] = mapped_column(ForeignKey("borrowers.id"), index=True)
    account_no: Mapped[str] = mapped_column(String(64))
    txn_date: Mapped[date] = mapped_column(Date)
    txn_type: Mapped[str] = mapped_column(String(16))  # deposit | withdrawal
    amount: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int | None] = mapped_column(BigInteger)
    seq: Mapped[int] = mapped_column(Integer, default=0)


class SavingsSnapshot(Base):
    """Weekly savings position, derived from savings transactions."""

    __tablename__ = "savings_snapshots"
    __table_args__ = (UniqueConstraint("borrower_id", "week_start"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"), index=True)
    account_no: Mapped[str] = mapped_column(String(64))
    week_start: Mapped[date] = mapped_column(Date)
    balance: Mapped[int] = mapped_column(BigInteger)
    deposits: Mapped[int] = mapped_column(BigInteger, default=0)
    withdrawals: Mapped[int] = mapped_column(BigInteger, default=0)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    file_kind: Mapped[str] = mapped_column(String(16))  # loans | schedule | savings
    mapping: Mapped[dict] = mapped_column(JSONB)
    anonymised: Mapped[bool] = mapped_column(Boolean, default=False)
    as_of: Mapped[date | None] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class ColumnMapping(Base):
    """Saved column mappings, so the second import from the same system is one click."""

    __tablename__ = "column_mappings"
    __table_args__ = (UniqueConstraint("tenant_id", "file_kind", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    file_kind: Mapped[str] = mapped_column(String(16))
    mapping: Mapped[dict] = mapped_column(JSONB)  # canonical field -> source column
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class Case(Base):
    """One collections case per overdue loan. Projection over case events."""

    __tablename__ = "cases"
    __table_args__ = (
        Index(
            "uq_one_open_case_per_loan",
            "loan_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("officers.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    # new | contacting | promised | plan_offered | plan_pending | plan_active |
    # visit | sensitive | closed
    state: Mapped[str] = mapped_column(String(24), default="new")
    close_reason: Mapped[str | None] = mapped_column(String(24))
    opened_at: Mapped[datetime] = _ts()
    closed_at: Mapped[datetime | None] = _ts(nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    bucket_at_open: Mapped[str] = mapped_column(String(16))
    amount_overdue_at_open: Mapped[int] = mapped_column(BigInteger)
    principal_outstanding_at_open: Mapped[int] = mapped_column(BigInteger)
    bucket: Mapped[str] = mapped_column(String(16))
    # Experiment arm. Locked for the life of the case.
    arm: Mapped[str] = mapped_column(String(16))  # control | treatment
    stratum: Mapped[str] = mapped_column(String(100))
    policy_version_at_open: Mapped[int] = mapped_column(Integer)
    segment: Mapped[str | None] = mapped_column(String(16))  # nudge | plan | visit | sensitive
    priority: Mapped[float | None] = mapped_column(Float)
    pay_likelihood: Mapped[float | None] = mapped_column(Float)
    stake: Mapped[float | None] = mapped_column(Float)
    reason_codes: Mapped[list | None] = mapped_column(JSONB)
    last_score_event_id: Mapped[int | None] = mapped_column(BigInteger)
    automation_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(64))
    contact_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_contact_at: Mapped[datetime | None] = _ts(nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(64))
    next_action_at: Mapped[datetime | None] = _ts(nullable=True)
    collected_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = _ts(server_default=func.now(), onupdate=func.now())


class TelegramLink(Base):
    __tablename__ = "telegram_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"), index=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))
    # disbursement_qr | officer_visit | sms_deeplink
    method: Mapped[str] = mapped_column(String(24))
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_text_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | opted_out
    linked_at: Mapped[datetime] = _ts()
    opted_out_at: Mapped[datetime | None] = _ts(nullable=True)
    last_inbound_at: Mapped[datetime | None] = _ts(nullable=True)


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("tenant_id", "key", "language", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(48))
    language: Mapped[str] = mapped_column(String(8))
    version: Mapped[int] = mapped_column(Integer, default=1)
    channel: Mapped[str] = mapped_column(String(16), default="telegram")
    body: Mapped[str] = mapped_column(Text)
    english_shadow: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSONB, default=list)
    # Telegram inline buttons, also template-controlled: [{"label": ..., "action": ...}]
    buttons: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | approved | retired
    needs_native_review: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # out | in
    channel: Mapped[str] = mapped_column(String(16))  # telegram | sms | mini_app
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id"))
    template_key: Mapped[str | None] = mapped_column(String(48))
    template_version: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(8))
    body: Mapped[str | None] = mapped_column(Text)
    body_shadow: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[dict | None] = mapped_column(JSONB)
    # planned | blocked | sent | delivered | read | failed | received
    status: Mapped[str] = mapped_column(String(16))
    gate_decision: Mapped[str | None] = mapped_column(String(8))  # allowed | blocked
    gate_rule_id: Mapped[str | None] = mapped_column(String(48))
    gate_trace: Mapped[list | None] = mapped_column(JSONB)
    policy_version: Mapped[int | None] = mapped_column(Integer)
    next_allowed_at: Mapped[datetime | None] = _ts(nullable=True)
    planned_at: Mapped[datetime] = _ts()
    sent_at: Mapped[datetime | None] = _ts(nullable=True)
    delivered_at: Mapped[datetime | None] = _ts(nullable=True)
    read_at: Mapped[datetime | None] = _ts(nullable=True)
    classification: Mapped[str | None] = mapped_column(String(24))
    classification_detail: Mapped[dict | None] = mapped_column(JSONB)
    external_id: Mapped[str | None] = mapped_column(String(64))


class Promise(Base):
    __tablename__ = "promises"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    due_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))  # mini_app | officer | call | chat
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | kept | broken | partial
    created_at: Mapped[datetime] = _ts()
    resolved_at: Mapped[datetime | None] = _ts(nullable=True)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    generation_id: Mapped[str] = mapped_column(String(36))  # options generated together
    option_type: Mapped[str] = mapped_column(String(16))  # catch_up | reschedule | short_relief
    # offered | pending_approval | approved | active | rejected | superseded
    status: Mapped[str] = mapped_column(String(20), default="offered")
    details: Mapped[dict] = mapped_column(JSONB)
    capacity: Mapped[dict] = mapped_column(JSONB)
    within_policy: Mapped[bool] = mapped_column(Boolean)
    breaches: Mapped[list] = mapped_column(JSONB, default=list)
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()
    accepted_at: Mapped[datetime | None] = _ts(nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))
    kind: Mapped[str] = mapped_column(String(24))  # plan | third_party_contact | waiver
    status: Mapped[str] = mapped_column(String(16), default="pending")
    breaches: Mapped[list] = mapped_column(JSONB, default=list)
    officer_note: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = _ts()
    sla_due_at: Mapped[datetime] = _ts()
    decided_at: Mapped[datetime | None] = _ts(nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_note: Mapped[str | None] = mapped_column(Text)
    counter_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))


class PaymentRequest(Base):
    __tablename__ = "payment_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(24))
    qr_payload: Mapped[str] = mapped_column(Text)
    deeplink: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | paid | expired
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = _ts()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("provider", "external_txn_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    external_txn_id: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    payer_phone: Mapped[str | None] = mapped_column(String(32))
    paid_at: Mapped[datetime] = _ts()
    received_at: Mapped[datetime] = _ts()
    raw: Mapped[dict | None] = mapped_column(JSONB)
    match_status: Mapped[str] = mapped_column(String(16))  # matched | unmatched | reversed
    match_method: Mapped[str | None] = mapped_column(String(24))
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    payment_request_id: Mapped[int | None] = mapped_column(ForeignKey("payment_requests.id"))
    kind: Mapped[str | None] = mapped_column(String(16))  # full | partial | over


class PostingBatch(Base):
    __tablename__ = "posting_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    columns: Mapped[list] = mapped_column(JSONB)
    row_count: Mapped[int] = mapped_column(Integer)
    file_name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class PostingBatchRow(Base):
    """The unique constraint on payment_id is what makes double export impossible."""

    __tablename__ = "posting_batch_rows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("posting_batches.id"), index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), unique=True)


class Visit(Base):
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"))
    officer_id: Mapped[int] = mapped_column(ForeignKey("officers.id"), index=True)
    assigned_for: Mapped[date] = mapped_column(Date)
    priority: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="assigned")  # assigned | completed | cancelled
    # paid | promised | not_home | refused | hardship | dispute | moved_away | deceased
    outcome: Mapped[str | None] = mapped_column(String(16))
    promise_id: Mapped[int | None] = mapped_column(ForeignKey("promises.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String(300))
    photo_taken_at: Mapped[datetime | None] = _ts(nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lng: Mapped[float | None] = mapped_column(Float)
    assigned_at: Mapped[datetime] = _ts()
    completed_at: Mapped[datetime | None] = _ts(nullable=True)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"))
    source: Mapped[str] = mapped_column(String(16))  # mini_app | chat | officer | phone
    text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | in_progress | closed
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = _ts()
    sla_due_at: Mapped[datetime] = _ts()
    closed_at: Mapped[datetime | None] = _ts(nullable=True)


class Flag(Base):
    __tablename__ = "flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    # vulnerability | dispute | complaint | deceased | lender_tag | opt_out
    kind: Mapped[str] = mapped_column(String(16))
    subtype: Mapped[str | None] = mapped_column(String(24))  # illness | death | disaster | job_loss | migration
    source: Mapped[str] = mapped_column(String(24))  # inbound_classifier | officer | manager
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    text: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    raised_at: Mapped[datetime] = _ts()
    raised_by: Mapped[str] = mapped_column(String(64))
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = _ts(nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text)


class Event(Base):
    """Append-only. UPDATE and DELETE are rejected by a database trigger.

    created_at is business time (the tenant's clock, which the demo can
    advance). recorded_at is wall-clock time of the insert.
    """

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_tenant_type_time", "tenant_id", "type", "created_at"),
        Index("ix_events_case", "case_id", "id"),
        Index("ix_events_borrower", "borrower_id", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    case_id: Mapped[int | None] = mapped_column(Integer)
    loan_id: Mapped[int | None] = mapped_column(Integer)
    borrower_id: Mapped[int | None] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(64))  # system | user:<id> | borrower | provider:<name>
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    policy_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()
    recorded_at: Mapped[datetime] = _ts(server_default=func.now())
