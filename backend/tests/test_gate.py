"""No message can be sent that breaks a contact rule."""
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import policy as policy_mod
from app.messaging import service as msg
from app.messaging.gate import check
from app.messaging.templates_seed import category
from app.models import Borrower, Case, Message, TelegramLink, Template, Tenant

TZ = ZoneInfo("Asia/Yangon")


def _linked_treatment_case(session, n=0):
    """An open treatment case with a clean slate: on Telegram, nothing paused or flagged."""
    from app.models import Complaint, Flag

    linked = select(TelegramLink.borrower_id).where(TelegramLink.tenant_id == "mm-demo",
                                                    TelegramLink.status == "active")
    flagged = select(Flag.borrower_id).where(Flag.active.is_(True))
    complained = select(Complaint.borrower_id)
    return session.scalars(select(Case).where(
        Case.tenant_id == "mm-demo", Case.status == "open", Case.arm == "treatment", Case.borrower_id.in_(linked),
        Case.automation_paused.is_(False), Case.borrower_id.not_in(flagged), Case.borrower_id.not_in(complained))
        .order_by(Case.id).offset(n).limit(1)).one()


def _at(tenant, d: date, hh: int, mm: int = 0):
    tenant.demo_now = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
    return tenant.demo_now


def test_brute_force_never_breaks_contact_rules(seeded_mm, session):
    """Try to send a reminder every hour for 15 days, then check what got out."""
    tenant = session.get(Tenant, "mm-demo")
    case = _linked_treatment_case(session)
    borrower = session.get(Borrower, case.borrower_id)
    _, policy = policy_mod.current(session, tenant)
    holidays = {h.date for h in policy.contact.holidays}
    start = date(2026, 11, 16)  # includes Sundays and the 23 Nov holiday
    for d in range(15):
        for hh in range(24):
            at = _at(tenant, start + timedelta(days=d), hh, 15)
            msg.process_due(session, tenant)
            msg.send(session, tenant, borrower=borrower, case=case, key="late_3_days", at=at)
    sent = [m for m in session.scalars(select(Message).where(
        Message.borrower_id == borrower.id, Message.direction == "out",
        Message.status.in_(("sent", "delivered", "read"))))
        if category(m.template_key) != "transactional"]
    assert sent, "something should get through"
    local = [m.sent_at.astimezone(TZ) for m in sent]
    for t in local:
        assert 8 <= t.hour < 19, f"quiet hours broken at {t}"
        assert t.weekday() != 6, f"sent on Sunday {t}"
        assert t.date() not in holidays, f"sent on holiday {t}"
    per_day = Counter(t.date() for t in local)
    assert max(per_day.values()) <= policy.contact.max_per_day
    times = sorted(m.sent_at for m in sent)
    for i, t in enumerate(times):
        window = [x for x in times if t - timedelta(days=7) < x <= t]
        assert len(window) <= policy.contact.max_per_week, f"weekly cap broken at {t}"
    blocked = session.scalars(select(Message).where(Message.borrower_id == borrower.id,
                                                    Message.status == "blocked")).all()
    assert {m.gate_rule_id for m in blocked} >= {"CR-07", "CR-08", "CR-09"}
    assert all(m.policy_version and m.gate_trace for m in blocked)


@pytest.mark.parametrize("hh,rule", [(7, "CR-08"), (19, "CR-08"), (22, "CR-08")])
def test_quiet_hours_block_with_rule_and_next_time(seeded_mm, session, hh, rule):
    tenant = session.get(Tenant, "mm-demo")
    case = _linked_treatment_case(session, 1)
    at = _at(tenant, date(2026, 11, 17), hh)
    m = msg.send(session, tenant, borrower=session.get(Borrower, case.borrower_id), case=case, key="late_3_days", at=at)
    assert m.status == "blocked" and m.gate_rule_id == rule
    nxt = m.next_allowed_at.astimezone(TZ)
    assert nxt.hour == 8 and nxt > at
    retry = session.scalars(select(Message).where(Message.borrower_id == case.borrower_id,
                                                  Message.status == "planned")).one()
    assert retry.planned_at == m.next_allowed_at


def test_control_case_gets_no_collections_messages(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    case = session.scalars(select(Case).where(Case.tenant_id == "mm-demo", Case.arm == "control")).first()
    _at(tenant, date(2026, 11, 17), 10)
    m = msg.send(session, tenant, borrower=session.get(Borrower, case.borrower_id), case=case, key="late_3_days")
    assert m.status == "blocked" and m.gate_rule_id in ("CR-02", "CR-04")
    assert any(t["rule"] == "CR-02" and t["result"] == "block" for t in m.gate_trace)


def test_vulnerability_reply_pauses_automation(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    case = _linked_treatment_case(session, 2)
    borrower = session.get(Borrower, case.borrower_id)
    _at(tenant, date(2026, 11, 17), 10)
    reply = msg.receive_reply(session, tenant, borrower, "အမေ ဆေးရုံတက်နေလို့ပါ")
    assert reply.classification == "vulnerability"
    assert case.automation_paused and case.segment == "sensitive"
    m = msg.send(session, tenant, borrower=borrower, case=case, key="late_7_days")
    assert m.status == "blocked" and m.gate_rule_id == "CR-03"


def test_opt_out_confirms_then_stops(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    case = _linked_treatment_case(session, 3)
    borrower = session.get(Borrower, case.borrower_id)
    _at(tenant, date(2026, 11, 17), 10)
    msg.receive_reply(session, tenant, borrower, "စာမပို့ပါနဲ့")
    confirmation = session.scalars(select(Message).where(Message.borrower_id == borrower.id,
                                                         Message.template_key == "opt_out_confirmation")).one()
    assert confirmation.status in ("sent", "delivered")
    _at(tenant, date(2026, 11, 18), 10)
    m = msg.send(session, tenant, borrower=borrower, case=case, key="late_3_days")
    assert m.status == "blocked"


def test_banned_phrase_blocks(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    version, policy = policy_mod.current(session, tenant)
    case = _linked_treatment_case(session, 4)
    borrower = session.get(Borrower, case.borrower_id)
    tpl = session.scalars(select(Template).where(Template.tenant_id == "mm-demo", Template.key == "late_3_days",
                                                 Template.language == "en")).one()
    at = _at(tenant, date(2026, 11, 17), 10)
    bad = Template(tenant_id=tpl.tenant_id, key=tpl.key, language="en", version=99, channel="telegram",
                   body="Pay now or the police will come", variables=[], buttons=[], status="approved")
    d = check(session, tenant, policy, version, borrower=borrower, case=case, template=bad,
              rendered=bad.body, channel="telegram", at=at)
    assert not d.allowed and d.rule_id == "CR-11"
    # A borrower's name that happens to contain a banned syllable never trips it.
    ok = check(session, tenant, policy, version, borrower=borrower, case=case, template=tpl,
               rendered="Hello Ko Ye ရဲ", channel="telegram", at=at)
    assert all(t["result"] != "block" for t in ok.trace if t["rule"] == "CR-11")


def test_seeded_templates_pass_banned_phrase_check(seeded_mm, session):
    from app.messaging.gate import banned_in

    tenant = session.get(Tenant, "mm-demo")
    _, policy = policy_mod.current(session, tenant)
    for t in session.scalars(select(Template).where(Template.tenant_id == "mm-demo")):
        assert not banned_in(policy, t.body, t.language), (t.key, t.language)


def test_third_party_blocked(seeded_mm, session):
    tenant = session.get(Tenant, "mm-demo")
    version, policy = policy_mod.current(session, tenant)
    case = _linked_treatment_case(session, 5)
    tpl = session.scalars(select(Template).where(Template.tenant_id == "mm-demo", Template.key == "late_3_days",
                                                 Template.language == "en")).one()
    d = check(session, tenant, policy, version, borrower=session.get(Borrower, case.borrower_id), case=case,
              template=tpl, rendered="hello", channel="telegram", at=_at(tenant, date(2026, 11, 17), 10),
              recipient="group_member")
    assert not d.allowed and d.rule_id == "CR-05"
