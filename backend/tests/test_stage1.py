from collections import Counter, defaultdict

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.domain.control import block_layout
from app.ingest import pipeline
from app.models import Case, Event, Tenant
from app.seed import generator, mifos_export
from app.seed.loader import reset_tenant
from tests.conftest import AS_OF


# --- event log --------------------------------------------------------------


def test_events_cannot_be_updated(seeded_mm, session):
    event_id = session.scalar(select(Event.id).where(Event.tenant_id == "mm-demo").limit(1))
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("UPDATE events SET type = 'x' WHERE id = :id"), {"id": event_id})


def test_events_cannot_be_deleted_without_demo_reset(seeded_mm, session):
    event_id = session.scalar(select(Event.id).where(Event.tenant_id == "mm-demo").limit(1))
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})


def test_events_cannot_be_truncated(seeded_mm, session):
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("TRUNCATE events CASCADE"))


def test_non_demo_tenant_cannot_be_reset(seeded_mm, session):
    session.execute(text("UPDATE tenants SET is_demo = false WHERE id = 'mm-demo'"))
    session.expire_all()
    with pytest.raises(PermissionError):
        reset_tenant(session, "mm-demo")
    # Even with the flag forced on, the trigger checks the tenant itself.
    session.execute(text("SET LOCAL tenpai.allow_demo_reset = 'on'"))
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("DELETE FROM events WHERE tenant_id = 'mm-demo'"))


# --- seed -------------------------------------------------------------------


def test_seed_is_deterministic():
    a, b = generator.generate("MM", AS_OF), generator.generate("MM", AS_OF)
    assert a.loans == b.loans and a.schedule == b.schedule and a.savings == b.savings
    assert a.telegram == b.telegram


def test_seed_shape():
    for market in ("MM", "KH"):
        w = generator.generate(market, AS_OF)
        assert len(w.loans) == 1500
        overdue = [l for l in w.loans if l["days_overdue"] > 0]
        assert 200 <= len(overdue) <= 320
        assert len(w.officers) == 12 and len(w.branches) == 3
        assert {l["group_name"] is not None for l in w.loans} == {True, False}
        # Every bucket populated.
        buckets = Counter(min(5, sum(l["days_overdue"] > edge for edge in (7, 30, 60, 90)) + 1) for l in overdue)
        assert set(buckets) == {1, 2, 3, 4, 5}
        assert all(l["phone"] is None or l["phone"].startswith(("+959000", "+85500")) for l in w.loans)


def test_khmer_tenant_has_two_currencies():
    w = generator.generate("KH", AS_OF)
    assert {l["currency"] for l in w.loans} == {"USD", "KHR"}


# --- import -----------------------------------------------------------------


def test_sample_file_validation(seeded_mm):
    loans = seeded_mm["import"]["batches"]["loans"]
    assert loans["rows"] == 1503
    assert loans["accepted"] == 1500
    assert loans["counts"] == {"missing_phone": 3, "negative_balance": 1, "duplicate_loan_id": 1, "future_date": 1}


def test_reimport_is_idempotent_and_arms_are_locked(seeded_mm, session, tmp_path):
    tenant = session.get(Tenant, "mm-demo")
    before = dict(session.execute(select(Case.loan_id, Case.arm).where(Case.tenant_id == tenant.id)).all())
    paths = mifos_export.write(generator.generate("MM", AS_OF), tmp_path)
    out = pipeline.import_files(session, tenant, {"loans": (paths["loans"].name, paths["loans"].read_bytes())},
                                as_of=AS_OF)
    assert out["cases"]["opened"] == 0
    assert out["batches"]["loans"]["changes"]["new"] == 0
    after = dict(session.execute(select(Case.loan_id, Case.arm).where(Case.tenant_id == tenant.id)).all())
    assert before == after


# --- control assignment -----------------------------------------------------


def test_block_layout_is_stable_and_exact():
    a = block_layout("t", "8_30|Bago", 0, 0.15, 13)
    assert a == block_layout("t", "8_30|Bago", 0, 0.15, 13)
    assert a.count("control") == 2 and len(a) == 13
    assert a != block_layout("t", "8_30|Bago", 1, 0.15, 13) or a != block_layout("t", "8_30|Takeo", 0, 0.15, 13)


def test_control_is_stratified(seeded_mm, session):
    cases = session.execute(
        select(Case.stratum, Case.arm, Case.id).where(Case.tenant_id == "mm-demo").order_by(Case.id)
    ).all()
    by_stratum = defaultdict(list)
    for stratum, arm, _ in cases:
        by_stratum[stratum].append(arm)
    for stratum, arms in by_stratum.items():
        full = len(arms) // 13 * 13
        assert arms[:full].count("control") == full // 13 * 2, stratum
    share = sum(a == "control" for _, a, _ in cases) / len(cases)
    assert 0.10 <= share <= 0.20


def test_control_assignment_is_recorded_as_event(seeded_mm, session):
    case = session.scalars(select(Case).where(Case.tenant_id == "mm-demo").limit(1)).one()
    ev = session.scalars(select(Event).where(Event.case_id == case.id, Event.type == "control_assigned")).one()
    assert ev.payload["arm"] == case.arm and ev.payload["stratum"] == case.stratum


def test_renamed_columns_import_via_mapping(seeded_mm, session, tmp_path):
    """A non-Mifos file: the suggester finds what it can, the user maps the rest."""
    from app.ingest.canonical import FIELDS_BY_KIND

    world = generator.generate("MM", AS_OF)
    path = mifos_export.write_other(world, tmp_path)
    headers, _ = pipeline.read_table(path.read_bytes(), path.name)
    suggested = pipeline.suggest_mapping(headers, "loans")
    assert suggested["loan_external_id"] == "Acct No" or suggested["loan_external_id"] is None
    mapping = {k: v for k, v in mifos_export.OTHER_HEADERS.items()}
    required = {f.key for f in FIELDS_BY_KIND["loans"] if f.required}
    assert required <= set(mapping)
    tenant = session.get(Tenant, "mm-demo")
    out = pipeline.import_files(session, tenant, {"loans": (path.name, path.read_bytes())},
                                mappings={"loans": mapping}, as_of=AS_OF)
    assert out["batches"]["loans"]["accepted"] == 1500
    assert out["cases"]["opened"] == 0  # same book, different file layout


def test_unmapped_columns_do_not_blank_existing_values(seeded_mm, session, tmp_path):
    from app.models import Loan

    world = generator.generate("MM", AS_OF)
    path = mifos_export.write_other(world, tmp_path)
    tenant = session.get(Tenant, "mm-demo")
    before = session.scalars(select(Loan).where(Loan.tenant_id == "mm-demo", Loan.appraisal.is_not(None))).first()
    rate, appraisal, local = before.interest_rate_annual, before.appraisal, before.loan_cycle
    pipeline.import_files(session, tenant, {"loans": (path.name, path.read_bytes())},
                          mappings={"loans": dict(mifos_export.OTHER_HEADERS)}, as_of=AS_OF)
    session.refresh(before)
    assert (before.interest_rate_annual, before.appraisal, before.loan_cycle) == (rate, appraisal, local)
