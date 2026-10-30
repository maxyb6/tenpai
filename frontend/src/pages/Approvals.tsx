import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, PageHeader, SampleTag } from "../components/ui";
import { day, money } from "../format";
import { useApp, useFetch } from "../state";

function useTick() {
  const [, set] = useState(0);
  useEffect(() => {
    const i = setInterval(() => set((x) => x + 1), 30_000);
    return () => clearInterval(i);
  }, []);
}

const sla = (s: number) => {
  if (s <= 0) return <Badge tone="danger">SLA breached {Math.round(-s / 3600)}h ago</Badge>;
  const h = Math.floor(s / 3600);
  return <Badge tone={h < 4 ? "warn" : "neutral"}>{h}h {Math.floor((s % 3600) / 60)}m left</Badge>;
};

export default function Approvals() {
  useTick();
  const { refresh, role } = useApp();
  const [status, setStatus] = useState("pending");
  const { data, error, reload } = useFetch<any>(`/approvals?status=${status}`, [status]);
  const [msg, setMsg] = useState<string>();
  const decide = async (id: number, decision: string, counter?: number) => {
    try {
      await api.post(`/approvals/${id}/decide`, { decision, counter_plan_id: counter });
      setMsg(`Approval ${decision}d`);
      reload();
      refresh();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  return (
    <div className="space-y-3">
      <PageHeader question="What needs my sign-off?">
        {data?.sample && <SampleTag />}
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Pending</option><option value="all">All</option>
        </select>
      </PageHeader>
      <ErrorBox error={error} />
      {msg && <div className="rounded bg-white px-3 py-2 text-[12px]">{msg}</div>}
      {!data ? <Loading /> : !data.items.length ? (
        <Card><div className="text-slate/60">Nothing waiting{role === "branch_manager" ? " for your branch" : ""}.</div></Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {data.items.map((a: any) => {
            const d = a.plan?.details;
            const cur = a.currency;
            return (
              <Card key={a.id} title={<span><Link className="text-green-slate hover:underline" to={`/cases/${a.case_id}`}>{a.borrower}</Link> <span className="local font-normal text-slate/60">{a.borrower_local}</span></span>}
                right={a.status === "pending" ? sla(a.sla_seconds_left) : <Badge tone={a.status === "approved" ? "good" : "neutral"}>{a.status} by {a.decided_by}</Badge>}>
                <div className="text-[12px] text-slate/70">{a.branch} · officer {a.officer} · {a.loan} · {a.days_overdue} days · arrears {money(a.amount_overdue, cur)}</div>
                {d && (
                  <table className="data mt-2">
                    <thead><tr><th></th><th className="num">Original</th><th className="num">Proposed: {d.label}</th></tr></thead>
                    <tbody>
                      <tr><td>Instalment</td><td className="num">{money(a.original.instalment, cur)}</td><td className="num font-semibold">{money(d.new_instalment, cur)}{d.relief_periods ? ` (first ${d.relief_periods}: ${money(d.relief_instalment, cur)})` : ""}</td></tr>
                      <tr><td>Instalments left</td><td className="num">{d.instalments - d.extension}</td><td className="num">{d.instalments} (+{d.extension})</td></tr>
                      <tr><td>Ends</td><td className="num">{day(a.original.end_date)}</td><td className="num">{day(d.new_end_date)}</td></tr>
                      <tr><td>Total to pay</td><td className="num">{money(d.original_total, cur)}</td><td className="num">{money(d.total_payable, cur)}</td></tr>
                      <tr><td>Capacity per instalment</td><td className="num" colSpan={2}>{money(d.capacity_per_period, cur)} <span className="text-[11px] text-slate/60">({a.plan.capacity.method})</span></td></tr>
                    </tbody>
                  </table>
                )}
                <div className="mt-2 space-y-1">
                  {a.breaches.map((b: any) => (
                    <div key={b.rule} className="rounded border border-danger/30 bg-danger-soft px-2 py-1 text-[12.5px] text-danger">
                      Breaches <b>{b.label}</b>: {b.value} vs limit {b.limit}{b.over != null ? `, over by ${b.over} ${b.unit ?? ""}` : ""}
                    </div>
                  ))}
                  {a.officer_note && <div className="text-[12px]">Officer note: {a.officer_note}</div>}
                </div>
                {a.status === "pending" && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button className="btn btn-primary" onClick={() => decide(a.id, "approve")}>Approve</button>
                    <button className="btn btn-danger" onClick={() => decide(a.id, "reject")}>Reject</button>
                    {a.alternatives.filter((x: any) => x.affordable).map((x: any) => (
                      <button key={x.id} className="btn" onClick={() => decide(a.id, "counter", x.id)}>
                        Counter: {x.type.replace("_", " ")} {money(x.new_instalment, cur)}{x.within_policy ? "" : " (outside policy)"}
                      </button>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
