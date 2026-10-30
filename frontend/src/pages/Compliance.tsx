import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, PageHeader, SampleTag, Stat } from "../components/ui";
import { dateTime } from "../format";
import { useApp, useFetch } from "../state";

export default function Compliance() {
  const { refresh, role } = useApp();
  const { data, error, reload } = useFetch<any>("/compliance");
  const [rule, setRule] = useState("");
  const [status, setStatus] = useState("");
  const qs = new URLSearchParams(Object.entries({ rule, status }).filter(([, v]) => v)).toString();
  const { data: log } = useFetch<any[]>(`/compliance/messages${qs ? `?${qs}` : ""}`, [qs]);
  const [open, setOpen] = useState<number>();
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const act = async (path: string, body: any) => {
    await api.post(path, body);
    reload();
    refresh();
  };
  const blockedTotal = data.blocked_by_rule.reduce((a: number, b: any) => a + b.count, 0);
  const canAct = role === "head_of_collections" || role === "branch_manager";
  return (
    <div className="space-y-3">
      <PageHeader question="Can we prove we treat borrowers fairly?">
        {data.sample && <SampleTag />}
        <a className="btn" href={api.url(`/compliance/messages.csv${qs ? `?${qs}` : ""}`)}>Export message log</a>
      </PageHeader>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="Messages sent" value={data.messages_sent.toLocaleString()} />
        <Stat label="Stopped by contact rules" value={blockedTotal} tone="good" sub="logged with rule ID" />
        <Stat label="On Telegram (consented)" value={data.consent.linked} sub={`${data.consent.opted_out} opted out`} />
        <Stat label="Vulnerability & dispute flags" value={data.flags.length} sub={`${data.flags.filter((f: any) => !f.reviewed_at).length} awaiting review`} tone={data.flags.some((f: any) => !f.reviewed_at) ? "warn" : undefined} />
        <Stat label="Complaints" value={data.complaints.length} sub={`${data.complaints.filter((c: any) => c.status !== "closed").length} open, ${data.complaints.filter((c: any) => c.overdue).length} past SLA`} />
      </div>
      <div className="grid gap-3 lg:grid-cols-[360px_1fr]">
        <Card title="Contact-limit breaches prevented, by rule" pad={false}>
          <table className="data">
            <tbody>
              {data.blocked_by_rule.map((b: any) => (
                <tr key={b.rule} className="clickable" onClick={() => { setRule(b.rule); setStatus("blocked"); }}>
                  <td className="whitespace-nowrap font-mono text-[12px]">{b.rule}</td><td>{b.name}</td><td className="num">{b.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card pad={false} title="Message log" right={
          <div className="flex gap-1">
            <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>{["blocked", "planned", "sent", "delivered", "read"].map((s) => <option key={s}>{s}</option>)}
            </select>
            <select className="input" value={rule} onChange={(e) => setRule(e.target.value)}>
              <option value="">All rules</option>{data.blocked_by_rule.map((b: any) => <option key={b.rule} value={b.rule}>{b.rule}</option>)}
            </select>
          </div>}>
          <div className="max-h-[420px] overflow-auto">
            <table className="data">
              <thead><tr><th>Planned</th><th>Borrower</th><th>Template</th><th>Status</th><th>Rule</th><th className="num">Policy</th><th>Sent / read</th></tr></thead>
              <tbody>
                {log?.map((m) => (
                  <>
                    <tr key={m.id} className="clickable" onClick={() => setOpen(open === m.id ? undefined : m.id)}>
                      <td className="whitespace-nowrap">{dateTime(m.planned_at)}</td>
                      <td>{m.case_id ? <Link className="text-green-slate hover:underline" onClick={(e) => e.stopPropagation()} to={`/cases/${m.case_id}`}>{m.borrower}</Link> : m.borrower}</td>
                      <td className="text-[12px]">{m.template} v{m.template_version} · {m.language} · {m.channel}</td>
                      <td><Badge tone={m.status === "blocked" ? "danger" : m.status === "read" ? "good" : "neutral"}>{m.status}</Badge></td>
                      <td className="text-[12px]">{m.rule ? <span title={m.rule_name}>{m.rule}</span> : ""}{m.next_allowed_at ? <div className="text-slate/60">next {dateTime(m.next_allowed_at)}</div> : ""}</td>
                      <td className="num">v{m.policy_version}</td>
                      <td className="whitespace-nowrap text-[12px]">{dateTime(m.sent_at)}{m.read_at ? ` · read ${dateTime(m.read_at)}` : ""}</td>
                    </tr>
                    {open === m.id && (
                      <tr key={`${m.id}-x`}>
                        <td colSpan={7} className="bg-[#F7F8F5]">
                          <div className="local text-[13px]">{m.body}</div>
                          <div className="text-[12px] text-slate/60">{m.shadow}</div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {m.trace?.map((t: any) => (
                              <Badge key={t.rule} tone={t.result === "block" ? "danger" : t.result === "exempt" ? "warn" : "good"} title={`${t.name}: ${t.detail}`}>
                                {t.rule} {t.result}
                              </Badge>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Vulnerability flags" pad={false}>
          <div className="max-h-80 overflow-auto">
            <table className="data">
              <thead><tr><th>Raised</th><th>Borrower</th><th>Flag</th><th>Inbound text / note</th><th>Review</th></tr></thead>
              <tbody>
                {data.flags.map((f: any) => (
                  <tr key={f.id}>
                    <td className="whitespace-nowrap">{dateTime(f.raised_at)}</td>
                    <td>{f.case_id ? <Link className="text-green-slate hover:underline" to={`/cases/${f.case_id}`}>{f.borrower}</Link> : f.borrower}</td>
                    <td><Badge tone="danger">{f.kind}{f.subtype ? `: ${f.subtype}` : ""}</Badge><div className="text-[11px] text-slate/60">{f.source.replace("_", " ")}</div></td>
                    <td className="local text-[12px]">{f.text}</td>
                    <td className="text-[12px]">
                      {f.reviewed_at ? <span>{f.reviewer}: {f.outcome}</span> : canAct ? (
                        <div className="flex flex-wrap gap-1">
                          <button className="btn" onClick={() => act(`/compliance/flags/${f.id}/review`, { outcome: "Confirmed; keep paused, manager owns case", resume: false })}>Keep paused</button>
                          <button className="btn" onClick={() => act(`/compliance/flags/${f.id}/review`, { outcome: "Reviewed; safe to resume", resume: true })}>Resume</button>
                        </div>
                      ) : <Badge tone="warn">awaiting review</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Complaints" pad={false}>
          <div className="max-h-80 overflow-auto">
            <table className="data">
              <thead><tr><th>Ref</th><th>Borrower</th><th>Text</th><th>SLA</th><th>Status</th></tr></thead>
              <tbody>
                {data.complaints.map((c: any) => (
                  <tr key={c.id}>
                    <td>{c.ref}<div className="text-[11px] text-slate/60">{c.source}</div></td>
                    <td>{c.case_id ? <Link className="text-green-slate hover:underline" to={`/cases/${c.case_id}`}>{c.borrower}</Link> : c.borrower}</td>
                    <td className="local text-[12px]">{c.text}</td>
                    <td className="whitespace-nowrap text-[12px]">{dateTime(c.sla_due_at)}{c.overdue && <div><Badge tone="danger">past SLA</Badge></div>}</td>
                    <td>{c.status === "closed" ? <span className="text-[12px]">closed: {c.resolution}</span> : canAct ? (
                      <button className="btn" onClick={() => { const r = prompt("Resolution"); if (r) act(`/compliance/complaints/${c.id}/close`, { resolution: r }); }}>Close</button>
                    ) : <Badge tone="warn">{c.status}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Consent records" pad={false}>
          <div className="flex flex-wrap gap-1 p-2">
            {Object.entries(data.consent.by_method).map(([k, v]) => <Badge key={k}>{k.replace("_", " ")}: {v as number}</Badge>)}
          </div>
          <div className="max-h-64 overflow-auto">
            <table className="data">
              <thead><tr><th>Borrower</th><th>Opted in</th><th>How</th><th>Consent text</th><th>Status</th></tr></thead>
              <tbody>
                {data.consent.recent.map((l: any, i: number) => (
                  <tr key={i}><td>{l.borrower}</td><td>{dateTime(l.linked_at)}</td><td>{l.method.replace("_", " ")}{l.phone_verified ? ", phone shared" : ""}</td>
                    <td>{l.consent_version}</td><td>{l.status === "opted_out" ? <Badge tone="danger">opted out {dateTime(l.opted_out_at)}</Badge> : <Badge tone="good">active</Badge>}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Charter charter={data.charter} onSaved={reload} />
      </div>
    </div>
  );
}

function Charter({ charter, onSaved }: { charter: Record<string, { title: string; body: string }[]>; onSaved: () => void }) {
  const { role, meta } = useApp();
  const langs = Object.keys(charter);
  const [lang, setLang] = useState(meta?.tenant.market === "MM" ? "my" : meta?.tenant.market === "KH" ? "km" : "en");
  const [draft, setDraft] = useState<Record<string, { title: string; body: string }[]>>(charter);
  const [saved, setSaved] = useState(false);
  const items = draft[lang] ?? [];
  const save = async () => {
    await api.put("/settings/brand", { charter: draft });
    setSaved(true);
    onSaved();
  };
  return (
    <Card title="Borrower charter (published in the Mini App)" right={
      <select className="input" value={lang} onChange={(e) => setLang(e.target.value)}>{langs.map((l) => <option key={l}>{l}</option>)}</select>}>
      <div className="space-y-2">
        {items.map((it, i) => (
          <div key={i} className="local">
            <input className="input w-full font-semibold" value={it.title} disabled={role !== "head_of_collections"}
              onChange={(e) => setDraft({ ...draft, [lang]: items.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} />
            <textarea className="input mt-1 w-full" rows={2} value={it.body} disabled={role !== "head_of_collections"}
              onChange={(e) => setDraft({ ...draft, [lang]: items.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)) })} />
          </div>
        ))}
        {role === "head_of_collections" && <button className="btn btn-primary" onClick={save}>{saved ? "Saved" : "Save charter"}</button>}
        {lang !== "en" && <div className="text-[11px] text-slate/60">Draft translation, needs native review.</div>}
      </div>
    </Card>
  );
}
