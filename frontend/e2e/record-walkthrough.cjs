// Records a captioned video of the 5-minute demo path.
// Usage: node e2e/record-walkthrough.cjs <out-dir>   (API :8000, Vite :5173, freshly seeded)
const { chromium } = require("playwright");
const path = require("path");

const WEB = process.env.WEB ?? "http://localhost:5173";
const API = process.env.API ?? "http://localhost:8000";
const OUT = process.argv[2] ?? "/tmp/walkthrough";
const SAMPLE = path.resolve(__dirname, "../../sample_data");
const SIZE = { width: 1280, height: 800 };

const j = async (p, opts = {}) => {
  const r = await fetch(API + p, opts);
  if (!r.ok) throw new Error(`${p} ${r.status}`);
  return r.json();
};
const post = (p, body) => j(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: SIZE, recordVideo: { dir: OUT, size: SIZE } });
  const p = await ctx.newPage();
  const pause = (ms) => p.waitForTimeout(ms);
  // Caption bar, re-added after every navigation.
  let current = "";
  const caption = async (text, ms = 3500) => {
    current = text;
    await p.evaluate((t) => {
      let el = document.getElementById("__cap");
      if (!el) {
        el = document.createElement("div");
        el.id = "__cap";
        el.style.cssText = "position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:99999;max-width:1100px;" +
          "background:rgba(47,62,70,.94);color:#fff;font:600 17px/1.4 Inter,system-ui,sans-serif;padding:10px 18px;border-radius:8px;" +
          "box-shadow:0 4px 18px rgba(0,0,0,.25);text-align:center";
        document.body.appendChild(el);
      }
      el.textContent = t;
    }, text);
    await pause(ms);
  };
  p.on("framenavigated", (f) => f === p.mainFrame() && current && setTimeout(() => caption(current, 0).catch(() => {}), 400));
  const go = async (url, ms = 1800) => {
    await p.goto(WEB + url);
    await pause(ms);
  };
  const setCtx = (tenant, role, userId) =>
    p.evaluate(([t, r, u]) => {
      localStorage.setItem("tenant", JSON.stringify(t));
      localStorage.setItem("role", JSON.stringify(r));
      localStorage.setItem("userId", JSON.stringify(u ?? null));
    }, [tenant, role, userId]);
  const scroll = async (y, ms = 1500) => {
    await p.evaluate((yy) => window.scrollTo({ top: yy, behavior: "smooth" }), y);
    await pause(ms);
  };

  // Title
  await go("/portfolio", 500);
  await setCtx("mm-new", "head_of_collections");
  await go("/portfolio", 800);
  await caption("Collections console for a Myanmar MFI. All data is fictional sample data.", 3500);

  // 1. First import
  await caption("1. Day one: the lender uploads its Mifos X export (loans, schedule, savings).", 2500);
  await p.click("text=Import core banking export");
  await pause(800);
  await p.setInputFiles("input[type=file] >> nth=0", `${SAMPLE}/mifos_loans_active_mm.csv`);
  await p.setInputFiles("input[type=file] >> nth=1", `${SAMPLE}/mifos_repayment_schedule_mm.csv`);
  await p.setInputFiles("input[type=file] >> nth=2", `${SAMPLE}/mifos_savings_transactions_mm.csv`);
  await p.click("text=Next: map columns");
  await p.waitForSelector("text=Validate and import");
  await caption("Columns are matched automatically. Any other core-banking file can be mapped by hand and saved.", 4000);
  await scroll(500, 1200);
  await p.click("text=Validate and import");
  await p.waitForSelector("text=Validation report", { timeout: 120000 });
  await p.locator("text=Validation report").scrollIntoViewIfNeeded();
  await caption("Validation catches a duplicate loan ID, a negative balance, a future date and missing phones.", 4500);
  await scroll(0, 600);
  await p.click("text=Close import");
  await caption("The free health check: PAR by branch, overdue book by bucket, Telegram reach.", 4500);
  await scroll(420);
  await caption("Repayments posted after the arrears run: check these before anyone chases.", 4000);
  await scroll(900);
  await caption("Top 50 ranked visit list with reasons, downloadable. A one-page PDF goes on the lender's letterhead.", 4500);

  // 2. Today
  await setCtx("mm-demo", "head_of_collections");
  await go("/today");
  await caption("2. Eight weeks later (simulated history). Today: who do we chase, and how?", 4000);
  await caption("Ranked by money at stake against likelihood to pay, with the reasons shown for every case.", 4500);
  const sug = await j("/api/t/mm-demo/demo/suggested-case");
  const acc = await j(`/api/t/mm-demo/cases/${sug.case_id}`);

  // 3. Borrower account and messaging
  await go(`/cases/${sug.case_id}`);
  await caption(`3. One borrower, ${acc.borrower.name}: loan, savings trend, reasons, full event timeline.`, 4500);
  await p.click("text=Send a template");
  await pause(600);
  await p.click("text=Send through gate");
  await pause(1500);
  await caption("A Burmese reminder under the lender's own name, checked against every contact rule before sending.", 5000);
  await caption("English copy underneath is for staff only. The borrower never sees the software vendor's name.", 4000);
  await p.selectOption('select:has-text("Borrower replies")', { index: 1 });
  await pause(1500);
  await caption('Borrower replies "I can\'t pay this week". It is classified and a plan offer goes back.', 4500);
  await p.click('button:has-text("Mini App")');
  await pause(1500);
  await caption("The borrower opens the lender's Mini App: amount due, pay, promise a date, or say they can't pay.", 4500);
  await p.click('button:has-text("မပေးနိုင်ပါ")');
  await pause(800);
  await p.click('button:has-text("လျော့သွားသည်")');
  await pause(500);
  const inputs = p.locator("input[inputmode=numeric]");
  await inputs.nth(0).fill(String(sug.income_now));
  await inputs.nth(1).fill("0");
  await caption("Three questions: has income changed, how much now, any new debts.", 3500);
  await p.click('button:has-text("ရှေ့ဆက်ရန်")');
  await pause(1500);
  await caption("Plans the borrower can afford. Options above their capacity are never shown.", 4000);
  await caption("The reschedule extends the loan beyond the lender's limit, so it is marked as needing branch approval.", 4500);

  // 4. Approval
  await p.locator('div.rounded-xl:has-text("ခွဲရုံး အတည်ပြုချက် လိုအပ်သည်") button').first().click();
  await pause(1500);
  await caption("4. The borrower picks it. They get an automatic holding message while the branch decides.", 4500);
  const meta = await j("/api/t/mm-demo/meta");
  const br = meta.branches.find((x) => x.name === acc.branch);
  const bm = meta.users.find((u) => u.role === "branch_manager" && u.branch_id === br.id);
  await setCtx("mm-demo", "branch_manager", bm.id);
  await go("/approvals");
  await caption(`Branch manager view: original vs proposed, capacity, and exactly which limit is breached and by how much.`, 5500);
  await p.click("button:has-text('Approve')");
  await pause(1500);
  await caption("Approved in one tap. Decision, approver and time are recorded.", 3000);

  // 5. Payment and posting
  await setCtx("mm-demo", "head_of_collections");
  await go(`/cases/${sug.case_id}`);
  await caption("The borrower gets the confirmation and an agreement PDF in Burmese on the lender's letterhead.", 4500);
  await p.click("text=Simulate payment due now");
  await pause(2000);
  await caption("5. A payment arrives from the wallet provider and is matched by its reference.", 4000);
  await scroll(1400, 1500);
  await caption("Every step is an event in an append-only log. Nothing is edited in place.", 4000);
  await go("/payments");
  await p.click("text=Generate posting file");
  await pause(1500);
  await caption("The Mifos posting file for the credit team. A payment can never be exported twice.", 4500);

  // 6. Advance a day, officer view
  await caption("6. Advance the clock one day: reminders go out, and non-responders move to officer visits.", 3000);
  await post("/api/t/mm-demo/demo/advance");
  await go("/field-manager");
  await caption("Field manager view: each officer's visits today, carried over, and completion rate.", 4500);
  const officerId = (await j("/api/t/mm-demo/field/manager")).officers.sort((a, b) => b.today_assigned - a.today_assigned)[0].officer_id;
  const officer = meta.users.find((u) => u.role === "credit_officer" && u.officer_id === officerId);
  await setCtx("mm-demo", "credit_officer", officer.id);
  await p.evaluate(() => {
    document.body.innerHTML = '<div style="height:100vh;display:flex;align-items:center;justify-content:center;background:#E6EAE3">' +
      '<iframe id="ph" src="/field" style="width:360px;height:720px;border:10px solid #2F3E46;border-radius:28px;background:#fff"></iframe></div>';
  });
  await caption("The credit officer's phone (360px, installable): today's visits grouped by ward, tap to call.", 4500);
  const f = p.frameLocator("#ph");
  await f.locator("div.rounded-lg.border.bg-white >> nth=0").locator("div.flex.items-start").click();
  await pause(1200);
  await f.locator("button:has-text('Promised')").click();
  await f.locator("input[inputmode=decimal]").first().fill("20000");
  await f.locator("input[type=date]").fill("2026-11-12");
  await f.locator("input[type=file]").setInputFiles(path.resolve(__dirname, "visit-photo.jpg"));
  await pause(1200);
  await caption("Outcome, promise amount and date, photo with time and GPS. It feeds straight back into the case.", 4500);
  await f.locator("button:has-text('Save outcome')").click();
  await pause(2000);

  // 7. Compliance
  await setCtx("mm-demo", "head_of_collections");
  await post("/api/t/mm-demo/demo/set-time", { hh: 20, mm: 30 });
  const other = (await j("/api/t/mm-demo/today?segment=nudge")).items.find((x) => x.telegram && x.arm === "treatment" && !x.paused && x.case_id !== sug.case_id);
  await post(`/api/t/mm-demo/cases/${other.case_id}/actions/send_template`, {});
  const vuln = (await j("/api/t/mm-demo/today?segment=plan")).items.find((x) => x.telegram && x.arm === "treatment" && !x.paused);
  await post("/api/t/mm-demo/demo/reply", { case_id: vuln.case_id, text: "အမေ ဆေးရုံတက်နေလို့ပါ" });
  await post("/api/t/mm-demo/demo/set-time", { hh: 9, mm: 30 });
  await go("/compliance");
  await caption("7. Compliance: every message attempted, allowed or blocked, with its rule ID and policy version.", 4500);
  await p.selectOption(`select:has-text("All statuses")`, "blocked");
  await pause(1500);
  await caption("A reminder tried at 20:30 was held by the quiet-hours rule (CR-08) and rescheduled for 08:00.", 4500);
  await scroll(700);
  await caption('A borrower wrote "my mother is in hospital": flagged as vulnerability, automation paused, a manager owns it.', 5500);

  // 8. Results
  await go("/results");
  await caption("8. Results. Every figure here is simulated, and labelled so.", 3500);
  await caption("PAR30 trend, the number funders watch, plus treatment vs a 15% control group that gets the lender's usual process.", 5500);
  await scroll(420);
  await caption("Honest about sample size: the difference is shown with its 95% interval.", 4500);
  await scroll(1000);
  await caption("Officer visits avoided, cost per unit recovered, and the fee formula with its working shown.", 5000);
  await scroll(0, 800);
  await caption("End of walkthrough.", 2500);

  await ctx.close();
  await b.close();
  console.log("done");
})().catch((e) => {
  console.error("FAILED", e);
  process.exit(1);
});
