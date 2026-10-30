import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, PageHeader, SampleTag, Segment, Stat } from "../components/ui";
import { BUCKET_LABEL, money, pct } from "../format";
import { useApp, useFetch } from "../state";

export default function Today() {
  const { meta, role, refresh } = useApp();
  const nav = useNavigate();
  const [f, setF] = useState<Record<string, string>>({});
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const { data, error } = useFetch<any>(`/today${qs ? `?${qs}` : ""}`, [qs]);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [note, setNote] = useState<string>();
  const items: any[] = data?.items ?? [];
  const officers = useMemo(
    () => meta?.officers.filter((o) => !f.branch || o.branch_id === Number(f.branch)) ?? [],
    [meta, f.branch],
  );
  const canBulk = role === "head_of_collections" || role === "branch_manager";

  const bulk = async (action: string) => {
    const r = await api.post<any>("/cases/bulk", { case_ids: [...sel], action });
    setNote(
      `${r.done} done` + (r.blocked ? `, ${r.blocked} blocked by contact rules` : "") +
        (r.skipped_control ? `, ${r.skipped_control} control cases skipped (lender's existing process)` : ""),
    );
    setSel(new Set());
    refresh();
  };
  const c = data?.counters;
  const set = (k: string, v: string) => setF({ ...f, [k]: v });

  return (
    <div className="space-y-3">
      <PageHeader question="Who do we chase today, and how?">{data?.sample && <SampleTag />}</PageHeader>
      <ErrorBox error={error} />
      {c && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-7">
          <Stat label="Open cases" value={c.open_cases} />
          <Stat label="On Telegram" value={pct(c.telegram_link_rate, 0)} tone="warn"
                tip="Telegram link rate of open cases. Caps everything digital." />
          <Stat label="Messages today" value={c.messages_scheduled_today} />
          <Stat label="Blocked by rules" value={c.messages_blocked_today} tone={c.messages_blocked_today ? "warn" : undefined} />
          <Stat label="Plans to approve" value={c.plans_awaiting_approval} tone={c.plans_awaiting_approval ? "danger" : undefined} />
          <Stat label="Visits assigned" value={c.visits_assigned} />
          <Stat label="Promises due today" value={c.promises_due_today} />
        </div>
      )}
      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-sage-pale p-2">
          <input className="input w-48" placeholder="Search borrower or loan" value={f.q ?? ""} onChange={(e) => set("q", e.target.value)} />
          {role !== "branch_manager" && role !== "credit_officer" && (
            <select className="input" value={f.branch ?? ""} onChange={(e) => setF({ ...f, branch: e.target.value, officer: "" })}>
              <option value="">All branches</option>
              {meta?.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
          {role !== "credit_officer" && (
            <select className="input" value={f.officer ?? ""} onChange={(e) => set("officer", e.target.value)}>
              <option value="">All officers</option>
              {officers.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          <select className="input" value={f.bucket ?? ""} onChange={(e) => set("bucket", e.target.value)}>
            <option value="">All buckets</option>
            {Object.entries(BUCKET_LABEL).filter(([k]) => k !== "pre_due").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select className="input" value={f.segment ?? ""} onChange={(e) => set("segment", e.target.value)}>
            <option value="">All segments</option>
            {["nudge", "plan", "visit", "sensitive"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="input" value={f.arm ?? ""} onChange={(e) => set("arm", e.target.value)}>
            <option value="">Treatment + control</option>
            <option value="treatment">Treatment</option>
            <option value="control">Control</option>
          </select>
          <span className="ml-auto text-[12px] text-slate/60">{items.length} cases, highest priority first</span>
        </div>
        {canBulk && sel.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-sage-pale bg-[#F3F6F1] px-3 py-2">
            <span className="font-medium">{sel.size} selected</span>
            <button className="btn btn-primary" onClick={() => bulk("send_reminder")}>Send approved reminder</button>
            <button className="btn" onClick={() => bulk("assign_visit")}>Assign to visit</button>
            <button className="btn" onClick={() => bulk("mark_sensitive")}>Mark sensitive</button>
            <button className="btn" onClick={() => setSel(new Set())}>Clear</button>
          </div>
        )}
        {note && <div className="border-b border-sage-pale bg-bg px-3 py-1.5 text-[12px]">{note}</div>}
        {!data ? (
          <Loading />
        ) : (
          <div className="max-h-[calc(100vh-300px)] overflow-auto">
            <table className="data">
              <thead>
                <tr>
                  {canBulk && (
                    <th>
                      <input
                        type="checkbox"
                        checked={sel.size > 0 && sel.size === items.length}
                        onChange={(e) => setSel(e.target.checked ? new Set(items.map((i) => i.case_id)) : new Set())}
                      />
                    </th>
                  )}
                  <th>Borrower</th><th>Branch / officer</th><th>Bucket</th><th className="num">Overdue</th>
                  <th className="num" title="Priority 0-100: money at stake weighted against likelihood to self-cure">Priority</th>
                  <th className="num" title="Pay likelihood 0-100">Pay %</th>
                  <th>Segment</th><th>Next action</th><th>Why</th><th>Telegram</th><th>Arm</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.case_id} className="clickable" onClick={() => nav(`/cases/${i.case_id}`)}>
                    {canBulk && (
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={sel.has(i.case_id)}
                          onChange={(e) => {
                            const n = new Set(sel);
                            e.target.checked ? n.add(i.case_id) : n.delete(i.case_id);
                            setSel(n);
                          }}
                        />
                      </td>
                    )}
                    <td>
                      <div className="font-medium">{i.borrower}</div>
                      <div className="local text-[11px] text-slate/60">{i.borrower_local}{i.loan_type === "group" ? " · group" : ""}</div>
                    </td>
                    <td>{i.branch}<div className="text-[11px] text-slate/60">{i.officer}</div></td>
                    <td>{BUCKET_LABEL[i.bucket]}<div className="text-[11px] text-slate/60">{i.days_overdue}d</div></td>
                    <td className="num">{money(i.amount_overdue, i.currency)}</td>
                    <td className="num font-semibold">{i.priority?.toFixed(0)}</td>
                    <td className="num">{i.pay_likelihood?.toFixed(0)}</td>
                    <td><Segment value={i.segment} />{i.paused && <div className="mt-0.5"><Badge tone="danger">paused</Badge></div>}</td>
                    <td className="text-[12px]">{i.next_action}</td>
                    <td className="max-w-[320px] text-[12px] text-slate/80">
                      {i.reasons.slice(0, 3).map((r: any) => (
                        <span key={r.code} className={`mr-1 inline-block ${r.impact < 0 ? "text-danger" : r.impact > 0 ? "text-green-slate" : ""}`}>
                          {r.text}.
                        </span>
                      ))}
                    </td>
                    <td>{i.telegram ? <Badge tone="good">linked</Badge> : <Badge>no</Badge>}</td>
                    <td>{i.arm === "control" ? <Badge tone="dark" title="Gets the lender's existing process; Tenpai does not contact">control</Badge> : <span className="text-[12px] text-slate/60">treatment</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
