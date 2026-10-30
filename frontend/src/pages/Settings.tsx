import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Card, DraftTag, ErrorBox, Loading, PageHeader, Segment } from "../components/ui";
import { BUCKET_LABEL, dateTime, money, ROLE_LABEL } from "../format";
import { useApp, useFetch } from "../state";

const TABS = ["Policy", "Strategy", "Contact rules", "Ranking", "Scripts", "Brand", "Integrations", "Users"] as const;

export default function Settings() {
  const { refresh } = useApp();
  const { data, error, reload } = useFetch<any>("/settings");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Policy");
  const [draft, setDraft] = useState<any>();
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string>();
  useEffect(() => {
    if (data) setDraft(structuredClone(data.policy));
  }, [data]);
  if (!data || !draft) return error ? <ErrorBox error={error} /> : <Loading />;
  const set = (path: string[], value: any) => {
    const next = structuredClone(draft);
    let o = next;
    for (const k of path.slice(0, -1)) o = o[k];
    o[path[path.length - 1]] = value;
    setDraft(next);
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.policy);
  const save = async () => {
    try {
      const r = await api.put<any>("/settings/policy", { data: draft, note: note || null });
      setMsg(`Saved as policy v${r.version}. Open cases rescored; earlier decisions keep their version.`);
      setNote("");
      reload();
      refresh();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const policyTabs = ["Policy", "Strategy", "Contact rules", "Ranking"].includes(tab);

  return (
    <div className="space-y-3">
      <PageHeader question="What are our rules?">
        <Badge tone="dark">policy v{data.policy_version}</Badge>
      </PageHeader>
      <div className="flex flex-wrap gap-1 border-b border-sage-pale">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`px-3 py-2 text-[13px] ${tab === t ? "border-b-2 border-green-slate font-semibold" : "text-slate/70"}`}>{t}</button>
        ))}
      </div>
      {policyTabs && dirty && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-warn bg-warn-soft px-3 py-2">
          <span>Unsaved changes create policy v{data.policy_version + 1}. Nothing applies retroactively.</span>
          <input className="input flex-1" placeholder="What changed and why" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn btn-primary" onClick={save}>Save new version</button>
          <button className="btn" onClick={() => setDraft(structuredClone(data.policy))}>Discard</button>
        </div>
      )}
      {msg && <div className="rounded bg-white px-3 py-2 text-[12px]">{msg}</div>}

      {tab === "Policy" && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="Restructure plans">
            <Num label="Max tenor extension (instalments)" v={draft.plans.max_tenor_extension_instalments} on={(v) => set(["plans", "max_tenor_extension_instalments"], v)} />
            <Num label="Max restructures per loan" v={draft.plans.max_restructures_per_loan} on={(v) => set(["plans", "max_restructures_per_loan"], v)} />
            {Object.entries(draft.plans.min_instalment).map(([c, v]) => (
              <Num key={c} label={`Minimum instalment (${c}, minor units)`} v={v as number} on={(x) => set(["plans", "min_instalment", c], x)} />
            ))}
            <Num label="Max share of surplus a plan may take" v={draft.plans.max_share_of_surplus} step={0.05} on={(v) => set(["plans", "max_share_of_surplus"], v)} />
            <Num label="Max penalty waiver (share)" v={draft.plans.max_penalty_waiver_pct} step={0.1} on={(v) => set(["plans", "max_penalty_waiver_pct"], v)} />
            <Num label="Max interest waiver (share)" v={draft.plans.max_interest_waiver_pct} step={0.1} on={(v) => set(["plans", "max_interest_waiver_pct"], v)} />
            {Object.entries(draft.plans.auto_approval_ceiling).map(([c, v]) => (
              <Num key={c} label={`Auto-approval ceiling, arrears (${c}, minor units)`} v={v as number} on={(x) => set(["plans", "auto_approval_ceiling", c], x)} />
            ))}
            <Num label="Catch-up: spread arrears over up to N instalments" v={draft.plans.catch_up_max_instalments} on={(v) => set(["plans", "catch_up_max_instalments"], v)} />
            <Num label="Short relief periods" v={draft.plans.short_relief_periods} on={(v) => set(["plans", "short_relief_periods"], v)} />
            <label className="mt-2 block text-[12px]">Eligible products (one per line)
              <textarea className="input mt-1 w-full" rows={3} value={draft.plans.eligible_products.join("\n")}
                onChange={(e) => set(["plans", "eligible_products"], e.target.value.split("\n").filter(Boolean))} /></label>
          </Card>
          <div className="space-y-3">
            <Card title="Who approves what">
              <table className="data"><thead><tr><th>Kind</th><th>Approver</th><th>Up to (arrears)</th></tr></thead>
                <tbody>{draft.approvals.map((a: any, i: number) => (
                  <tr key={i}><td>{a.kind.replace("_", " ")}</td><td>{ROLE_LABEL[a.approver_role]}</td>
                    <td>{a.max_amount ? Object.entries(a.max_amount).map(([c, v]) => money(v as number, c)).join(", ") : "no limit"}</td></tr>
                ))}</tbody></table>
            </Card>
            <Card title="Control group and SLAs">
              <Num label="Control share" v={draft.control.share} step={0.01} on={(v) => set(["control", "share"], v)} />
              <Num label="Block size (stratified permuted blocks)" v={draft.control.block_size} on={(v) => set(["control", "block_size"], v)} />
              <Num label="Approval SLA (hours)" v={draft.slas.approval_hours} on={(v) => set(["slas", "approval_hours"], v)} />
              <Num label="Complaint SLA (hours)" v={draft.slas.complaint_hours} on={(v) => set(["slas", "complaint_hours"], v)} />
              <div className="mt-1 text-[11px] text-slate/60">A case's arm is locked when it opens; changing the share affects new cases only.</div>
            </Card>
            <Card title="Unit costs and fee">
              {Object.entries(draft.visit_cost).map(([c, v]) => <Num key={c} label={`Cost per officer visit (${c}, minor units)`} v={v as number} on={(x) => set(["visit_cost", c], x)} />)}
              {Object.entries(draft.message_cost).map(([c, v]) => <Num key={c} label={`Cost per message (${c}, minor units)`} v={v as number} on={(x) => set(["message_cost", c], x)} />)}
              <Num label={`Monthly platform fee (${draft.fee.currency}, minor units)`} v={draft.fee.monthly_platform_fee} on={(v) => set(["fee", "monthly_platform_fee"], v)} />
              <Num label="Success fee (share of incremental cash)" v={draft.fee.success_fee_pct} step={0.01} on={(v) => set(["fee", "success_fee_pct"], v)} />
            </Card>
          </div>
          <Versions versions={data.versions} />
        </div>
      )}

      {tab === "Strategy" && (
        <Card title="Strategy per bucket" pad={false}>
          <table className="data">
            <thead><tr><th>Bucket</th><th>Days</th><th>Channel</th><th>Templates in order</th><th className="num">Attempts</th><th className="num">Days between</th><th className="num">Visit after N unanswered</th><th>Visit on broken promise</th></tr></thead>
            <tbody>
              {draft.strategy.map((s: any, i: number) => {
                const b = draft.buckets.find((x: any) => x.key === s.bucket);
                return (
                  <tr key={s.bucket}>
                    <td>{BUCKET_LABEL[s.bucket]}</td>
                    <td>{b.min_days} to {b.max_days ?? "∞"}</td>
                    <td>{s.channel}</td>
                    <td><input className="input w-full" value={s.templates.join(", ")} onChange={(e) => set(["strategy", String(i), "templates"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></td>
                    <td className="num"><input type="number" className="input w-16" value={s.attempts} onChange={(e) => set(["strategy", String(i), "attempts"], Number(e.target.value))} /></td>
                    <td className="num"><input type="number" className="input w-16" value={s.days_between_attempts} onChange={(e) => set(["strategy", String(i), "days_between_attempts"], Number(e.target.value))} /></td>
                    <td className="num"><input type="number" className="input w-16" value={s.escalate_to_visit_after_attempts ?? ""} placeholder="never" onChange={(e) => set(["strategy", String(i), "escalate_to_visit_after_attempts"], e.target.value === "" ? null : Number(e.target.value))} /></td>
                    <td><input type="checkbox" checked={s.escalate_on_broken_promise} onChange={(e) => set(["strategy", String(i), "escalate_on_broken_promise"], e.target.checked)} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {tab === "Contact rules" && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="Limits">
            <Txt label="Quiet hours start (nothing at or after)" v={draft.contact.quiet_hours_start} on={(v) => set(["contact", "quiet_hours_start"], v)} />
            <Txt label="Quiet hours end (nothing before)" v={draft.contact.quiet_hours_end} on={(v) => set(["contact", "quiet_hours_end"], v)} />
            <Num label="Max outbound per day (all channels)" v={draft.contact.max_per_day} on={(v) => set(["contact", "max_per_day"], v)} />
            <Num label="Max outbound per week (all channels)" v={draft.contact.max_per_week} on={(v) => set(["contact", "max_per_week"], v)} />
            <Chk label="Sundays off" v={draft.contact.sundays_off} on={(v) => set(["contact", "sundays_off"], v)} />
            <Chk label="Replies to the borrower's own action skip quiet hours and caps" v={draft.contact.transactional_exempt_from_limits} on={(v) => set(["contact", "transactional_exempt_from_limits"], v)} />
            <Chk label="Allow contact with group members / guarantors (needs manager approval per case)" v={draft.contact.third_party_contact_enabled} on={(v) => set(["contact", "third_party_contact_enabled"], v)} />
            <div className="mt-2 text-[12px]">Automation stops on: {draft.contact.stop_on.map((x: string) => <Badge key={x}>{x.replace("_", " ")}</Badge>)}</div>
          </Card>
          <Card title="Quiet days">
            <textarea className="input w-full font-mono text-[12px]" rows={14}
              value={draft.contact.holidays.map((h: any) => `${h.date} ${h.name}`).join("\n")}
              onChange={(e) => set(["contact", "holidays"], e.target.value.split("\n").filter((l) => /^\d{4}-\d{2}-\d{2}/.test(l)).map((l) => ({ date: l.slice(0, 10), name: l.slice(11) || "Holiday" })))} />
            <div className="text-[11px] text-slate/60">One per line: YYYY-MM-DD name. Lunar dates need confirming each year.</div>
          </Card>
          <Card title="Banned phrases (checked when a script is approved and at every send)">
            {Object.entries(draft.contact.banned_phrases).map(([lang, list]) => (
              <label key={lang} className="mb-2 block text-[12px]">{lang}
                <textarea className="input local mt-1 w-full" rows={2} value={(list as string[]).join(", ")}
                  onChange={(e) => set(["contact", "banned_phrases", lang], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></label>
            ))}
          </Card>
          <Card title="Send gate rule IDs">
            <table className="data"><tbody>{Object.entries(data.rules).map(([k, v]) => <tr key={k}><td className="font-mono text-[12px]">{k}</td><td>{v as string}</td></tr>)}</tbody></table>
          </Card>
        </div>
      )}

      {tab === "Ranking" && <Ranking draft={draft} set={set} />}
      {tab === "Scripts" && <Scripts templates={data.templates} onChange={reload} />}
      {tab === "Brand" && <Brand brand={data.brand} onSaved={() => { reload(); refresh(); }} />}
      {tab === "Integrations" && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="Core banking (Mifos X)">
            <div className="text-[12px]">Saved column mappings:</div>
            {data.integrations.mappings.length ? data.integrations.mappings.map((m: any) => (
              <div key={m.name + m.kind} className="mt-1"><Badge>{m.kind}</Badge> {m.name} · {Object.keys(m.mapping).length} fields</div>
            )) : <div className="text-slate/60">None yet: the first import saves one.</div>}
            <div className="mt-2 text-[12px] text-slate/60">Posting back to Mifos is by file (bulk import), not API. Confirm the column layout against your Mifos version.</div>
          </Card>
          <Card title="Payments">
            <div>Provider: {data.integrations.payment_provider}</div>
            <div className="mt-1 text-[12px] text-slate/60">Borrowers pay into your own account at the partner bank or wallet; Tenpai only receives notifications and matches them.</div>
          </Card>
          <Card title="Telegram">
            <div>{data.integrations.telegram}</div>
            <div className="mt-1 text-[12px] text-slate/60">Bot: @{data.brand.bot_username}. Mini App buttons need an https public URL (PUBLIC_BASE_URL).</div>
          </Card>
          <Card title="Data hosting"><div>{data.integrations.data_region}</div><div className="mt-1 text-[12px] text-slate/60">Singapore or in-country, per lender.</div></Card>
        </div>
      )}
      {tab === "Users" && (
        <Card pad={false} title="Users and roles">
          <table className="data"><thead><tr><th>Name</th><th>Role</th><th>Email</th></tr></thead>
            <tbody>{data.users.map((u: any) => <tr key={u.id}><td>{u.name}</td><td>{ROLE_LABEL[u.role]}</td><td>{u.email}</td></tr>)}</tbody></table>
        </Card>
      )}
    </div>
  );
}

function Num({ label, v, on, step = 1 }: { label: string; v: number; on: (v: number) => void; step?: number }) {
  return (
    <label className="flex items-center justify-between gap-2 py-1 text-[13px]">
      <span>{label}</span>
      <input type="number" step={step} className="input w-32 text-right" value={v} onChange={(e) => on(Number(e.target.value))} />
    </label>
  );
}
function Txt({ label, v, on }: { label: string; v: string; on: (v: string) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 py-1 text-[13px]">
      <span>{label}</span><input className="input w-32 text-right" value={v} onChange={(e) => on(e.target.value)} />
    </label>
  );
}
function Chk({ label, v, on }: { label: string; v: boolean; on: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 py-1 text-[13px]"><input type="checkbox" checked={v} onChange={(e) => on(e.target.checked)} />{label}</label>
  );
}

function Versions({ versions }: { versions: any[] }) {
  return (
    <Card title="Policy versions">
      <table className="data"><tbody>{versions.map((v) => (
        <tr key={v.version}><td>v{v.version}</td><td>{dateTime(v.at)}</td><td>{v.by}</td><td className="text-[12px]">{v.note}</td></tr>
      ))}</tbody></table>
    </Card>
  );
}

function Ranking({ draft, set }: { draft: any; set: (p: string[], v: any) => void }) {
  const [preview, setPreview] = useState<any>();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setPreview(await api.post("/settings/ranking-preview", { ranking: draft.ranking, segments: draft.segments }));
    } finally {
      setBusy(false);
    }
  };
  const w = draft.ranking;
  return (
    <div className="grid gap-3 lg:grid-cols-[380px_1fr]">
      <div className="space-y-3">
        <Card title="Priority blend">
          <Num label="Weight: money at stake" v={w.stake} step={0.05} on={(v) => set(["ranking", "stake"], v)} />
          <Num label="Weight: unlikely to self-cure" v={w.pay_likelihood} step={0.05} on={(v) => set(["ranking", "pay_likelihood"], v)} />
        </Card>
        <Card title="Pay likelihood adjustments (points)">
          {[["on_time_ratio", "On-time ratio (full swing)"], ["promises_kept", "Promises kept (full swing)"], ["savings_stopped", "Savings deposits stopped"],
            ["savings_stopped_weeks", "...after N weeks without a deposit"], ["telegram_responsive", "On Telegram and responsive"],
            ["telegram_unlinked", "Not on Telegram"], ["prior_restructure", "Restructured before"], ["repeat_borrower", "Repeat borrower"]].map(([k, l]) => (
            <Num key={k} label={l} v={w[k]} on={(v) => set(["ranking", k], v)} />
          ))}
        </Card>
        <Card title="Segment rules">
          <Num label="Nudge if pay likelihood at least" v={draft.segments.nudge_min_pay_likelihood} on={(v) => set(["segments", "nudge_min_pay_likelihood"], v)} />
          <Num label="Visit if stake at least (and unlikely to pay)" v={draft.segments.visit_min_stake} on={(v) => set(["segments", "visit_min_stake"], v)} />
          <Num label="Visit after N unanswered messages" v={draft.segments.visit_after_unanswered_attempts} on={(v) => set(["segments", "visit_after_unanswered_attempts"], v)} />
          <Num label="Visit after N broken promises" v={draft.segments.visit_on_broken_promises} on={(v) => set(["segments", "visit_on_broken_promises"], v)} />
        </Card>
        <button className="btn btn-primary w-full justify-center" disabled={busy} onClick={run}>{busy ? "Scoring…" : "Preview top 20 with these weights"}</button>
      </div>
      <Card title={preview ? `Top 20 under proposed weights · ${preview.segment_changes} cases would change segment` : "Preview"} pad={false}>
        {!preview ? <div className="p-3 text-slate/60">Change weights, then preview. Nothing is saved until you save a new policy version.</div> : (
          <table className="data">
            <thead><tr><th className="num">Rank</th><th className="num">Was</th><th>Borrower</th><th className="num">Priority</th><th>Segment</th></tr></thead>
            <tbody>{preview.top20.map((x: any) => (
              <tr key={x.case_id}>
                <td className="num">{x.rank}</td>
                <td className={`num ${x.was > x.rank ? "text-green-slate" : x.was < x.rank ? "text-danger" : "text-slate/50"}`}>{x.was}{x.was !== x.rank ? (x.was > x.rank ? " ↑" : " ↓") : ""}</td>
                <td>{x.borrower}</td><td className="num">{x.priority.toFixed(1)}</td>
                <td><Segment value={x.segment} />{x.segment !== x.segment_was && <span className="ml-1 text-[11px] text-slate/60">was {x.segment_was}</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function Scripts({ templates, onChange }: { templates: any[]; onChange: () => void }) {
  const [lang, setLang] = useState("all");
  const [edit, setEdit] = useState<{ id: number; body: string }>();
  const [msg, setMsg] = useState<string>();
  const langs = [...new Set(templates.map((t) => t.language))];
  const act = async (fn: () => Promise<any>, ok: string) => {
    try {
      await fn();
      setMsg(ok);
      setEdit(undefined);
      onChange();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  return (
    <Card pad={false} title="Template library" right={
      <select className="input" value={lang} onChange={(e) => setLang(e.target.value)}><option value="all">All languages</option>{langs.map((l) => <option key={l}>{l}</option>)}</select>}>
      {msg && <div className="border-b border-sage-pale bg-bg px-3 py-1.5 text-[12px]">{msg}</div>}
      <div className="max-h-[640px] overflow-auto">
        <table className="data">
          <thead><tr><th>Template</th><th>Lang</th><th>v</th><th>Text</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {templates.filter((t) => lang === "all" || t.language === lang).map((t) => (
              <tr key={t.id} className={t.status === "retired" ? "opacity-50" : ""}>
                <td className="whitespace-nowrap">{t.key}<div className="text-[11px] text-slate/60">{t.category} · {t.channel}</div></td>
                <td>{t.language}</td><td>{t.version}</td>
                <td className="max-w-[520px]">
                  {edit && edit.id === t.id ? (
                    <div><textarea className="input local w-full" rows={4} value={edit.body} onChange={(e) => setEdit({ id: t.id, body: e.target.value })} />
                      <div className="mt-1 flex gap-1"><button className="btn btn-primary" onClick={() => act(() => api.post(`/settings/templates/${t.id}/edit`, { body: edit.body }), "Saved as a new draft version")}>Save draft</button>
                        <button className="btn" onClick={() => setEdit(undefined)}>Cancel</button></div></div>
                  ) : (
                    <>
                      <div className="local text-[13px]">{t.body}</div>
                      {t.language !== "en" && <div className="text-[11px] text-slate/60">{t.english}</div>}
                      <div className="mt-0.5 text-[11px] text-slate/50">Variables: {t.variables.join(", ")}</div>
                    </>
                  )}
                </td>
                <td className="whitespace-nowrap">
                  <Badge tone={t.status === "approved" ? "good" : t.status === "draft" ? "warn" : "neutral"}>{t.status}</Badge>
                  {t.needs_native_review && <div className="mt-1"><DraftTag /></div>}
                  {t.approved_by && <div className="text-[11px] text-slate/60">{t.approved_by}</div>}
                </td>
                <td className="whitespace-nowrap">
                  {t.status !== "retired" && <button className="btn" onClick={() => setEdit({ id: t.id, body: t.body })}>Edit</button>}
                  {t.status === "draft" && <button className="btn btn-primary ml-1" onClick={() => act(() => api.post(`/settings/templates/${t.id}/approve`), "Approved; previous version retired")}>Approve</button>}
                  {t.needs_native_review && t.status !== "retired" && <button className="btn ml-1" onClick={() => act(() => api.post(`/settings/templates/${t.id}/native-review`), "Native review recorded")}>Mark reviewed</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Brand({ brand, onSaved }: { brand: any; onSaved: () => void }) {
  const [b, setB] = useState(brand);
  const [saved, setSaved] = useState(false);
  const f = (k: string, label: string) => (
    <label className="block py-1 text-[13px]">{label}<input className="input local mt-0.5 w-full" value={b[k] ?? ""} onChange={(e) => { setB({ ...b, [k]: e.target.value }); setSaved(false); }} /></label>
  );
  const c = (k: string, label: string) => (
    <label className="flex items-center justify-between py-1 text-[13px]">{label}
      <input type="color" value={b.colors?.[k] ?? "#000000"} onChange={(e) => { setB({ ...b, colors: { ...b.colors, [k]: e.target.value } }); setSaved(false); }} /></label>
  );
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card title="What borrowers see">
        {f("lender_name", "Lender name")}{f("lender_name_local", "Lender name (local script)")}{f("bot_display_name", "Telegram bot display name")}
        {f("bot_username", "Telegram bot username")}{f("logo_text", "Logo letter (until a logo is uploaded)")}{f("lender_phone", "Lender phone for borrowers")}
        {c("primary", "Mini App primary colour")}{c("accent", "Accent colour")}{c("background", "Background colour")}
        <button className="btn btn-primary mt-2" onClick={async () => { await api.put("/settings/brand", b); setSaved(true); onSaved(); }}>{saved ? "Saved" : "Save brand"}</button>
        <div className="mt-1 text-[11px] text-slate/60">Put a prospect's own name and colours here before a demo. "Tenpai" never appears to borrowers.</div>
      </Card>
      <Card title="Preview">
        <div className="mx-auto w-64 overflow-hidden rounded-xl border" style={{ background: b.colors?.background }}>
          <div className="flex items-center gap-2 px-3 py-2 text-white" style={{ background: b.colors?.primary }}>
            <span className="flex h-7 w-7 items-center justify-center rounded bg-white/20 font-bold">{b.logo_text}</span>
            <span className="local font-semibold">{b.lender_name_local || b.lender_name}</span>
          </div>
          <div className="p-3"><div className="rounded-lg py-2 text-center font-semibold text-white" style={{ background: b.colors?.primary }}>Pay now</div></div>
        </div>
      </Card>
    </div>
  );
}
