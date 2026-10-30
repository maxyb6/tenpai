"""Replay 8 weeks of simulated history through the real services.

The generator decided which loans had overdue episodes and how they ended.
This module walks the days in order, sets the tenant clock, and drives the
same code the console uses: case opening with the real control assignment,
the send gate, replies and classification, promises, plans and approvals,
visits, payments and closures. Every number on Results is then computed from
the events this produces. All of it is labelled simulated.
"""
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app import policy as policy_mod
from app.domain import plans as plans_mod
from app.domain.ranking import score_open_cases
from app.events import EventType, emit
from app.ingest.pipeline import open_case
from app.messaging import service as msg
from app.models import (
    Approval,
    Borrower,
    Branch,
    Case,
    Loan,
    Plan,
    Promise,
    Schedule,
    TelegramLink,
    Tenant,
    User,
    Visit,
)
from app.payments import service as pay_svc
from app.payments.provider import provider_for
from app.services import cases as case_svc
from app.services import daily
from app.services import field as field_svc

REPLIES = {
    "my": {"will_pay": "နောက်တစ်ပတ် ပေးပါမယ်", "cant_pay": "ဒီတစ်ပတ် မပေးနိုင်သေးပါဘူး",
           "vulnerability": "အမေ ဆေးရုံတက်နေလို့ပါ", "complaint": "ချေးငွေအရာရှိအကြောင်း တိုင်ကြားချင်ပါတယ်",
           "stop": "စာမပို့ပါနဲ့"},
    "km": {"will_pay": "ខ្ញុំនឹងបង់សប្តាហ៍ក្រោយ", "cant_pay": "សប្តាហ៍នេះខ្ញុំមិនអាចបង់បានទេ",
           "vulnerability": "ម្តាយខ្ញុំសម្រាកនៅមន្ទីរពេទ្យ", "complaint": "ខ្ញុំចង់ដាក់បណ្តឹងអំពីមន្ត្រី",
           "stop": "ឈប់ផ្ញើសារ"},
}


class Replay:
    def __init__(self, session, tenant: Tenant, world, seed: int = 11):
        self.s, self.t, self.w = session, tenant, world
        self.rng = random.Random(f"history:{tenant.id}:{world.as_of}:{seed}")
        self.tz = ZoneInfo(tenant.timezone)
        self.version, self.policy = policy_mod.current(session, tenant)
        self.lang = "my" if tenant.market == "MM" else "km"
        self.loans = {l.external_id: l for l in session.scalars(select(Loan).where(Loan.tenant_id == tenant.id))}
        self.branch_names = dict(session.execute(select(Branch.id, Branch.name).where(Branch.tenant_id == tenant.id)).all())
        self.linked = set(session.scalars(select(TelegramLink.borrower_id).where(TelegramLink.tenant_id == tenant.id)))
        self.managers = {u.branch_id: u for u in session.scalars(select(User).where(
            User.tenant_id == tenant.id, User.role == "branch_manager"))}
        self.sched = defaultdict(list)
        for r in session.scalars(select(Schedule).join(Loan, Loan.id == Schedule.loan_id).where(
                Loan.tenant_id == tenant.id, Schedule.version == 1).order_by(Schedule.instalment_no)):
            self.sched[r.loan_id].append(r)
        self.info: dict[int, dict] = {}

    def at(self, d: date, hh: int, mm: int = 0) -> datetime:
        when = datetime(d.year, d.month, d.day, hh, mm, tzinfo=self.tz)
        self.t.demo_now = when
        return when

    # -- opening ---------------------------------------------------------------

    def open(self, o: dict, d: date):
        loan = self.loans[o["loan"]]
        rows = self.sched[loan.id]
        due_rows = [r for r in rows if o["first_unpaid"] <= r.due_date < d]
        arrears = sum(r.total_due for r in due_rows)
        if o["kind"] == "overdue":
            arrears = sum(r.total_due - (r.paid_amount if r.paid_on is None else 0) for r in due_rows)
        principal_paid_later = sum(r.principal_due for r in rows if r.paid_on and r.paid_on >= d)
        case = open_case(self.s, self.t, loan, at=self.at(d, 7, 30), actor="system:import",
                         days_overdue=o["days_at_open"], amount_overdue=max(arrears, 1),
                         principal_outstanding=loan.principal_outstanding + principal_paid_later,
                         branch_name=self.branch_names[loan.branch_id], version=self.version, policy=self.policy)
        assert case.arm == o["arm"], (o, case.arm)
        b = self.s.get(Borrower, case.borrower_id)
        r = self.rng.random()
        if o["cure_date"]:
            behaviour = "promise_keep" if r < 0.4 else ("promise_break" if r < 0.5 else "quiet")
        else:
            behaviour = ("cant_pay" if r < 0.3 else "promise_break" if r < 0.45 else "vulnerability" if r < 0.52
                         else "complaint" if r < 0.55 else "stop" if r < 0.58 else "quiet")
        self.info[case.id] = {"o": o, "loan": loan, "borrower": b, "first_unpaid": o["first_unpaid"],
                              "next_touch": d, "replied": False, "behaviour": behaviour, "invited": False,
                              "next_visit": d + timedelta(days=self.rng.randint(1, 4)),
                              "linked": b.id in self.linked, "pay_via_app": self.rng.random() < 0.7}

    # -- daily handling ------------------------------------------------------

    def day(self, d: date):
        for cid, info in list(self.info.items()):
            case = self.s.get(Case, cid)
            if case.status != "open":
                del self.info[cid]
                continue
            days = (d - info["first_unpaid"]).days
            bucket = policy_mod.bucket_for(self.policy, max(1, days))
            if bucket != case.bucket:
                emit(self.s, tenant_id=self.t.id, type=EventType.bucket_changed, at=self.at(d, 7, 30),
                     actor="system:import", policy_version=self.version, case_id=case.id, loan_id=case.loan_id,
                     borrower_id=case.borrower_id, payload={"from": case.bucket, "to": bucket, "days_overdue": days})
                case.bucket = bucket
            if info["o"]["cure_date"] == d:
                self.cure(case, info, d)
                continue
            if case.arm == "treatment":
                self.treat(case, info, d, days)
            elif days >= 8 and d >= info["next_visit"]:
                # The lender's existing process: officers visit overdue borrowers weekly.
                case_svc.assign_visit(self.s, self.t, case, actor="system:existing_process",
                                      for_date=d + timedelta(days=1), notify=False)
                info["next_visit"] = d + timedelta(days=7)

    def cure(self, case: Case, info: dict, d: date):
        if case.arm == "treatment" and info["linked"] and info["pay_via_app"] and case.state != "sensitive":
            loan = info["loan"]
            amount = max(0, case.amount_overdue_at_open - case.collected_amount)
            req, _ = pay_svc.create_request(self.s, self.t, loan, case, amount, actor="borrower")
            when = self.at(d, 11, 20)
            pay_svc.receive(self.s, self.t, provider_for("mock").parse_notification({
                "txn_id": f"SIM{case.id:06d}", "reference": req.reference, "amount": amount, "currency": loan.currency,
                "payer_phone": info["borrower"].phone, "paid_at": when.isoformat()}))
            if case.status == "open":
                self.close_import(case, d)
        else:
            self.close_import(case, d)

    def close_import(self, case: Case, d: date):
        """The next core-banking import shows the loan current again."""
        at = self.at(d + timedelta(days=1), 7, 30)
        outside = max(0, case.amount_overdue_at_open - case.collected_amount)
        case.collected_amount += outside
        for p in self.s.scalars(select(Promise).where(Promise.case_id == case.id, Promise.status == "open")):
            p.status, p.resolved_at = "kept", at
            emit(self.s, tenant_id=self.t.id, type=EventType.ptp_kept, at=at, actor="system:import",
                 policy_version=self.version, case_id=case.id, loan_id=case.loan_id, borrower_id=case.borrower_id,
                 payload={"promise_id": p.id, "amount": p.amount, "source": "import"})
        pay_svc.close_case(self.s, self.t, case, "cured", at, "system:import")
        emit(self.s, tenant_id=self.t.id, type=EventType.loan_imported, at=at, actor="system:import",
             policy_version=self.version, case_id=case.id, loan_id=case.loan_id, borrower_id=case.borrower_id,
             payload={"change": "updated", "days_overdue": 0, "collected_outside_tenpai": outside, "simulated": True})

    def treat(self, case: Case, info: dict, d: date, days: int):
        b = info["borrower"]
        if case.automation_paused or case.state in ("sensitive", "plan_pending", "plan_active"):
            return
        if not info["linked"]:
            if b.phone and not info["invited"]:
                msg.send(self.s, self.t, borrower=b, case=case, key="telegram_invite", at=self.at(d, 10, 5))
                info["invited"] = True
            if (days >= 31 or not b.phone or info["invited"]) and d >= info["next_visit"]:
                case_svc.assign_visit(self.s, self.t, case, actor="system:scheduler", for_date=d + timedelta(days=1),
                                      notify=False)
                info["next_visit"] = d + timedelta(days=14)
            return
        strategy = next((s for s in self.policy.strategy if s.bucket == case.bucket), None)
        if case.state != "promised" and strategy and d >= info["next_touch"]:
            sent = [m for m in strategy.templates if m != "visit_notice"]
            attempts = case.contact_attempts
            if attempts < strategy.attempts and sent:
                key = sent[min(attempts, len(sent) - 1)]
                evening = self.rng.random() < 0.06  # a staff member's late batch: the gate holds it
                msg.send(self.s, self.t, borrower=b, case=case, key=key,
                         at=self.at(d, 19, 35) if evening else self.at(d, 10, 0))
                info["next_touch"] = d + timedelta(days=strategy.days_between_attempts)
            elif d >= info["next_visit"] and days >= 20:
                case_svc.assign_visit(self.s, self.t, case, actor="system:scheduler",
                                      for_date=d + timedelta(days=1), notify=True)
                info["next_visit"] = d + timedelta(days=14)
        if not info["replied"] and case.contact_attempts >= 1 and self.rng.random() < 0.5:
            self.reply(case, info, d)

    def reply(self, case: Case, info: dict, d: date):
        info["replied"] = True
        beh = info["behaviour"]
        if beh == "quiet":
            return
        b = info["borrower"]
        when = self.at(d, 14, 10)
        if beh in ("promise_keep", "promise_break"):
            msg.receive_reply(self.s, self.t, b, REPLIES[self.lang]["will_pay"], at=when, score=False)
            cure = info["o"]["cure_date"]
            due = cure if beh == "promise_keep" and cure and cure >= d else d + timedelta(days=self.rng.randint(2, 5))
            arrears = max(1, case.amount_overdue_at_open - case.collected_amount)
            case_svc.record_promise(self.s, self.t, case, amount=arrears, due=due, source="chat", actor="borrower")
        elif beh == "cant_pay":
            msg.receive_reply(self.s, self.t, b, REPLIES[self.lang]["cant_pay"], at=when, score=False)
            plans = plans_mod.generate_for_case(self.s, self.t, case, answers={"income_changed": "same"},
                                                actor="borrower")
            fits = [p for p in plans if p.details.get("affordable")]
            if fits and self.rng.random() < 0.6:
                pick = next((p for p in fits if p.within_policy), fits[0])
                case_svc.accept_plan(self.s, self.t, pick, actor="borrower")
        else:
            msg.receive_reply(self.s, self.t, b, REPLIES[self.lang][beh], at=when, score=False)

    # -- daily sweeps ----------------------------------------------------------

    def sweeps(self, d: date):
        when = self.at(d, 16, 0)
        daily.sweep_promises(self.s, self.t, d, when, self.version, send=True)
        for a in self.s.scalars(select(Approval).where(Approval.tenant_id == self.t.id, Approval.status == "pending",
                                                       Approval.requested_at < when - timedelta(hours=18))):
            decision = "approve" if self.rng.random() < 0.85 else "reject"
            case_svc.decide_approval(self.s, self.t, a, decision=decision, user=self.managers.get(a.branch_id),
                                     note="Simulated decision")
        for v in self.s.scalars(select(Visit).where(Visit.tenant_id == self.t.id, Visit.status == "assigned",
                                                    Visit.assigned_for == d)):
            case = self.s.get(Case, v.case_id)
            if case.status != "open":
                v.status = "cancelled"
                continue
            info = self.info.get(case.id, {})
            self.at(d, 15, self.rng.randint(0, 59))
            r = self.rng.random()
            outcome = ("not_home" if r < 0.3 else "promised" if r < 0.62 else "refused" if r < 0.72
                       else "paid" if r < 0.8 else "hardship" if r < 0.84 else "moved_away" if r < 0.87 else "not_home")
            amount = max(1, case.amount_overdue_at_open - case.collected_amount)
            due = info.get("o", {}).get("cure_date") or d + timedelta(days=self.rng.randint(3, 7))
            if due < d:
                due = d + timedelta(days=3)
            field_svc.record_outcome(self.s, self.t, v, outcome=outcome, actor=f"officer:{v.officer_id}",
                                     notes="Simulated visit", promise_amount=amount if outcome == "promised" else None,
                                     promise_date=due if outcome == "promised" else None)
        # Borrowers read most delivered messages within a day or so.
        from app.models import Message

        for m in self.s.scalars(select(Message).where(Message.tenant_id == self.t.id, Message.status == "delivered",
                                                      Message.channel == "telegram",
                                                      Message.sent_at < when - timedelta(hours=6))):
            if self.rng.random() < 0.45:
                m.status, m.read_at = "read", when
                emit(self.s, tenant_id=self.t.id, type=EventType.message_read, at=when, actor="borrower",
                     case_id=m.case_id, borrower_id=m.borrower_id, policy_version=m.policy_version,
                     payload={"message_id": m.id})
        self.at(d, 8, 0)
        msg.process_due(self.s, self.t, "system:scheduler")

    def snapshot(self, d: date):
        """Weekly PAR from the schedule as it stood on date d."""
        rep, fx = self.t.reporting_currency, self.t.fx
        from app.money import to_reporting

        totals = defaultdict(lambda: defaultdict(int))
        for loan in self.loans.values():
            if loan.disbursed_on > d:
                continue
            rows = self.sched[loan.id]
            paid_principal = sum(r.principal_due for r in rows if r.paid_on and r.paid_on <= d)
            out = to_reporting(max(0, loan.principal_disbursed - paid_principal), loan.currency, rep, fx)
            unpaid = [r for r in rows if r.due_date < d and not (r.paid_on and r.paid_on <= d)]
            days = (d - unpaid[0].due_date).days if unpaid else 0
            for key in ("all", self.branch_names[loan.branch_id]):
                g = totals[key]
                g["outstanding"] += out
                for n in (0, 30, 90):
                    if days > n:
                        g[f"par{n or 1}"] += out
        par = {k: {"outstanding": g["outstanding"], **{p: round(g[p] / g["outstanding"], 4) if g["outstanding"] else 0
                                                       for p in ("par1", "par30", "par90")}}
               for k, g in totals.items()}
        emit(self.s, tenant_id=self.t.id, type=EventType.portfolio_snapshot, at=self.at(d, 23, 0),
             actor="system:import", policy_version=self.version,
             payload={"as_of": d, "reporting_currency": rep, "total": par.pop("all"), "by_branch": par,
                      "simulated": True})

    def run(self):
        hist = self.w.history
        t0, as_of = hist["t0"], self.w.as_of
        by_day = defaultdict(list)
        for o in hist["openings"]:
            by_day[o["open_date"]].append(o)
        d = t0
        while d < as_of:
            for o in by_day.get(d, []):
                self.open(o, d)
            self.day(d)
            self.sweeps(d)
            if d.weekday() == 0 or d == t0:
                self.snapshot(d)
            d += timedelta(days=1)
        # Openings dated today (loans 1 day overdue in today's export).
        for o in by_day.get(as_of, []):
            self.open(o, as_of)
        self.snapshot(as_of)
        # Last night's run: score and put Visit cases on today's lists.
        self.at(as_of - timedelta(days=1), 18, 0)
        score_open_cases(self.s, self.t, "system:scheduler")
        for case in self.s.scalars(select(Case).where(Case.tenant_id == self.t.id, Case.status == "open",
                                                      Case.arm == "treatment", Case.segment == "visit")):
            if case.state not in ("plan_pending", "plan_active"):
                case_svc.assign_visit(self.s, self.t, case, actor="system:scheduler", for_date=as_of, notify=False)
        self.at(as_of, 9, 30)
        score_open_cases(self.s, self.t, "system:scheduler")
