import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, SampleTag, Segment } from "../components/ui";
import Phone from "../mini/Phone";
import { BUCKET_LABEL, dateTime, day, money, toMinor } from "../format";
import { useApp, useFetch } from "../state";

const EVENT_LABEL: Record<string, string> = {
  loan_imported: "Loan imported", case_opened: "Case opened", control_assigned: "Experiment arm assigned",
  scored: "Scored", segment_changed: "Segment changed", bucket_changed: "Bucket changed",
  message_planned: "Message planned", message_blocked: "Message blocked", message_sent: "Message sent",
  message_delivered: "Delivered", message_read: "Read", reply_received: "Reply received",
  reply_classified: "Reply classified", telegram_linked: "Telegram linked", opted_out: "Opted out",
  ptp_created: "Promise to pay", ptp_kept: "Promise kept", ptp_broken: "Promise broken",
  plan_options_generated: "Plan options generated", plan_accepted: "Plan accepted",
  approval_requested: "Approval requested", approval_decided: "Approval decided",
  agreement_generated: "Agreement generated", payment_requested: "Payment requested",
  payment_received: "Payment received", payment_matched: "Payment matched", payment_exported: "Payment exported",
  visit_assigned: "Visit assigned", visit_outcome: "Visit outcome", complaint_opened: "Complaint opened",
  complaint_closed: "Complaint closed", flag_raised: "Flag raised", automation_paused: "Automation paused",
  automation_resumed: "Automation resumed", case_closed: "Case closed", call_logged: "Call logged",
};
const QUIET = new Set(["message_planned", "message_delivered", "scored"]);

function eventSummary(e: any, cur: string): string {
  const p = e.payload ?? {};
  switch (e.type) {
    case "scored": return `priority ${p.priority}, pay ${p.pay_likelihood}, ${p.segment} (${p.segment_rule})`;
    case "segment_changed": return `${p.from ?? "none"} → ${p.to} (${p.rule})`;
    case "control_assigned": return `${p.arm}, stratum ${p.stratum}, position ${p.position_in_stratum}`;
    case "case_opened": return `${p.days_overdue} days, ${money(p.amount_overdue, cur)} overdue`;
    case "message_sent": return `${p.template} v${p.template_version} (${p.language}) via ${p.channel}`;
    case "message_blocked": return `${p.template}: ${p.rule_id} ${p.reason}${p.next_allowed_at ? `; rescheduled ${dateTime(p.next_allowed_at)}` : ""}`;
    case "reply_received": return p.text;
    case "reply_classified": return `${p.label}${p.subtype ? ` (${p.subtype})` : ""}${p.matched ? `, matched "${p.matched}"` : ""}`;
    case "ptp_created": return `${money(p.amount, cur)} by ${p.due_date} (${p.source})`;
    case "plan_options_generated": return `${p.options.length} options; capacity ${p.capacity.monthly_capacity != null ? money(p.capacity.monthly_capacity, cur) + "/month" : "unknown"}`;
    case "plan_accepted": return `${p.type}, ${p.within_policy ? "within policy" : "outside policy: " + p.breaches.map((b: any) => b.label).join(", ")}`;
    case "approval_requested": return `to ${p.approver_role.replace("_", " ")}, SLA ${dateTime(p.sla_due_at)}`;
    case "approval_decided": return `${p.decision} by ${p.approver ?? "?"}${p.within_sla ? " within SLA" : " after SLA"}`;
    case "payment_matched": return `${money(p.amount, cur)} ${p.kind}, by ${p.method}`;
    case "payment_requested": return `${money(p.amount, cur)} ref ${p.reference}`;
    case "flag_raised": return `${p.kind}${p.subtype ? ` (${p.subtype})` : ""}: ${p.text ?? ""}`;
    case "automation_paused": return p.reason;
    case "visit_assigned": return `for ${p.for}`;
    case "case_closed": return p.reason;
    case "telegram_linked": return `via ${p.method?.replace("_", " ")}`;
    case "loan_imported": return `${p.change}, ${p.days_overdue} days overdue`;
    case "agreement_generated": return p.file;
    case "call_logged": return `${p.outcome}${p.note ? `: ${p.note}` : ""}`;
    default: return "";
  }
}

export default function Account() {
  const { id } = useParams();
  const { role, refresh } = useApp();
  const { data: a, error, reload } = useFetch<any>(`/cases/${id}`, [id]);
  const [showAll, setShowAll] = useState(false);
  const [action, setAction] = useState<string>();
  const [form, setForm] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string>();
  if (error) return <ErrorBox error={error} />;
  if (!a) return <Loading />;
  const cur = a.loan.currency;
  const readOnly = role === "leadership";
  const changed = () => { reload(); refresh(); };

  const doAction = async (name: string, body: any = {}) => {
    try {
      const r = await api.post<any>(`/cases/${a.case.id}/actions/${name}`, body);
      setMsg(name === "send_template" ? `Message ${r.status}${r.rule ? `: ${r.rule}` : ""}` : "Done");
      setAction(undefined);
      setForm({});
      changed();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const timeline = a.timeline.filter((e: any) => showAll || !QUIET.has(e.type));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/today" className="text-[12px] text-green-slate">← Today</Link>
        {a.sample && <SampleTag />}
      </div>
      <div className="grid gap-3 xl:grid-cols-[1fr_330px]">
        <div className="min-w-0 space-y-3">
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-[18px] font-semibold">{a.borrower.name}</h1>
                <div className="local text-[14px] text-slate/70">{a.borrower.name_local}</div>
                <div className="mt-1 text-[12px] text-slate/70">
                  {a.borrower.external_id} · {a.borrower.phone ?? "no phone"} · {a.borrower.village} · {a.branch} · officer {a.officer?.name}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Segment value={a.case.segment} />
                <Badge>{BUCKET_LABEL[a.case.bucket]} · {a.loan.days_overdue}d</Badge>
                <Badge tone={a.case.arm === "control" ? "dark" : "neutral"}>{a.case.arm}</Badge>
                <Badge>{a.case.state.replace("_", " ")}</Badge>
                {a.case.paused && <Badge tone="danger">automation paused: {a.case.pause_reason}</Badge>}
                {a.telegram ? <Badge tone={a.telegram.status === "active" ? "good" : "danger"}>Telegram {a.telegram.status}</Badge> : <Badge>Not on Telegram</Badge>}
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] md:grid-cols-4">
              <KV k="Loan" v={`${a.loan.external_id} · ${a.loan.product}`} />
              <KV k="Disbursed" v={`${money(a.loan.principal_disbursed, cur)} on ${day(a.loan.disbursed_on)}`} />
              <KV k="Terms" v={`${a.loan.term} × ${a.loan.frequency}, ${a.loan.rate}% p.a., cycle ${a.loan.cycle}`} />
              <KV k="Instalment" v={money(a.loan.instalment, cur)} />
              <KV k="Principal outstanding" v={money(a.loan.principal_outstanding, cur)} />
              <KV k="Arrears (import)" v={money(a.loan.amount_overdue, cur)} strong />
              <KV k="Arrears now" v={money(a.loan.arrears_now, cur)} strong />
              <KV k="Arrears as of" v={day(a.loan.arrears_as_of)} />
              <KV k="Savings balance" v={money(a.loan.savings_balance, cur)} />
              <KV k="Last repayment" v={day(a.loan.last_repayment_date)} />
              <KV k="Collected in case" v={money(a.case.collected, cur)} />
              <KV k="Appraisal surplus" v={a.loan.appraisal ? money(a.loan.appraisal.household_income - a.loan.appraisal.household_expenses - a.loan.appraisal.other_debt_repayments, cur) + "/mo" : "not in import"} />
            </div>
          </Card>
          <div className="grid gap-3 lg:grid-cols-2">
            <Card title={`Why this case ranks where it does · priority ${a.case.priority?.toFixed(0)}`}>
              <div className="mb-2 flex gap-4 text-[12px]">
                <span>Pay likelihood <b>{a.case.pay_likelihood?.toFixed(0)}</b></span>
                <span>Stake <b>{a.case.stake?.toFixed(0)}</b></span>
                <span className="text-slate/60">segment rule: {a.case.segment_rule}</span>
              </div>
              <ul className="space-y-1">
                {(a.case.reasons ?? []).map((r: any) => (
                  <li key={r.code} className="flex justify-between gap-2 text-[12.5px]">
                    <span>{r.text}</span>
                    <span className={`tabular-nums ${r.impact < 0 ? "text-danger" : r.impact > 0 ? "text-green-slate" : "text-slate/40"}`}>
                      {r.impact ? (r.impact > 0 ? "+" : "") + r.impact : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="Savings deposits (26 weeks)">
              <div className="h-28">
                <ResponsiveContainer>
                  <AreaChart data={a.savings}>
                    <XAxis dataKey="week" hide />
                    <Tooltip formatter={(v: number) => money(v, cur)} labelFormatter={(l) => `Week of ${l}`} />
                    <Area dataKey="balance" stroke="#52796F" fill="#CAD2C5" name="Balance" />
                    <Area dataKey="deposits" stroke="#84A98C" fill="#84A98C" name="Deposits" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {a.group && (
                <div className="mt-2 text-[12px]">
                  <div className="font-semibold">Group: {a.group.name}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {a.group.members.map((m: any) => (
                      <Badge key={m.borrower_id} tone={m.days_overdue > 0 ? "warn" : "good"}>
                        {m.is_self ? "▸ " : ""}{m.name} {m.days_overdue > 0 ? `${m.days_overdue}d` : "current"}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-1 text-[11px] text-slate/60">Group members are never contacted about each other's loans unless the lender enables it and a manager approves.</div>
                </div>
              )}
            </Card>
          </div>
          {!readOnly && (
            <Card title="Actions">
              <div className="flex flex-wrap gap-2">
                {[
                  ["send", "Send a template"], ["call", "Log a call"], ["promise", "Record a promise"],
                  ["plans", "Generate plan options"], ["visit", "Assign a visit"], ["flag", "Flag sensitive"],
                ].map(([k, label]) => (
                  <button key={k} className={`btn ${action === k ? "btn-primary" : ""}`} onClick={() => setAction(action === k ? undefined : k)}>{label}</button>
                ))}
                <button className="btn" onClick={() => doAction("pause", { paused: !a.case.paused })}>
                  {a.case.paused ? "Resume automation" : "Pause automation"}
                </button>
              </div>
              {action === "send" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <select className="input" value={form.template ?? ""} onChange={(e) => setForm({ template: e.target.value })}>
                    <option value="">Next in strategy</option>
                    {["pre_due_reminder", "due_day_reminder", "late_3_days", "late_7_days", "plan_offer", "promise_reminder", "visit_notice", "telegram_invite"].map((k) => <option key={k}>{k}</option>)}
                  </select>
                  <button className="btn btn-primary" onClick={() => doAction("send_template", { template: form.template || null })}>Send through gate</button>
                </div>
              )}
              {action === "call" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <select className="input" value={form.outcome ?? "spoke"} onChange={(e) => setForm({ ...form, outcome: e.target.value })}>
                    {["spoke", "no_answer", "wrong_number", "promised", "refused"].map((k) => <option key={k}>{k}</option>)}
                  </select>
                  <input className="input flex-1" placeholder="Note" value={form.note ?? ""} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                  <button className="btn btn-primary" onClick={() => doAction("log_call", { outcome: form.outcome ?? "spoke", note: form.note })}>Save</button>
                </div>
              )}
              {action === "promise" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <input className="input" placeholder={`Amount (${cur})`} value={form.amount ?? ""} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
                  <input className="input" type="date" value={form.date ?? ""} onChange={(e) => setForm({ ...form, date: e.target.value })} />
                  <button className="btn btn-primary" onClick={() => doAction("record_promise", { amount: toMinor(Number(form.amount), cur), due_date: form.date })}>Save promise</button>
                </div>
              )}
              {action === "plans" && <button className="btn btn-primary mt-2" onClick={() => doAction("generate_plans", {})}>Generate from appraisal</button>}
              {action === "visit" && (
                <div className="mt-2 flex gap-2">
                  <input className="input" type="date" value={form.date ?? ""} onChange={(e) => setForm({ date: e.target.value })} />
                  <button className="btn btn-primary" onClick={() => doAction("assign_visit", { due_date: form.date || null })}>Assign (default next working day)</button>
                </div>
              )}
              {action === "flag" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <select className="input" value={form.kind ?? "vulnerability"} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                    {["vulnerability", "dispute", "deceased", "lender_tag"].map((k) => <option key={k}>{k}</option>)}
                  </select>
                  <input className="input flex-1" placeholder="Note" value={form.note ?? ""} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                  <button className="btn btn-danger" onClick={() => doAction("flag_sensitive", { kind: form.kind ?? "vulnerability", note: form.note })}>Flag and pause</button>
                </div>
              )}
              {msg && <div className="mt-2 rounded bg-bg px-2 py-1 text-[12px]">{msg}</div>}
            </Card>
          )}
          {a.plans.length > 0 && (
            <Card title="Plans" pad={false}>
              <table className="data">
                <thead><tr><th>Option</th><th>Status</th><th className="num">Instalment</th><th className="num">Ext.</th><th>Ends</th><th className="num">Total</th><th>Policy</th><th>Capacity</th></tr></thead>
                <tbody>
                  {a.plans.map((p: any) => (
                    <tr key={p.id}>
                      <td>{p.details.label}</td>
                      <td><Badge tone={p.status === "active" ? "good" : p.status === "pending_approval" ? "warn" : "neutral"}>{p.status.replace("_", " ")}</Badge></td>
                      <td className="num">{money(p.details.new_instalment, cur)}</td>
                      <td className="num">{p.details.extension}</td>
                      <td>{day(p.details.new_end_date)}</td>
                      <td className="num">{money(p.details.total_payable, cur)}</td>
                      <td className="text-[12px]">{p.within_policy ? <Badge tone="good">within v{p.policy_version}</Badge> : p.breaches.map((b: any) => <div key={b.rule} className="text-danger">{b.label}: {b.value} vs {b.limit}</div>)}</td>
                      <td className="text-[12px]">{p.details.affordable ? "fits" : <span className="text-danger">above capacity, not shown</span>}<div className="text-slate/60">{p.capacity.monthly_capacity != null ? money(p.capacity.monthly_capacity, cur) + "/mo" : "?"}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          <Card title={`Timeline (${a.timeline.length} events)`} right={
            <label className="flex items-center gap-1 text-[12px]"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show scoring and delivery events</label>
          } pad={false}>
            <div className="max-h-[520px] overflow-auto">
              <table className="data">
                <tbody>
                  {timeline.map((e: any) => (
                    <tr key={e.id}>
                      <td className="w-32 whitespace-nowrap text-[12px] text-slate/60">{dateTime(e.at)}</td>
                      <td className="w-44 whitespace-nowrap">
                        <span className={e.type === "message_blocked" || e.type === "flag_raised" || e.type === "automation_paused" ? "text-danger" : ""}>{EVENT_LABEL[e.type] ?? e.type}</span>
                      </td>
                      <td className="local text-[12px]">{eventSummary(e, cur)}</td>
                      <td className="whitespace-nowrap text-right text-[11px] text-slate/50">{e.actor} · v{e.policy_version ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
        <div>
          <Phone account={a} onChange={changed} />
        </div>
      </div>
    </div>
  );
}

function KV({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-slate/60">{k}</div>
      <div className={`tabular-nums ${strong ? "font-semibold" : ""}`}>{v}</div>
    </div>
  );
}
