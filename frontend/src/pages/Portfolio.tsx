import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, PageHeader, SampleTag, Segment, Stat, Tip } from "../components/ui";
import { money, pct } from "../format";
import { useApp, useFetch } from "../state";

const PAR_TIP = "PARn = outstanding principal of loans more than n days overdue / total outstanding principal";

export default function Portfolio() {
  const { meta, role } = useApp();
  const { data: hc, error, reload } = useFetch<any>("/health");
  const [showImport, setShowImport] = useState(false);
  const rep = hc?.reporting_currency ?? "MMK";
  return (
    <div className="space-y-3">
      <PageHeader question="How bad is my book today?">
        {meta?.tenant.is_demo && <SampleTag />}
        {role === "head_of_collections" && (
          <button className="btn btn-primary" onClick={() => setShowImport(!showImport)}>
            {showImport ? "Close import" : "Import core banking export"}
          </button>
        )}
        <a className="btn" href={api.url("/health.pdf")} target="_blank" rel="noreferrer">
          One-page PDF
        </a>
      </PageHeader>
      {showImport && <ImportFlow onDone={reload} />}
      <ErrorBox error={error} />
      {!hc ? (
        <Loading />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="PAR30" value={pct(hc.summary.par30)} tone="danger" tip={PAR_TIP} sub="funders watch this" />
            <Stat label="PAR1" value={pct(hc.summary.par1)} tip={PAR_TIP} />
            <Stat label="PAR90" value={pct(hc.summary.par90)} tip={PAR_TIP} />
            <Stat label="Overdue loans" value={hc.summary.overdue_loans.toLocaleString()}
                  sub={`of ${hc.summary.active_loans.toLocaleString()} active`} />
            <Stat label="Amount overdue" value={money(hc.summary.amount_overdue, rep, true)}
                  sub={`outstanding ${money(hc.summary.outstanding, rep, true)}`} />
            <Stat label="Overdue on Telegram" value={pct(hc.summary.telegram_link_rate_overdue, 0)}
                  tone="warn" tip="Caps everything digital: unlinked borrowers can only be invited by SMS or visited"
                  sub={`${hc.summary.missing_phone} with no phone`} />
          </div>
          {Object.keys(hc.fx).length > 0 && (
            <div className="text-[12px] text-slate/60">
              Amounts in {rep}; {Object.entries(hc.fx).map(([k, v]) => `${(v as number).toLocaleString()} ${k}/${rep}`).join(", ")}.
              Loans by currency: {Object.entries(hc.currencies).map(([k, v]) => `${k} ${v}`).join(", ")}.
            </div>
          )}
          <div className="grid gap-3 lg:grid-cols-5">
            <Card title="Overdue book by bucket" className="lg:col-span-2">
              <div className="h-40">
                <ResponsiveContainer>
                  <BarChart data={hc.buckets.filter((b: any) => b.key !== "pre_due")} margin={{ left: 0, right: 8 }}>
                    <XAxis dataKey="label" fontSize={11} />
                    <YAxis fontSize={11} tickFormatter={(v) => money(v, rep, true).replace(`${rep} `, "")} width={48} />
                    <Tooltip formatter={(v: number) => money(v, rep)} />
                    <Bar dataKey="amount_overdue" fill="#52796F" name="Amount overdue" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <table className="data mt-2">
                <thead>
                  <tr><th>Bucket</th><th className="num">Loans</th><th className="num">Amount overdue</th></tr>
                </thead>
                <tbody>
                  {hc.buckets.map((b: any) => (
                    <tr key={b.key}>
                      <td>{b.label}</td>
                      <td className="num">{b.loans.toLocaleString()}</td>
                      <td className="num">{b.key === "pre_due" ? <span className="text-slate/50">due soon</span> : money(b.amount_overdue, rep)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title={<Tip text={PAR_TIP}>PAR by branch</Tip>} className="lg:col-span-3" pad={false}>
              <ParTable rows={hc.par.by_branch} rep={rep} />
              <details className="border-t border-sage-pale">
                <summary className="cursor-pointer px-3 py-2 text-[12px] font-medium text-green-slate">By officer ({hc.par.by_officer.length})</summary>
                <ParTable rows={hc.par.by_officer} rep={rep} officer />
              </details>
            </Card>
          </div>
          <Card
            title={`Payments that appear unposted (${hc.unposted.length})`}
            right={<span className="text-[12px] text-slate/60">Check these before anyone chases</span>}
            pad={false}
          >
            <div className="max-h-64 overflow-auto">
              <table className="data">
                <thead>
                  <tr><th>Loan</th><th>Borrower</th><th>Branch</th><th>Signal</th><th className="num">Days</th><th className="num">Arrears</th></tr>
                </thead>
                <tbody>
                  {hc.unposted.map((u: any) => (
                    <tr key={u.loan + u.kind}>
                      <td>{u.loan}</td>
                      <td>{u.borrower}</td>
                      <td>{u.branch}</td>
                      <td>
                        <Badge tone={u.kind === "repayment_after_arrears_run" ? "danger" : "warn"}>
                          {u.kind === "repayment_after_arrears_run" ? "Repayment after arrears run" : "Savings cover arrears"}
                        </Badge>{" "}
                        <span className="text-[12px] text-slate/70">
                          {u.kind === "repayment_after_arrears_run"
                            ? `paid ${money(u.last_repayment_amount, u.currency)} on ${u.last_repayment_date}; arrears as of ${u.arrears_as_of}`
                            : `savings ${money(u.savings_balance, u.currency)}`}
                        </span>
                      </td>
                      <td className="num">{u.days_overdue}</td>
                      <td className="num">{money(u.amount_overdue, u.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card
            title="Top 50 ranked visit list"
            right={<a className="btn" href={api.url("/health/visit-list.csv")}>Download CSV</a>}
            pad={false}
          >
            <div className="max-h-[480px] overflow-auto">
              <table className="data">
                <thead>
                  <tr><th className="num">#</th><th>Borrower</th><th>Village / ward</th><th>Officer</th><th>Segment</th>
                    <th className="num">Days</th><th className="num">Overdue</th><th>Why</th></tr>
                </thead>
                <tbody>
                  {hc.visit_list.map((v: any) => (
                    <tr key={v.case_id}>
                      <td className="num">{v.rank}</td>
                      <td>
                        <Link className="font-medium text-green-slate hover:underline" to={`/cases/${v.case_id}`}>{v.borrower}</Link>
                        <div className="local text-[11px] text-slate/60">{v.borrower_local}</div>
                      </td>
                      <td>{v.village}<div className="text-[11px] text-slate/60">{v.branch}</div></td>
                      <td>{v.officer}</td>
                      <td><Segment value={v.segment} /></td>
                      <td className="num">{v.days_overdue}</td>
                      <td className="num">{money(v.amount_overdue, v.currency)}</td>
                      <td className="text-[12px] text-slate/80">{v.reasons.join(" · ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <ImportHistory />
        </>
      )}
    </div>
  );
}

function ParTable({ rows, rep, officer }: { rows: any[]; rep: string; officer?: boolean }) {
  return (
    <table className="data">
      <thead>
        <tr><th>{officer ? "Officer" : "Branch"}</th><th className="num">Loans</th><th className="num">Outstanding</th>
          <th className="num">PAR1</th><th className="num">PAR30</th><th className="num">PAR90</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td>{r.name}{officer && <div className="text-[11px] text-slate/60">{r.branch}</div>}</td>
            <td className="num">{r.loans}</td>
            <td className="num">{money(r.outstanding, rep, true)}</td>
            <td className="num">{pct(r.par1)}</td>
            <td className={`num font-semibold ${r.par30 > 0.1 ? "text-danger" : ""}`}>{pct(r.par30)}</td>
            <td className="num">{pct(r.par90)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const KIND_LABEL: Record<string, string> = {
  loans: "Loans (required)",
  schedule: "Repayment schedule (optional)",
  savings: "Savings transactions (optional)",
};

function ImportFlow({ onDone }: { onDone: () => void }) {
  const { refresh, tenant } = useApp();
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [anonymise, setAnonymise] = useState(false);
  const [preview, setPreview] = useState<any>();
  const [mappings, setMappings] = useState<Record<string, Record<string, string | null>>>({});
  const [saveAs, setSaveAs] = useState("Mifos X export");
  const [result, setResult] = useState<any>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const doPreview = async () => {
    if (!files.loans) return;
    setBusy(true);
    setError(undefined);
    try {
      const fd = new FormData();
      Object.entries(files).forEach(([k, f]) => f && fd.append(k, f));
      const p = await api.upload<any>("/imports/preview", fd);
      setPreview(p);
      setMappings(Object.fromEntries(Object.entries(p.files).map(([k, f]: any) => [k, f.mapping])));
      setResult(undefined);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const r = await api.post<any>("/imports/commit", {
        upload_id: preview.upload_id, mappings, anonymise, save_mapping_as: saveAs || null,
      });
      setResult(r);
      setPreview(undefined);
      onDone();
      refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Import core banking export" right={<span className="text-[12px] text-slate/60">Mifos X or any CSV/XLSX via column mapping</span>}>
      <div className="grid gap-3 md:grid-cols-3">
        {(["loans", "schedule", "savings"] as const).map((k) => (
          <label key={k} className="block rounded border border-dashed border-sage-pale p-2">
            <div className="mb-1 text-[12px] font-medium">{KIND_LABEL[k]}</div>
            <input type="file" accept=".csv,.xlsx" onChange={(e) => setFiles({ ...files, [k]: e.target.files?.[0] })} />
          </label>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={anonymise} onChange={(e) => setAnonymise(e.target.checked)} />
          Anonymise on import <span className="text-[12px] text-slate/60">(hashes names, phones and ID numbers; keeps everything else)</span>
        </label>
        <button className="btn btn-primary" disabled={!files.loans || busy} onClick={doPreview}>
          {busy && !preview ? "Reading…" : "Next: map columns"}
        </button>
        <span className="text-[12px] text-slate/60">
          Sample files:{" "}
          {["mifos_loans_active", "mifos_repayment_schedule", "mifos_savings_transactions"].map((n) => (
            <a key={n} className="mr-2 text-green-slate underline" href={`/api/sample-files/${n}_${tenant.slice(0, 2)}.csv`}>{n.replace("mifos_", "")}</a>
          ))}
        </span>
      </div>
      <ErrorBox error={error} />
      {preview && (
        <div className="mt-3 space-y-3">
          {Object.entries(preview.files).map(([kind, f]: any) => (
            <div key={kind} className="rounded border border-sage-pale">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sage-pale bg-[#F7F8F5] px-3 py-2">
                <div className="font-medium">{KIND_LABEL[kind]}: {f.filename} · {f.rows.toLocaleString()} rows</div>
                {f.matched_saved ? <Badge tone="good">Matched saved mapping "{f.matched_saved}"</Badge> : <Badge>New mapping</Badge>}
              </div>
              <div className="max-h-72 overflow-auto">
                <table className="data">
                  <thead><tr><th>Tenpai field</th><th>Column in your file</th><th>First row</th></tr></thead>
                  <tbody>
                    {f.fields.map((fld: any) => {
                      const col = mappings[kind]?.[fld.key] ?? "";
                      const missing = fld.required && !col;
                      return (
                        <tr key={fld.key}>
                          <td>
                            {fld.label} {fld.required && <span className="text-danger">*</span>}
                            {fld.help && <div className="text-[11px] text-slate/60">{fld.help}</div>}
                          </td>
                          <td>
                            <select
                              className={`input w-full ${missing ? "border-danger" : ""}`}
                              value={col}
                              onChange={(e) => setMappings({ ...mappings, [kind]: { ...mappings[kind], [fld.key]: e.target.value || null } })}
                            >
                              <option value="">(not in file)</option>
                              {f.headers.map((h: string) => <option key={h} value={h}>{h}</option>)}
                            </select>
                          </td>
                          <td className="local max-w-[220px] truncate text-[12px] text-slate/70">{col ? f.sample[0]?.[col] : ""}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-[12px]">Save mapping as <input className="input ml-1" value={saveAs} onChange={(e) => setSaveAs(e.target.value)} /></label>
            <button className="btn btn-primary" disabled={busy} onClick={commit}>{busy ? "Importing…" : "Validate and import"}</button>
          </div>
        </div>
      )}
      {result && <ImportResult result={result} />}
    </Card>
  );
}

const ISSUE_LABEL: Record<string, string> = {
  missing_required: "Missing required value",
  parse_error: "Value could not be read",
  duplicate_loan_id: "Duplicate loan ID (first row kept)",
  negative_balance: "Negative balance",
  future_date: "Date after the export date",
  missing_phone: "No mobile number (falls to Visit)",
  unknown_currency: "Unknown currency",
  unknown_loan: "Loan not in loans file",
};

function ImportResult({ result }: { result: any }) {
  const loans = result.batches.loans;
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="Rows read" value={loans.rows.toLocaleString()} />
        <Stat label="Accepted" value={loans.accepted.toLocaleString()} tone="good" />
        <Stat label="Rejected" value={loans.rejected} tone={loans.rejected ? "danger" : undefined} />
        <Stat label="Cases opened" value={result.cases.opened} sub={`${result.cases.control} control · ${result.cases.treatment} treatment`} />
        <Stat label="Cured since last" value={result.cases.closed_cured} sub={`${loans.changes.new} new, ${loans.changes.updated} changed loans`} />
      </div>
      <div className="rounded border border-sage-pale">
        <div className="border-b border-sage-pale bg-[#F7F8F5] px-3 py-2 font-medium">Validation report</div>
        <div className="flex flex-wrap gap-2 p-2">
          {Object.entries(loans.counts).map(([k, v]) => (
            <Badge key={k} tone={["missing_phone", "unknown_loan"].includes(k) ? "warn" : "danger"}>{ISSUE_LABEL[k] ?? k}: {v as number}</Badge>
          ))}
          {!Object.keys(loans.counts).length && <Badge tone="good">No issues</Badge>}
        </div>
        <table className="data">
          <thead><tr><th className="num">Row</th><th>Loan</th><th>Issue</th><th>Detail</th></tr></thead>
          <tbody>
            {loans.issues.slice(0, 50).map((i: any, n: number) => (
              <tr key={n}>
                <td className="num">{i.row}</td><td>{i.key}</td>
                <td><Badge tone={i.severity === "error" ? "danger" : "warn"}>{ISSUE_LABEL[i.code] ?? i.code}</Badge></td>
                <td className="text-[12px]">{i.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ImportHistory() {
  const { data } = useFetch<any[]>("/imports");
  if (!data?.length) return null;
  return (
    <Card title="Import history" pad={false}>
      <table className="data">
        <thead><tr><th>When</th><th>File</th><th>Kind</th><th className="num">Rows</th><th className="num">Accepted</th><th>Anonymised</th><th>By</th></tr></thead>
        <tbody>
          {data.slice(0, 10).map((b) => (
            <tr key={b.id}>
              <td>{new Date(b.created_at).toLocaleString("en-GB")}</td><td>{b.filename}</td><td>{b.kind}</td>
              <td className="num">{b.rows.toLocaleString()}</td><td className="num">{b.accepted.toLocaleString()}</td>
              <td>{b.anonymised ? "yes" : "no"}</td><td>{b.created_by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
