import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, PageHeader, SampleTag, Segment } from "../components/ui";
import { money, pct, toMinor } from "../format";
import { useApp, useFetch } from "../state";

export function FieldManager() {
  const { data, error } = useFetch<any>("/field/manager");
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const max = Math.max(1, ...data.officers.map((o: any) => o.today_assigned + o.carried_over));
  return (
    <div className="space-y-3">
      <PageHeader question="Where should my officers go?">{data.sample && <SampleTag />}</PageHeader>
      <div className="flex flex-wrap gap-2">
        {Object.entries(data.outcomes_today).map(([k, v]) => <Badge key={k}>{k.replace("_", " ")}: {v as number}</Badge>)}
        {!Object.keys(data.outcomes_today).length && <span className="text-[12px] text-slate/60">No outcomes logged yet today.</span>}
      </div>
      <Card pad={false} title={`Visits for ${data.day}`}>
        <table className="data">
          <thead><tr><th>Officer</th><th>Branch</th><th>Workload today</th><th className="num">Done</th><th className="num">Carried over</th><th className="num">Open cases</th><th className="num">Completion (30d)</th><th className="num">Visits (30d)</th></tr></thead>
          <tbody>
            {data.officers.map((o: any) => (
              <tr key={o.officer_id}>
                <td className="font-medium">{o.officer}</td>
                <td>{o.branch}</td>
                <td className="w-56">
                  <div className="flex h-3 overflow-hidden rounded bg-bg">
                    <div className="bg-green-slate" style={{ width: `${(o.today_done / max) * 100}%` }} />
                    <div className="bg-sage" style={{ width: `${((o.today_assigned - o.today_done) / max) * 100}%` }} />
                    <div className="bg-warn" style={{ width: `${(o.carried_over / max) * 100}%` }} />
                  </div>
                  <div className="text-[11px] text-slate/60">{o.today_assigned} today{o.carried_over ? `, ${o.carried_over} carried over` : ""}</div>
                </td>
                <td className="num">{o.today_done}</td>
                <td className="num">{o.carried_over}</td>
                <td className="num">{o.open_cases}</td>
                <td className="num">{pct(o.completion_30d, 0)}</td>
                <td className="num">{o.visits_30d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <p className="text-[12px] text-slate/60">Officers open their list at <Link className="underline" to="/field">/field</Link> on their phone (installable).</p>
    </div>
  );
}

const OUT: Record<string, { en: string; my: string; km: string }> = {
  paid: { en: "Paid", my: "ပေးပြီး", km: "បានបង់" },
  promised: { en: "Promised", my: "ကတိပြု", km: "សន្យា" },
  not_home: { en: "Not home", my: "အိမ်မှာမရှိ", km: "មិននៅផ្ទះ" },
  refused: { en: "Refused", my: "ငြင်းဆို", km: "បដិសេធ" },
  hardship: { en: "Hardship", my: "အခက်အခဲ", km: "លំបាក" },
  dispute: { en: "Dispute", my: "အငြင်းပွား", km: "វិវាទ" },
  moved_away: { en: "Moved away", my: "ပြောင်းသွား", km: "ផ្លាស់ទៅ" },
  deceased: { en: "Deceased", my: "ကွယ်လွန်", km: "ស្លាប់" },
};

export function OfficerView() {
  const { meta, role, setRole } = useApp();
  useEffect(() => {
    navigator.serviceWorker?.register("/sw.js").catch(() => undefined);
  }, []);
  const [lang, setLang] = useState<"en" | "local">("en");
  const officerUser = meta?.user?.role === "credit_officer" ? meta.user : undefined;
  const { data, error, reload } = useFetch<any>(officerUser ? "/field/my" : null, [officerUser?.id]);
  const [open, setOpen] = useState<number>();
  const local = meta?.tenant.market === "MM" ? "my" : "km";
  const L = (k: string) => (lang === "en" ? OUT[k].en : OUT[k][local as "my" | "km"]);

  if (role !== "credit_officer") {
    const officers = meta?.users.filter((u) => u.role === "credit_officer") ?? [];
    return (
      <div className="mx-auto max-w-sm space-y-3 p-4">
        <h1 className="text-[17px] font-semibold">Field visits</h1>
        <p>Choose an officer to open their phone view:</p>
        {officers.map((u) => <button key={u.id} className="btn w-full justify-center" onClick={() => setRole("credit_officer", u.id)}>{u.name}</button>)}
      </div>
    );
  }
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  return (
    <div className="mx-auto max-w-md pb-10">
      <div className="sticky top-0 z-10 flex items-center justify-between bg-slate px-4 py-3 text-white">
        <div>
          <div className="text-[15px] font-semibold">{lang === "en" ? data.officer.name : data.officer.name_local ?? data.officer.name}</div>
          <div className="text-[12px] text-white/70">{data.day} · {data.done}/{data.total} done{data.sample ? " · SAMPLE" : ""}</div>
        </div>
        <button className="rounded border border-white/30 px-2 py-1 text-[12px]" onClick={() => setLang(lang === "en" ? "local" : "en")}>
          {lang === "en" ? (local === "my" ? "မြန်မာ" : "ខ្មែរ") : "English"}
        </button>
      </div>
      <div className="space-y-4 p-3">
        {!data.villages.length && <div className="p-4 text-center text-slate/60">No visits today.</div>}
        {data.villages.map((g: any) => (
          <div key={g.village}>
            <div className="mb-1 px-1 text-[12px] font-semibold uppercase text-green-slate">{g.village} · {g.visits.length}</div>
            <div className="space-y-2">
              {g.visits.map((v: any) => (
                <div key={v.visit_id} className={`rounded-lg border bg-white p-3 ${v.status === "completed" ? "opacity-60" : ""}`}>
                  <div className="flex items-start justify-between gap-2" onClick={() => setOpen(open === v.visit_id ? undefined : v.visit_id)}>
                    <div>
                      <div className="text-[15px] font-semibold">{lang === "en" ? v.borrower : v.borrower_local ?? v.borrower}</div>
                      <div className="text-[13px]">{money(v.amount_overdue, v.currency)} · {v.days_overdue}d{v.loan_type === "group" ? " · group" : ""}</div>
                      <div className="mt-1 text-[12px] text-slate/70">{v.reasons.join(" · ")}</div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      {v.status === "completed" ? <Badge tone="good">{L(v.outcome)}</Badge> : <Segment value={v.segment} />}
                      {v.carried_over && v.status !== "completed" && <Badge tone="warn">carried over</Badge>}
                    </div>
                  </div>
                  {v.phone && v.status !== "completed" && (
                    <a href={`tel:${v.phone}`} className="mt-2 block rounded-lg border border-green-slate py-3 text-center text-[15px] font-semibold text-green-slate">Call {v.phone}</a>
                  )}
                  {open === v.visit_id && v.status !== "completed" && <OutcomeForm v={v} L={L} onDone={() => { setOpen(undefined); reload(); }} />}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OutcomeForm({ v, L, onDone }: { v: any; L: (k: string) => string; onDone: () => void }) {
  const [outcome, setOutcome] = useState<string>();
  const [notes, setNotes] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [photo, setPhoto] = useState<string>();
  const [gps, setGps] = useState<{ lat: number; lng: number }>();
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState(false);
  const takenAt = useRef<string | undefined>(undefined);
  const onPhoto = (f?: File) => {
    if (!f) return;
    takenAt.current = new Date().toISOString();
    const img = new Image();
    const reader = new FileReader();
    reader.onload = () => {
      img.onload = () => {
        // Downscale on the phone: cheap Androids, slow networks.
        const scale = Math.min(1, 1024 / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = img.width * scale;
        c.height = img.height * scale;
        c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
        setPhoto(c.toDataURL("image/jpeg", 0.7));
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(f);
    navigator.geolocation?.getCurrentPosition((p) => setGps({ lat: p.coords.latitude, lng: p.coords.longitude }), () => undefined,
      { timeout: 5000 });
  };
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/field/visits/${v.visit_id}/outcome`, {
        outcome, notes: notes || null, photo, photo_taken_at: takenAt.current, lat: gps?.lat, lng: gps?.lng,
        promise_amount: outcome === "promised" && amount ? toMinor(Number(amount), v.currency) : null,
        promise_date: outcome === "promised" ? date || null : null,
      });
      onDone();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <div className="grid grid-cols-2 gap-2">
        {Object.keys(OUT).map((k) => (
          <button key={k} className={`rounded-lg border py-3 text-[14px] font-medium ${outcome === k ? "border-slate bg-slate text-white" : "bg-white"}`} onClick={() => setOutcome(k)}>{L(k)}</button>
        ))}
      </div>
      {outcome === "promised" && (
        <div className="grid grid-cols-2 gap-2">
          <input inputMode="decimal" className="rounded-lg border px-3 py-3 text-[15px]" placeholder={`Amount ${v.currency}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
          <input type="date" className="rounded-lg border px-3 py-3 text-[15px]" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      )}
      <textarea className="w-full rounded-lg border p-2 text-[14px]" rows={2} placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <label className="block rounded-lg border border-dashed py-3 text-center text-[14px]">
        {photo ? "Photo added ✓" : "Take photo"}
        <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => onPhoto(e.target.files?.[0])} />
      </label>
      {photo && <img src={photo} alt="" className="h-24 rounded object-cover" />}
      {gps && <div className="text-[11px] text-slate/60">GPS {gps.lat.toFixed(5)}, {gps.lng.toFixed(5)}</div>}
      {err && <div className="text-[12px] text-danger">{err}</div>}
      <button className="w-full rounded-lg bg-green-slate py-3 text-[15px] font-semibold text-white disabled:opacity-50"
        disabled={!outcome || busy || (outcome === "promised" && (!amount || !date))} onClick={submit}>
        {busy ? "Saving…" : "Save outcome"}
      </button>
      <div className="text-[11px] text-slate/50">Offline queue: designed for, not built in the demo.</div>
    </div>
  );
}
