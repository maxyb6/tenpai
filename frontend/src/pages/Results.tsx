import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Card, ErrorBox, Loading, PageHeader, SimulatedTag, Stat, Tip } from "../components/ui";
import { BUCKET_LABEL, day, money, pct } from "../format";
import { useFetch } from "../state";

// Validated pair (scripts/validate_palette.js): treatment teal, control blue.
const TREAT = "#14866A";
const CTRL = "#2a78d6";

const DEF: Record<string, string> = {
  par30: "PAR30 = outstanding principal of loans with any instalment more than 30 days overdue / total outstanding principal",
  cure: "Cure rate = cases returned to current / cases opened, per bucket and period",
  recovery: "Recovery rate = cash collected on cases / amount overdue at case open",
  roll: "Roll rate = share of balance moving to the next bucket in the period",
  promise: "Promise-kept rate = promises kept / promises resolved",
  days: "Days to cure = mean days from case open to cure, cured cases only",
};

export default function Results() {
  const { data: r, error } = useFetch<any>("/results");
  const [traceArm, setTraceArm] = useState<string>();
  if (!r) return error ? <ErrorBox error={error} /> : <Loading />;
  const t = r.by_arm.treatment;
  const c = r.by_arm.control;
  const rep = r.reporting_currency;
  const sim = r.simulated && <SimulatedTag />;
  const latest = r.par_trend[r.par_trend.length - 1];
  const first = r.par_trend[0];
  const compare = [
    { metric: "Cure rate", key: "cure", treatment: t.cure_rate, control: c.cure_rate },
    { metric: "Recovery rate", key: "recovery", treatment: t.recovery_rate, control: c.recovery_rate },
    { metric: "Roll rate", key: "roll", treatment: t.roll_rate, control: c.roll_rate },
    { metric: "Promise kept", key: "promise", treatment: t.promise_kept_rate, control: c.promise_kept_rate },
  ];
  const pctLabel = (v: number) => (v == null ? "" : `${(v * 100).toFixed(0)}%`);

  return (
    <div className="space-y-3">
      <PageHeader question="Is this working?">
        {sim}
        <span className="text-[12px] text-slate/60">Cases opened {day(r.window_start)} to {day(r.as_of)} · policy v{r.policy_version}</span>
      </PageHeader>
      <div className="grid gap-3 lg:grid-cols-[320px_1fr]">
        <div className="card flex flex-col justify-between p-4">
          <div>
            <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-green-slate">
              <Tip text={DEF.par30}>PAR30 today</Tip> {sim}
            </div>
            <div className="mt-1 text-[44px] font-semibold leading-none tabular-nums">{pct(latest.par30)}</div>
            <div className="mt-2 text-[13px] text-slate/70">
              {latest.par30 <= first.par30 ? "down" : "up"} {Math.abs((latest.par30 - first.par30) * 100).toFixed(1)} pts from {pct(first.par30)} eight weeks ago. The number your funders watch.
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
            <div><div className="text-slate/60">PAR1</div><div className="font-semibold">{pct(latest.par1)}</div></div>
            <div><div className="text-slate/60">PAR90</div><div className="font-semibold">{pct(latest.par90)}</div></div>
            <div><div className="text-slate/60">On Telegram</div><div className="font-semibold">{pct(r.telegram_link_rate, 0)}</div></div>
            <div><div className="text-slate/60">Cases measured</div><div className="font-semibold">{r.trace.cases}</div></div>
          </div>
        </div>
        <Card title={<span>PAR30 trend, weekly {sim}</span>}>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={r.par_trend} margin={{ left: 0, right: 16, top: 8 }}>
                <CartesianGrid stroke="#EDF0EA" vertical={false} />
                <XAxis dataKey="date" fontSize={11} tickFormatter={(d) => day(d).slice(0, 6)} stroke="#9AA5A0" />
                <YAxis fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} width={40} stroke="#9AA5A0" domain={[0, "auto"]} />
                <Tooltip formatter={(v: number) => pct(v)} labelFormatter={(d) => `Week of ${day(d)}`} />
                <Line dataKey="par30" name="PAR30" stroke="#2F3E46" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="text-[11px] text-slate/60">From weekly portfolio snapshot events; the last point is today's health check.</div>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="Recovery uplift" value={`${(r.fee.uplift * 100).toFixed(1)} pts`} tone="good" sub={`${pct(t.recovery_rate)} vs ${pct(c.recovery_rate)} control`} tip={DEF.recovery} />
        <Stat label="Cure rate" value={pct(t.cure_rate)} sub={`control ${pct(c.cure_rate)}`} tip={DEF.cure} />
        <Stat label="Days to cure" value={t.days_to_cure ?? "-"} sub={`control ${c.days_to_cure ?? "-"}`} tip={DEF.days} />
        <Stat label="Visits avoided" value={Math.round(r.cost.visits_avoided)} sub={`${money(r.cost.visit_cost_avoided, rep, true)} of officer time`} />
        <Stat label="Fee for the period" value={money(r.fee.total, rep, true)} sub="working below" />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title={<span>Treatment vs control {sim}</span>}>
          <div className="h-60">
            <ResponsiveContainer>
              <BarChart data={compare} margin={{ top: 18, left: 0, right: 8 }} barGap={2} barCategoryGap="28%">
                <CartesianGrid stroke="#EDF0EA" vertical={false} />
                <XAxis dataKey="metric" fontSize={11} stroke="#9AA5A0" />
                <YAxis fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} width={40} stroke="#9AA5A0" />
                <Tooltip formatter={(v: number) => pct(v)} cursor={{ fill: "#F3F6F1" }} />
                <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="treatment" name={`Treatment (${t.cases})`} fill={TREAT} radius={[4, 4, 0, 0]} maxBarSize={36}>
                  <LabelList dataKey="treatment" position="top" fontSize={11} fill="#2F3E46" formatter={pctLabel} />
                </Bar>
                <Bar dataKey="control" name={`Control (${c.cases})`} fill={CTRL} radius={[4, 4, 0, 0]} maxBarSize={36}>
                  <LabelList dataKey="control" position="top" fontSize={11} fill="#2F3E46" formatter={pctLabel} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          {r.significance.cure_rate && (
            <div className={`mb-1 rounded px-2 py-1 text-[12px] ${r.significance.cure_rate.conclusive ? "bg-[#E3EEE6]" : "bg-warn-soft"}`}>
              Cure-rate difference {(r.significance.cure_rate.diff * 100).toFixed(1)} pts, 95% interval {(r.significance.cure_rate.low * 100).toFixed(1)} to {(r.significance.cure_rate.high * 100).toFixed(1)}.{" "}
              {r.significance.cure_rate.conclusive ? "Conclusive at this sample size." : `Not yet conclusive: the control group has ${r.significance.control_cases} cases. It firms up as cases accumulate.`}
            </div>
          )}
          <div className="text-[11px] text-slate/60">
            Roll rate: lower is better. Control promises are those officers took under the lender's existing process.{" "}
            Trace: <button className="underline" onClick={() => setTraceArm("treatment")}>treatment cases</button> ·{" "}
            <button className="underline" onClick={() => setTraceArm("control")}>control cases</button>
          </div>
        </Card>
        <Card title={<span>By bucket at case open {sim}</span>} pad={false}>
          <table className="data">
            <thead>
              <tr><th>Bucket</th><th>Arm</th><th className="num">Cases</th>
                <th className="num"><Tip text={DEF.cure}>Cure</Tip></th><th className="num"><Tip text={DEF.recovery}>Recovery</Tip></th>
                <th className="num"><Tip text={DEF.roll}>Roll</Tip></th><th className="num"><Tip text={DEF.promise}>Promise kept</Tip></th>
                <th className="num"><Tip text={DEF.days}>Days to cure</Tip></th></tr>
            </thead>
            <tbody>
              {r.by_bucket.flatMap((b: any) => (["treatment", "control"] as const).map((arm) => (
                <tr key={b.bucket + arm}>
                  <td>{arm === "treatment" ? BUCKET_LABEL[b.bucket] : ""}</td>
                  <td className="whitespace-nowrap"><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: arm === "treatment" ? TREAT : CTRL }} />{arm}</td>
                  <td className="num">{b[arm].cases}</td>
                  <td className="num">{pct(b[arm].cure_rate, 0)}</td>
                  <td className="num">{pct(b[arm].recovery_rate, 0)}</td>
                  <td className="num">{pct(b[arm].roll_rate, 0)}</td>
                  <td className="num">{pct(b[arm].promise_kept_rate, 0)}</td>
                  <td className="num">{b[arm].days_to_cure ?? ""}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title={<span>Cost {sim}</span>}>
          <table className="data">
            <tbody>
              <tr><td>Officer visits per case, control</td><td className="num">{r.cost.control_visit_rate}</td></tr>
              <tr><td>Officer visits per case, treatment</td><td className="num">{r.cost.treatment_visit_rate}</td></tr>
              <tr><td>Visits avoided = (control rate - treatment rate) x {t.cases} treated cases</td><td className="num font-semibold">{r.cost.visits_avoided}</td></tr>
              <tr><td>Value at {money(r.cost.visit_cost, rep)} per visit</td><td className="num">{money(r.cost.visit_cost_avoided, rep)}</td></tr>
              <tr><td>Messages sent ({money(r.cost.message_cost, rep)} each)</td><td className="num">{r.cost.messages_sent.toLocaleString()}</td></tr>
              <tr><td>Cost per unit recovered, treatment</td><td className="num">{r.cost.treatment_cost_per_unit_recovered?.toFixed(3)}</td></tr>
              <tr><td>Cost per unit recovered, control</td><td className="num">{r.cost.control_cost_per_unit_recovered?.toFixed(3)}</td></tr>
            </tbody>
          </table>
          <div className="mt-1 text-[11px] text-slate/60">Unit costs are editable in Settings.</div>
        </Card>
        <Card title={<span>Fee working {sim}</span>}>
          <div className="mb-2 text-[12px] text-slate/70">{r.fee.formula}; incremental cash = {r.fee.incremental_formula}.</div>
          <table className="data">
            <tbody>
              <tr><td>Treated recovery rate</td><td className="num">{pct(r.fee.treated_recovery_rate, 2)}</td></tr>
              <tr><td>Control recovery rate</td><td className="num">{pct(r.fee.control_recovery_rate, 2)}</td></tr>
              <tr><td>Uplift</td><td className="num">{pct(r.fee.uplift, 2)}</td></tr>
              <tr><td>x Treated overdue balance at case open</td><td className="num">{money(r.fee.treated_opening_balance, rep)}</td></tr>
              <tr><td>= Incremental cash</td><td className="num font-semibold">{money(r.fee.incremental_cash, rep)}</td></tr>
              <tr><td>Success fee {pct(r.fee.success_fee_pct, 0)} x incremental cash</td><td className="num">{money(r.fee.success_fee, rep)}</td></tr>
              <tr><td>Platform fee {money(r.fee.monthly_platform_fee, rep)} x {r.fee.months} months</td><td className="num">{money(r.fee.platform_fee, rep)}</td></tr>
              <tr><td className="font-semibold">Total</td><td className="num font-semibold">{money(r.fee.total, rep)}</td></tr>
            </tbody>
          </table>
        </Card>
      </div>
      {traceArm && <Trace arm={traceArm} onClose={() => setTraceArm(undefined)} />}
      <div className="text-[11px] text-slate/60">
        Sources: {Object.values(r.trace).filter((x) => typeof x === "string").join(" · ")}. Every figure is computed from these events at request time.
        <a className="ml-1 underline" href={api.url("/compliance/messages.csv")}>Message log CSV</a>
      </div>
    </div>
  );
}

function Trace({ arm, onClose }: { arm: string; onClose: () => void }) {
  const { data } = useFetch<any[]>(`/results/trace?arm=${arm}`, [arm]);
  return (
    <Card title={`Cases behind the ${arm} figures (${data?.length ?? "…"})`} right={<button className="btn" onClick={onClose}>Close</button>} pad={false}>
      <div className="max-h-80 overflow-auto">
        <table className="data">
          <thead><tr><th>Case</th><th>Opened</th><th>Bucket</th><th className="num">Overdue at open</th><th className="num">Collected</th><th>Outcome</th><th>Closing event</th></tr></thead>
          <tbody>
            {data?.map((x) => (
              <tr key={x.case_id}>
                <td><Link className="text-green-slate underline" to={`/cases/${x.case_id}`}>#{x.case_id}</Link></td>
                <td>{day(x.opened_at)}</td><td>{BUCKET_LABEL[x.bucket_at_open]}</td>
                <td className="num">{money(x.amount_overdue_at_open, x.currency)}</td><td className="num">{money(x.collected, x.currency)}</td>
                <td>{x.close_reason ?? "open"}</td><td>{x.closed_event_id ? `event #${x.closed_event_id}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
