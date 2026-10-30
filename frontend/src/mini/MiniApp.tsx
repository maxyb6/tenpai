// Borrower-facing Mini App. Lender brand only; local script first.
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { mini } from "../api";
import { toMajor, toMinor } from "../format";

type L = "my" | "km" | "en";
const S: Record<L, Record<string, string>> = {
  my: {
    hello: "မင်္ဂလာပါ", due: "ပေးရန်ကျန်ငွေ", overdue: "ရက် နောက်ကျ", pay: "ငွေပေးချေရန်", promise: "ပေးမည့်ရက် ပြောရန်",
    cant: "မပေးနိုင်ပါ", wallet: "မိုဘိုင်းငွေပေးချေမှု app ဖြင့် ပေးရန်", saveqr: "QR ကို ဓာတ်ပုံအဖြစ် သိမ်းရန်",
    ref: "ရည်ညွှန်းနံပါတ်", back: "နောက်သို့", date: "ရက်စွဲ", amount: "ပမာဏ", confirm: "အတည်ပြုရန်",
    q1: "သင့်အိမ်ထောင်စု ဝင်ငွေ ပြောင်းလဲသွားပါသလား", less: "လျော့သွားသည်", same: "မပြောင်းပါ", more: "တိုးလာသည်",
    q2: "ယခု တစ်လ အိမ်ထောင်စု ဝင်ငွေ ဘယ်လောက်ရှိပါသလဲ", q3: "ချေးငွေအသစ် ရှိပါသလား (တစ်လ ပြန်ဆပ်ငွေ)",
    next: "ရှေ့ဆက်ရန်", options: "သင့်အတွက် ရွေးချယ်စရာများ", per: "တစ်ရစ်လျှင်", until: "ပြီးဆုံးမည့်ရက်",
    total: "စုစုပေါင်း", choose: "ဤအစီအစဉ်ကို ရွေးမည်", needs: "ခွဲရုံး အတည်ပြုချက် လိုအပ်သည်",
    pending: "သင့်အစီအစဉ်ကို ခွဲရုံးက စစ်ဆေးနေပါသည်", active: "သင့် ပေးချေမှုအစီအစဉ်", charter: "ကျွန်ုပ်တို့၏ ကတိကဝတ်",
    complain: "တိုင်ကြားရန်", sent: "ပေးပို့ပြီးပါပြီ", promised: "ကတိပြုထားသည်", none: "ယခုအချိန်တွင် ကိုက်ညီသော အစီအစဉ် မရှိပါ။ သင်၏ ချေးငွေအရာရှိက ဆက်သွယ်ပါမည်။",
    relief: "ပထမ", periods: "ရစ်",
  },
  km: {
    hello: "សួស្តី", due: "ចំនួនត្រូវបង់", overdue: "ថ្ងៃយឺត", pay: "បង់ប្រាក់", promise: "ប្រាប់ថ្ងៃដែលខ្ញុំនឹងបង់",
    cant: "ខ្ញុំមិនអាចបង់បាន", wallet: "បង់តាមកម្មវិធីធនាគារ", saveqr: "រក្សាទុក QR ក្នុងរូបភាព",
    ref: "លេខយោង", back: "ត្រឡប់", date: "កាលបរិច្ឆេទ", amount: "ចំនួន", confirm: "បញ្ជាក់",
    q1: "តើប្រាក់ចំណូលគ្រួសាររបស់អ្នកបានផ្លាស់ប្តូរទេ?", less: "ថយចុះ", same: "ដដែល", more: "កើនឡើង",
    q2: "ប្រាក់ចំណូលគ្រួសារប្រចាំខែឥឡូវនេះប៉ុន្មាន?", q3: "មានបំណុលថ្មីទេ? (ប្រាក់សងប្រចាំខែ)",
    next: "បន្ទាប់", options: "ជម្រើសសម្រាប់អ្នក", per: "ក្នុងមួយលើក", until: "បញ្ចប់នៅ",
    total: "សរុប", choose: "ជ្រើសរើសផែនការនេះ", needs: "ត្រូវការការអនុម័តពីសាខា",
    pending: "សាខាកំពុងពិនិត្យផែនការរបស់អ្នក", active: "ផែនការបង់ប្រាក់របស់អ្នក", charter: "ការប្តេជ្ញារបស់យើង",
    complain: "ដាក់ពាក្យបណ្តឹង", sent: "បានផ្ញើ", promised: "បានសន្យា", none: "ឥឡូវនេះមិនមានផែនការដែលសមស្របទេ។ មន្ត្រីឥណទានរបស់អ្នកនឹងទាក់ទងអ្នក។",
    relief: "ដំបូង", periods: "លើក",
  },
  en: {
    hello: "Hello", due: "Amount due", overdue: "days late", pay: "Pay now", promise: "Tell us when you will pay",
    cant: "I can't pay", wallet: "Pay with your wallet or bank app", saveqr: "Save QR to photos",
    ref: "Reference", back: "Back", date: "Date", amount: "Amount", confirm: "Confirm",
    q1: "Has your household income changed?", less: "Less", same: "No change", more: "More",
    q2: "How much does your household earn per month now?", q3: "Any new debts? (monthly repayment)",
    next: "Next", options: "Options for you", per: "per instalment", until: "Ends",
    total: "Total", choose: "Choose this plan", needs: "Needs branch approval",
    pending: "Your branch is reviewing your plan", active: "Your repayment plan", charter: "Our promise to you",
    complain: "Make a complaint", sent: "Sent", promised: "Promised", none: "No plan fits right now. Your loan officer will contact you.",
    relief: "First", periods: "instalments",
  },
};
const PLAN_NAME: Record<L, Record<string, string>> = {
  my: { catch_up: "ကျန်ငွေ ခွဲပေးခြင်း", reschedule: "ပေးချေမှုကာလ တိုးခြင်း", short_relief: "ခေတ္တ သက်သာခွင့်" },
  km: { catch_up: "បង់តាមទាន់", reschedule: "ពន្យារពេលបង់", short_relief: "សម្រាលបណ្តោះអាសន្ន" },
  en: { catch_up: "Catch up", reschedule: "Reschedule", short_relief: "Short relief" },
};

export function MiniApp({ token, shadow = false, onChange, version = 0 }: {
  token: string; shadow?: boolean; onChange?: () => void; version?: number;
}) {
  const [st, setSt] = useState<any>();
  const [view, setView] = useState<"home" | "pay" | "promise" | "q" | "plans" | "charter" | "complaint">("home");
  const [payReq, setPayReq] = useState<any>();
  const [ans, setAns] = useState<{ changed?: string; income?: string; debt?: string }>({});
  const [plans, setPlans] = useState<any>();
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => mini.get<any>(token).then(setSt).catch((e) => setErr(e.message)), [token]);
  useEffect(() => {
    load();
  }, [load, version]);
  const lang = (st?.lang ?? "en") as L;
  const s = S[lang] ?? S.en;
  const en = S.en;
  const color = st?.brand?.colors?.primary ?? "#333";
  const act = async (fn: () => Promise<any>) => {
    setBusy(true);
    setErr(undefined);
    try {
      const r = await fn();
      onChange?.();
      return r;
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const T = ({ k }: { k: string }) => (
    <>
      <span>{s[k]}</span>
      {shadow && lang !== "en" && <span className="block text-[10px] font-normal opacity-60">{en[k]}</span>}
    </>
  );
  if (err && !st) return <div className="p-4 text-sm">{err}</div>;
  if (!st) return <div className="p-4 text-sm opacity-60">…</div>;
  const btn = "w-full rounded-lg px-3 py-3 text-[15px] font-semibold";
  const cur = st.loan?.currency;

  return (
    <div className="local min-h-full text-[14px]" style={{ background: st.brand.colors?.background ?? "#fff" }}>
      <div className="flex items-center gap-2 px-4 py-3 text-white" style={{ background: color }}>
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-white/20 font-bold">{st.brand.logo_text}</span>
        <div className="leading-tight">
          <div className="font-semibold">{lang === "en" ? st.brand.name : st.brand.name_local ?? st.brand.name}</div>
          {st.sample && <div className="text-[10px] opacity-80">SAMPLE</div>}
        </div>
      </div>
      <div className="space-y-3 p-4">
        {err && <div className="rounded bg-red-50 p-2 text-[12px] text-red-700">{err}</div>}
        {view === "home" && (
          <>
            <div>
              {s.hello} {st.borrower.name}
            </div>
            {st.loan && (
              <div className="rounded-xl bg-white p-4 shadow-sm">
                <div className="text-[12px] opacity-70"><T k="due" /></div>
                <div className="text-[26px] font-bold" style={{ color }}>{st.loan.arrears.text}</div>
                {shadow && lang !== "en" && <div className="text-[11px] opacity-60">{st.loan.arrears.en}</div>}
                {st.loan.days_overdue > 0 && (
                  <div className="mt-1 text-[13px] text-red-700">{st.loan.days_overdue} {s.overdue}</div>
                )}
              </div>
            )}
            {st.pending_plan && (
              <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-[13px]"><T k="pending" />: {st.pending_plan.instalment.text}</div>
            )}
            {st.active_plan && (
              <div className="rounded-xl border border-green-300 bg-green-50 p-3 text-[13px]">
                <div className="font-semibold"><T k="active" /></div>
                {st.active_plan.instalment.text} {s.per} · {s.until} {st.active_plan.end_date.text}
              </div>
            )}
            {st.promise && (
              <div className="rounded-xl bg-white p-3 text-[13px] shadow-sm">{s.promised}: {st.promise.amount.text} · {st.promise.date}</div>
            )}
            {st.plans.length > 0 && !st.pending_plan && !st.active_plan && (
              <button className={`${btn} border-2 bg-white`} style={{ borderColor: color, color }}
                onClick={() => { setPlans({ plans: st.plans }); setView("plans"); }}>
                <T k="options" />
              </button>
            )}
            <button className={`${btn} text-white`} style={{ background: color }} disabled={busy}
              onClick={() => act(async () => { setPayReq(await mini.post(token, "/pay")); setView("pay"); })}>
              <T k="pay" />
            </button>
            {st.loan?.days_overdue > 0 && !st.pending_plan && !st.active_plan && (
              <>
                <button className={`${btn} bg-white shadow-sm`} onClick={() => setView("promise")}><T k="promise" /></button>
                <button className={`${btn} bg-white shadow-sm`} onClick={() => setView("q")}><T k="cant" /></button>
              </>
            )}
            <div className="flex justify-between pt-2 text-[12px] underline opacity-80">
              <button onClick={() => setView("charter")}><T k="charter" /></button>
              <button onClick={() => setView("complaint")}><T k="complain" /></button>
            </div>
          </>
        )}
        {view === "pay" && payReq && (
          <>
            <div className="rounded-xl bg-white p-4 text-center shadow-sm">
              <div className="text-[24px] font-bold" style={{ color }}>{payReq.amount.text}</div>
              <div className="text-[12px] opacity-70">{s.ref}: {payReq.reference}</div>
            </div>
            <a className={`${btn} block text-center text-white`} style={{ background: color }} href={payReq.deeplink}><T k="wallet" /></a>
            <div className="rounded-xl bg-white p-3 text-center shadow-sm">
              <img alt="QR" className="mx-auto w-40" src={`data:image/png;base64,${payReq.qr_png}`} />
              <a className="mt-1 inline-block text-[12px] underline" download={`${payReq.reference}.png`} href={`data:image/png;base64,${payReq.qr_png}`}><T k="saveqr" /></a>
            </div>
            <button className="text-[13px] underline" onClick={() => { setView("home"); load(); }}>{s.back}</button>
          </>
        )}
        {view === "promise" && <PromiseForm s={s} color={color} cur={cur} st={st} busy={busy}
          onBack={() => setView("home")}
          onSubmit={(amount: number, date: string) => act(async () => { setSt(await mini.post(token, "/promise", { amount, due_date: date })); setView("home"); })} />}
        {view === "q" && (
          <div className="space-y-3">
            <div className="font-semibold"><T k="q1" /></div>
            <div className="grid grid-cols-3 gap-2">
              {(["less", "same", "more"] as const).map((k) => (
                <button key={k} className={`rounded-lg border px-2 py-2 ${ans.changed === k ? "text-white" : "bg-white"}`}
                  style={ans.changed === k ? { background: color } : {}} onClick={() => setAns({ ...ans, changed: k })}>
                  {s[k]}
                </button>
              ))}
            </div>
            <div className="font-semibold"><T k="q2" /></div>
            <input inputMode="numeric" className="w-full rounded-lg border px-3 py-2" value={ans.income ?? ""} placeholder={cur}
              onChange={(e) => setAns({ ...ans, income: e.target.value.replace(/[^0-9.]/g, "") })} />
            <div className="font-semibold"><T k="q3" /></div>
            <input inputMode="numeric" className="w-full rounded-lg border px-3 py-2" value={ans.debt ?? ""} placeholder="0"
              onChange={(e) => setAns({ ...ans, debt: e.target.value.replace(/[^0-9.]/g, "") })} />
            <button className={`${btn} text-white`} style={{ background: color }} disabled={!ans.changed || busy}
              onClick={() => act(async () => {
                const r = await mini.post<any>(token, "/cant-pay", {
                  income_changed: ans.changed,
                  income_now: ans.income ? toMinor(Number(ans.income), cur) : null,
                  new_debt_repayments: ans.debt ? toMinor(Number(ans.debt), cur) : 0,
                });
                setPlans(r);
                setView("plans");
              })}>
              <T k="next" />
            </button>
            <button className="text-[13px] underline" onClick={() => setView("home")}>{s.back}</button>
          </div>
        )}
        {view === "plans" && plans && (
          <div className="space-y-3">
            <div className="font-semibold"><T k="options" /></div>
            {!plans.plans.length && <div className="rounded-xl bg-white p-3 shadow-sm">{s.none}</div>}
            {plans.plans.map((p: any) => (
              <div key={p.id} className="rounded-xl bg-white p-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <div className="font-semibold">{PLAN_NAME[lang][p.type]}</div>
                  {!p.within_policy && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800">{s.needs}</span>}
                </div>
                {shadow && lang !== "en" && <div className="text-[10px] opacity-60">{PLAN_NAME.en[p.type]}{!p.within_policy ? " · needs branch approval" : ""}</div>}
                {p.relief && <div className="mt-1 text-[13px]">{s.relief} {p.relief_periods} {s.periods}: {p.relief.text}</div>}
                <div className="mt-1 text-[20px] font-bold" style={{ color }}>{p.instalment.text}</div>
                <div className="text-[12px] opacity-70">{s.per} · {s.until} {p.end_date.text} · {s.total} {p.total.text}</div>
                {shadow && lang !== "en" && <div className="text-[10px] opacity-60">{p.instalment.en} per instalment, total {p.total.en}, ends {p.end_date.value}</div>}
                <button className="mt-2 w-full rounded-lg py-2 font-semibold text-white" style={{ background: color }} disabled={busy}
                  onClick={() => act(async () => { setSt(await mini.post(token, `/plans/${p.id}/accept`)); setView("home"); })}>
                  {s.choose}
                </button>
              </div>
            ))}
            <button className="text-[13px] underline" onClick={() => setView("home")}>{s.back}</button>
          </div>
        )}
        {view === "charter" && (
          <div className="space-y-2">
            {st.charter.map((c: any, i: number) => (
              <div key={i} className="rounded-xl bg-white p-3 shadow-sm">
                <div className="font-semibold">{c.title}</div>
                <div className="text-[13px]">{c.body}</div>
                {shadow && lang !== "en" && <div className="mt-1 text-[10px] opacity-60">{st.charter_en[i].title}: {st.charter_en[i].body}</div>}
              </div>
            ))}
            <button className="text-[13px] underline" onClick={() => setView("home")}>{s.back}</button>
          </div>
        )}
        {view === "complaint" && <ComplaintForm s={s} color={color} busy={busy} onBack={() => setView("home")}
          onSubmit={(text: string) => act(async () => { await mini.post(token, "/complaint", { text }); setView("home"); load(); })} />}
      </div>
    </div>
  );
}

function PromiseForm({ s, color, cur, st, busy, onBack, onSubmit }: any) {
  const [date, setDate] = useState("");
  const [amount, setAmount] = useState(String(toMajor(st.loan.arrears.value, cur)));
  return (
    <div className="space-y-3">
      <label className="block">{s.date}<input type="date" className="mt-1 w-full rounded-lg border px-3 py-2" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <label className="block">{s.amount} ({cur})<input inputMode="numeric" className="mt-1 w-full rounded-lg border px-3 py-2" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
      <button className="w-full rounded-lg py-3 font-semibold text-white" style={{ background: color }} disabled={!date || busy}
        onClick={() => onSubmit(toMinor(Number(amount), cur), date)}>{s.confirm}</button>
      <button className="text-[13px] underline" onClick={onBack}>{s.back}</button>
    </div>
  );
}

function ComplaintForm({ s, color, busy, onBack, onSubmit }: any) {
  const [text, setText] = useState("");
  return (
    <div className="space-y-3">
      <textarea className="h-28 w-full rounded-lg border p-2" value={text} onChange={(e) => setText(e.target.value)} />
      <button className="w-full rounded-lg py-3 font-semibold text-white" style={{ background: color }} disabled={!text || busy}
        onClick={() => onSubmit(text)}>{s.complain}</button>
      <button className="text-[13px] underline" onClick={onBack}>{s.back}</button>
    </div>
  );
}

export default function MiniAppRoute() {
  const { token } = useParams();
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col [&>div]:flex-1">
      <MiniApp token={token!} />
    </div>
  );
}
