// Phone-frame preview of what the borrower saw: the lender's Telegram chat and
// the Mini App, local script with an English shadow for lender staff.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { MiniApp } from "./MiniApp";

import { dateTime } from "../format";

const tz = (iso: string) => dateTime(iso);

export default function Phone({ account, onChange }: { account: any; onChange: () => void }) {
  const [tab, setTab] = useState<"chat" | "app">("chat");
  const [shadow, setShadow] = useState(true);
  const [replies, setReplies] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string>();
  const brand = account.brand;
  const color = brand?.colors?.primary ?? "#333";
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api.get<any[]>("/demo/replies").then(setReplies).catch(() => setReplies([]));
  }, []);
  useEffect(() => {
    // scrollIntoView returns a Promise in newer Chromium; never return it from an effect.
    void end.current?.scrollIntoView({ block: "end" });
  }, [account.messages.length, tab]);
  const msgs = account.messages.filter((m: any) => m.channel !== "sms");
  const sms = account.messages.filter((m: any) => m.channel === "sms");

  const send = async (text: string) => {
    setBusy(true);
    try {
      const r = await api.post<any>("/demo/reply", { case_id: account.case.id, text });
      setNote(`Classified: ${r.classification}${r.detail?.subtype ? ` (${r.detail.subtype})` : ""}`);
      onChange();
    } finally {
      setBusy(false);
    }
  };
  const pay = async () => {
    setBusy(true);
    try {
      const r = await api.post<any>("/demo/pay", { case_id: account.case.id });
      setNote(`Payment ${r.reference}: ${r.match_status} (${r.kind})`);
      onChange();
    } catch (e: any) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <div className="flex rounded border border-sage-pale bg-white p-0.5">
          {(["chat", "app"] as const).map((t) => (
            <button key={t} className={`rounded px-3 py-1 text-[12px] ${tab === t ? "bg-slate text-white" : ""}`} onClick={() => setTab(t)}>
              {t === "chat" ? "Telegram chat" : "Mini App"}
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-1 text-[12px]">
          <input type="checkbox" checked={shadow} onChange={(e) => setShadow(e.target.checked)} /> English shadow
        </label>
      </div>
      <div className="mx-auto w-[300px] rounded-[36px] border-[10px] border-slate bg-slate shadow-lg">
        <div className="h-[560px] overflow-hidden rounded-[26px] bg-[#DCE6EE]">
          {tab === "chat" ? (
            <div className="flex h-full flex-col">
              <div className="flex items-center gap-2 bg-white px-3 py-2 shadow-sm">
                <span className="flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-bold text-white" style={{ background: color }}>{brand.logo_text}</span>
                <div className="leading-tight">
                  <div className="text-[13px] font-semibold">{brand.bot_display_name}</div>
                  <div className="text-[10px] text-slate/60">bot</div>
                </div>
              </div>
              <div className="local flex-1 space-y-2 overflow-y-auto p-2">
                {!msgs.length && <div className="mt-10 text-center text-[11px] text-slate/60">No messages yet</div>}
                {msgs.map((m: any) => {
                  const out = m.direction === "out";
                  const notSent = m.status === "blocked" || m.status === "planned";
                  return (
                    <div key={m.id} className={`flex ${out ? "justify-start" : "justify-end"}`}>
                      <div className={`max-w-[85%] rounded-xl px-2.5 py-1.5 text-[12.5px] leading-snug shadow-sm ${
                        notSent ? "border border-dashed border-slate/40 bg-white/50 text-slate/60" : out ? "bg-white" : "bg-[#E2F7CB]"}`}>
                        {notSent && (
                          <div className="mb-0.5 text-[10px] font-semibold text-danger">
                            {m.status === "blocked" ? `Not sent: ${m.rule}` : `Scheduled ${tz(m.planned_at)}`} (staff view)
                          </div>
                        )}
                        <div className="whitespace-pre-wrap break-words">{m.body}</div>
                        {shadow && out && m.shadow && m.language !== "en" && (
                          <div className="mt-1 border-t border-slate/10 pt-1 font-sans text-[10px] text-slate/60">{m.shadow}</div>
                        )}
                        {!out && m.classification && (
                          <div className="mt-0.5 font-sans text-[10px] text-slate/60">→ {m.classification}{m.classification_detail?.subtype ? ` (${m.classification_detail.subtype})` : ""}</div>
                        )}
                        <div className="mt-0.5 text-right font-sans text-[9px] text-slate/50">
                          {tz(m.sent_at ?? m.planned_at)}{out && !notSent ? (m.status === "read" ? " ✓✓" : " ✓") : ""}
                        </div>
                        {out && !notSent && m.template && ["late_3_days", "late_7_days", "pre_due_reminder", "due_day_reminder", "plan_offer", "promise_broken", "promise_reminder", "visit_notice"].includes(m.template) && (
                          <button className="mt-1 w-full rounded-md py-1 text-[11px] font-semibold text-white" style={{ background: color }} onClick={() => setTab("app")}>
                            Open
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
                <div ref={end} />
              </div>
              <ReplyBox disabled={busy || !account.telegram || account.telegram.status !== "active"} onSend={send} />
            </div>
          ) : (
            <div className="h-full overflow-y-auto">
              <MiniApp token={account.mini_app_token} shadow={shadow} onChange={onChange}
                version={account.messages.length + account.timeline.length} />
            </div>
          )}
        </div>
      </div>
      {sms.length > 0 && (
        <div className="mx-auto mt-2 w-[300px] rounded border border-sage-pale bg-white p-2 text-[11px]">
          <div className="font-semibold">SMS (opt-in invite)</div>
          {sms.map((m: any) => <div key={m.id} className="local mt-1">{m.body} <span className="text-slate/50">· {m.status}{m.rule ? ` ${m.rule}` : ""}</span></div>)}
        </div>
      )}
      <div className="mx-auto mt-3 w-[300px] space-y-2 rounded border border-warn/40 bg-warn-soft/40 p-2">
        <div className="text-[11px] font-semibold uppercase text-[#7A5A1E]">Demo: act as the borrower</div>
        <select className="input w-full" disabled={busy || !replies.length} value="" onChange={(e) => e.target.value && send(e.target.value)}>
          <option value="">Borrower replies…</option>
          {replies.map((r) => <option key={r.text} value={r.text}>{r.en} · {r.text}</option>)}
        </select>
        <button className="btn w-full justify-center" disabled={busy} onClick={pay}>Simulate payment of arrears</button>
        {note && <div className="text-[11px]">{note}</div>}
      </div>
    </div>
  );
}

function ReplyBox({ onSend, disabled }: { onSend: (t: string) => void; disabled: boolean }) {
  const [text, setText] = useState("");
  return (
    <form className="flex gap-1 bg-white p-1.5" onSubmit={(e) => { e.preventDefault(); if (text) { onSend(text); setText(""); } }}>
      <input className="local flex-1 rounded-full border border-sage-pale px-3 py-1 text-[12px]" placeholder={disabled ? "Borrower not on Telegram" : "Message"}
        disabled={disabled} value={text} onChange={(e) => setText(e.target.value)} />
      <button className="rounded-full bg-green-slate px-3 text-[12px] text-white" disabled={disabled}>Send</button>
    </form>
  );
}
