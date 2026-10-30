import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, PageHeader, SampleTag, Stat } from "../components/ui";
import { dateTime, money } from "../format";
import { useApp, useFetch } from "../state";

export default function Payments() {
  const { refresh } = useApp();
  const [status, setStatus] = useState("");
  const { data, error, reload } = useFetch<any>(`/payments${status ? `?status=${status}` : ""}`, [status]);
  const [fromState, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [msg, setMsg] = useState<string>();
  const [matchFor, setMatchFor] = useState<number>();
  const [loanNo, setLoanNo] = useState("");
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const c = data.counts;
  // Default range starts the day after the last exported batch.
  const lastTo = data.batches[0]?.to;
  const from = fromState || (lastTo ? new Date(new Date(lastTo).getTime() + 86400000).toISOString().slice(0, 10) : data.today);
  const run = async (fn: () => Promise<any>, ok: (r: any) => string) => {
    try {
      const r = await fn();
      setMsg(ok(r));
      reload();
      refresh();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  return (
    <div className="space-y-3">
      <PageHeader question="Has the money arrived, and is it posted?">
        {data.sample && <SampleTag />}
        <a className="btn" href={api.url("/restructure-export.csv")}>Restructure export (CSV)</a>
      </PageHeader>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
        <Stat label="Payment requests" value={c.requests} sub={`${c.requests_open} open`} />
        <Stat label="Received" value={c.received} />
        <Stat label="Matched" value={c.matched ?? 0} tone="good" />
        <Stat label="Unmatched" value={c.unmatched ?? 0} tone={c.unmatched ? "danger" : undefined} sub="manual queue" />
        <Stat label="Reversed" value={c.reversed ?? 0} />
        <Stat label="Awaiting export" value={c.awaiting_export} tone={c.awaiting_export ? "warn" : undefined} sub="not yet in a Mifos file" />
      </div>
      <Card title="Mifos posting file (loan repayments)" right={<span className="text-[12px] text-slate/60">Each payment can be exported once, ever</span>}>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[12px]">From<br /><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="text-[12px]">To<br /><input type="date" className="input" value={to || data.today} onChange={(e) => setTo(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={!from}
            onClick={() => run(() => api.post("/posting-batches", { date_from: from, date_to: to || data.today }),
              (r) => `Batch ${r.id}: ${r.rows} payments in ${r.file}`)}>
            Generate posting file
          </button>
          <span className="text-[12px] text-slate/60">
            Columns: {data.columns.map((x: any) => x.header).join(" · ")}. Confirm against your Mifos version.
          </span>
        </div>
        {data.batches.length > 0 && (
          <table className="data mt-3">
            <thead><tr><th>Batch</th><th>Created</th><th>Range</th><th className="num">Rows</th><th>By</th><th></th></tr></thead>
            <tbody>
              {data.batches.map((b: any) => (
                <tr key={b.id}>
                  <td>#{b.id}</td><td>{dateTime(b.created_at)}</td><td>{b.from} to {b.to}</td><td className="num">{b.rows}</td><td>{b.by}</td>
                  <td><a className="text-green-slate underline" href={api.url(`/posting-batches/${b.id}.csv`)}>{b.file}</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {msg && <div className="rounded bg-white px-3 py-2 text-[12px]">{msg}</div>}
      <Card pad={false} title="Payments" right={
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option><option value="matched">Matched</option><option value="unmatched">Unmatched</option><option value="reversed">Reversed</option>
        </select>}>
        <div className="max-h-[520px] overflow-auto">
          <table className="data">
            <thead><tr><th>Paid</th><th>Borrower / loan</th><th className="num">Amount</th><th>Reference</th><th>Status</th><th>Matched by</th><th>Kind</th><th>Exported</th><th></th></tr></thead>
            <tbody>
              {data.items.map((p: any) => (
                <tr key={p.id}>
                  <td className="whitespace-nowrap">{dateTime(p.paid_at)}</td>
                  <td>{p.case_id ? <Link className="text-green-slate hover:underline" to={`/cases/${p.case_id}`}>{p.borrower}</Link> : p.borrower ?? <span className="text-slate/50">unknown</span>}
                    <div className="text-[11px] text-slate/60">{p.loan}</div></td>
                  <td className="num">{money(p.amount, p.currency)}</td>
                  <td className="text-[12px]">{p.reference ?? "-"}<div className="text-slate/50">{p.txn}</div></td>
                  <td><Badge tone={p.status === "matched" ? "good" : p.status === "unmatched" ? "danger" : "neutral"}>{p.status}</Badge></td>
                  <td className="text-[12px]">{p.method}</td>
                  <td className="text-[12px]">{p.kind}</td>
                  <td>{p.exported ? <Badge>exported</Badge> : ""}</td>
                  <td className="whitespace-nowrap">
                    {p.status === "unmatched" && (matchFor === p.id ? (
                      <span className="flex gap-1"><input className="input w-36" placeholder="Loan account no." value={loanNo} onChange={(e) => setLoanNo(e.target.value)} />
                        <button className="btn btn-primary" onClick={() => run(() => api.post(`/payments/${p.id}/match`, { loan_external_id: loanNo }), () => "Matched")}>Match</button></span>
                    ) : <button className="btn" onClick={() => { setMatchFor(p.id); setLoanNo(""); }}>Match manually</button>)}
                    {p.status === "matched" && (
                      <button className="btn" onClick={() => confirm("Reverse this payment?") && run(() => api.post(`/payments/${p.id}/reverse`), (r) => r.note ?? "Reversed")}>Reverse</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <UnmatchedDemo onDone={() => { reload(); refresh(); }} />
    </div>
  );
}

function UnmatchedDemo({ onDone }: { onDone: () => void }) {
  const { meta } = useApp();
  if (!meta?.tenant.is_demo) return null;
  return (
    <div className="text-[12px] text-slate/60">
      Demo:{" "}
      <button className="underline" onClick={() => api.post("/demo/pay", { unmatched: true }).then(onDone)}>
        simulate a payment with no reference
      </button>{" "}
      to see the manual queue.
    </div>
  );
}
