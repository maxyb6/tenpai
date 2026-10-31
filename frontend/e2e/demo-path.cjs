// The 5-minute demo path, end to end in a real browser.
// Usage: node e2e/demo-path.cjs [shots-dir]   (API on :8000, Vite on :5173, freshly seeded)
const { chromium } = require("playwright");
const path = require("path");

const WEB = process.env.WEB ?? "http://localhost:5173";
const API = process.env.API ?? "http://localhost:8000";
const SHOTS = process.argv[2] ?? "/tmp/tenpai-demo";
const SAMPLE = path.resolve(__dirname, "../../sample_data");

// If the deployment has a console password, send it (any username).
const PASSWORD = process.env.DEMO_PASSWORD;
const AUTH = PASSWORD ? { Authorization: "Basic " + Buffer.from(`demo:${PASSWORD}`).toString("base64") } : {};

const j = async (p, opts = {}) => {
  const r = await fetch(API + p, { ...opts, headers: { ...AUTH, ...(opts.headers ?? {}) } });
  if (!r.ok) throw new Error(`${p} ${r.status} ${await r.text()}`);
  return r.json();
};
const post = (p, body, headers = {}) =>
  j(p, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body ?? {}) });

(async () => {
  require("fs").mkdirSync(SHOTS, { recursive: true });
  const b = await chromium.launch();
  const creds = PASSWORD ? { httpCredentials: { username: "demo", password: PASSWORD } } : {};
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1000 }, ...creds });
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("response", (r) => r.url().includes("/api/") && r.status() >= 500 && errors.push(`${r.status()} ${r.url()}`));
  const shot = (n) => p.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: false });
  const setCtx = async (tenant, role, userId) => {
    await p.evaluate(([t, r, u]) => {
      localStorage.setItem("tenant", JSON.stringify(t));
      localStorage.setItem("role", JSON.stringify(r));
      localStorage.setItem("userId", JSON.stringify(u ?? null));
    }, [tenant, role, userId]);
  };
  const step = (n, s) => console.log(`step ${n}: ${s}`);

  // 1. Portfolio health from a first import.
  await p.goto(`${WEB}/portfolio`);
  await setCtx("mm-new", "head_of_collections");
  await p.goto(`${WEB}/portfolio`);
  await p.click("text=Import core banking export");
  await p.setInputFiles("input[type=file] >> nth=0", `${SAMPLE}/mifos_loans_active_mm.csv`);
  await p.setInputFiles("input[type=file] >> nth=1", `${SAMPLE}/mifos_repayment_schedule_mm.csv`);
  await p.setInputFiles("input[type=file] >> nth=2", `${SAMPLE}/mifos_savings_transactions_mm.csv`);
  await p.click("text=Next: map columns");
  await p.waitForSelector("text=Validate and import");
  await p.click("text=Validate and import");
  await p.waitForSelector("text=Validation report", { timeout: 120000 });
  await p.waitForTimeout(1500);
  await shot("1-import-health");
  const hc = await j("/api/t/mm-new/health");
  step(1, `imported, ${hc.summary.overdue_loans} overdue, PAR30 ${(hc.summary.par30 * 100).toFixed(1)}%, ${hc.par.by_branch.length} branches`);

  // 2. Today: the top Nudge case and its reason codes.
  await setCtx("mm-demo", "head_of_collections");
  const sug = await j("/api/t/mm-demo/demo/suggested-case");
  const pick = await j(`/api/t/mm-demo/cases/${sug.case_id}`);
  await p.goto(`${WEB}/today`);
  await p.selectOption("select:has(option[value=nudge])", "nudge");
  await p.waitForTimeout(1200);
  await shot("2-today");
  step(2, `case ${pick.case.id} ${pick.borrower.name}: ${pick.case.reasons.map((r) => r.text).join("; ")}`);

  // 3. Burmese reminder, "can't pay this week", three questions, plans.
  await p.goto(`${WEB}/cases/${pick.case.id}`);
  await p.click("text=Send a template");
  await p.click("text=Send through gate");
  await p.waitForTimeout(1200);
  await p.selectOption('select:has-text("Borrower replies")', { index: 1 });
  await p.waitForTimeout(1500);
  await shot("3a-chat");
  await p.click('button:has-text("Mini App")');
  await p.waitForTimeout(1000);
  await p.click('button:has-text("မပေးနိုင်ပါ")');
  await p.click('button:has-text("လျော့သွားသည်")');
  const inputs = p.locator("input[inputmode=numeric]");
  await inputs.nth(0).fill(String(sug.income_now));
  await inputs.nth(1).fill("0");
  await p.click('button:has-text("ရှေ့ဆက်ရန်")');
  await p.waitForTimeout(1500);
  await shot("3b-plans");
  const outside = p.locator('div.rounded-xl:has-text("ခွဲရုံး အတည်ပြုချက် လိုအပ်သည်") button');
  const nOutside = await outside.count();
  step(3, `plans shown, ${nOutside} outside policy`);

  // 4. Out-of-policy plan, branch manager approves in one tap.
  if (nOutside) await outside.first().click();
  else await p.locator("div.rounded-xl button:has-text('ဤအစီအစဉ်ကို ရွေးမည်')").first().click();
  await p.waitForTimeout(1500);
  const meta = await j("/api/t/mm-demo/meta");
  const br = meta.branches.find((x) => x.name === pick.branch);
  const bm = meta.users.find((u) => u.role === "branch_manager" && u.branch_id === br.id);
  await setCtx("mm-demo", "branch_manager", bm.id);
  await p.goto(`${WEB}/approvals`);
  await p.waitForTimeout(1500);
  await shot("4a-approvals");
  await p.waitForSelector("button:has-text('Approve')", { timeout: 15000 });
  await p.locator("button:has-text('Approve')").first().click();
  await p.waitForTimeout(2000);
  await setCtx("mm-demo", "head_of_collections");
  const after = await j(`/api/t/mm-demo/cases/${pick.case.id}`);
  step(4, `state ${after.case.state}, last message ${after.messages.at(-1).template}`);

  // 5. Payment matched, Mifos posting file.
  await p.goto(`${WEB}/cases/${pick.case.id}`);
  await p.click("text=Simulate payment due now");
  await p.waitForTimeout(2000);
  await shot("4b-account");
  await p.goto(`${WEB}/payments`);
  await p.waitForTimeout(1200);
  await p.click("text=Generate posting file");
  await p.waitForTimeout(1500);
  await shot("5-payments");
  const pays = await j("/api/t/mm-demo/payments");
  step(5, `batches ${pays.batches.length}, awaiting export ${pays.counts.awaiting_export}`);

  // 6. Advance a day; a non-responder moves to Visit; officer logs an outcome at 360px.
  const visitsBefore = (await j("/api/t/mm-demo/today")).counters.visits_assigned;
  const adv = await post("/api/t/mm-demo/demo/advance");
  const run = adv.runs[0];
  const visitsAfter = (await j("/api/t/mm-demo/today")).counters.visits_assigned;
  step(6, `advanced to ${adv.now}: ${run.reminders} reminders, ${run.visits_assigned} new visits (${visitsBefore} -> ${visitsAfter})`);
  const officerId = (await j("/api/t/mm-demo/field/manager")).officers.sort((a, b) => b.today_assigned - a.today_assigned)[0].officer_id;
  const officerUser = meta.users.find((u) => u.role === "credit_officer" && u.officer_id === officerId);
  const mctx = await b.newContext({ viewport: { width: 360, height: 760 }, ...creds });
  const m = await mctx.newPage();
  m.on("pageerror", (e) => errors.push("officer " + e.message));
  await m.goto(`${WEB}/field`);
  await m.evaluate((u) => {
    localStorage.setItem("tenant", '"mm-demo"');
    localStorage.setItem("role", '"credit_officer"');
    localStorage.setItem("userId", JSON.stringify(u));
  }, officerUser.id);
  await m.goto(`${WEB}/field`);
  await m.waitForTimeout(1500);
  await m.locator("div.rounded-lg.border.bg-white >> nth=0").locator("div.flex.items-start").click();
  await m.click("button:has-text('Promised')");
  const fields = m.locator("input[inputmode=decimal]");
  await fields.first().fill("20000");
  await m.fill("input[type=date]", "2026-11-12");
  await m.setInputFiles("input[type=file]", path.resolve(__dirname, "visit-photo.jpg"));
  await m.waitForTimeout(800);
  await m.screenshot({ path: `${SHOTS}/6a-officer.png` });
  await m.click("button:has-text('Save outcome')");
  await m.waitForTimeout(1500);
  await m.screenshot({ path: `${SHOTS}/6b-officer-done.png` });

  // 7. Compliance: quiet-hours block with rule ID; vulnerability reply pauses automation.
  await post("/api/t/mm-demo/demo/set-time", { hh: 20, mm: 30 });
  const other = (await j("/api/t/mm-demo/today?segment=nudge")).items.find((x) => x.telegram && x.arm === "treatment" && !x.paused && x.case_id !== pick.case.id);
  const blocked = await post(`/api/t/mm-demo/cases/${other.case_id}/actions/send_template`, {});
  const vuln = (await j("/api/t/mm-demo/today?segment=plan")).items.find((x) => x.telegram && x.arm === "treatment" && !x.paused);
  const v = await post("/api/t/mm-demo/demo/reply", { case_id: vuln.case_id, text: "အမေ ဆေးရုံတက်နေလို့ပါ" });
  await post("/api/t/mm-demo/demo/set-time", { hh: 9, mm: 30 });
  await p.goto(`${WEB}/compliance`);
  await p.waitForTimeout(1500);
  await shot("7-compliance");
  step(7, `reminder at 20:30: ${blocked.status} ${blocked.rule}; vulnerability reply: ${v.classification}`);

  // Borrower links open without the console password.
  const anon = await b.newPage({ viewport: { width: 360, height: 740 } });
  const tok = (await j(`/api/t/mm-demo/cases/${pick.case.id}`)).mini_app_token;
  const resp = await anon.goto(`${WEB}/m/${tok}`);
  await anon.waitForTimeout(1500);
  await anon.screenshot({ path: `${SHOTS}/7b-mini-app-no-password.png` });
  step("7b", `borrower Mini App without password: HTTP ${resp.status()}`);

  // 8. Results.
  await p.goto(`${WEB}/results`);
  await p.waitForTimeout(2000);
  await shot("8-results");
  const r = await j("/api/t/mm-demo/results");
  step(8, `cure ${(r.by_arm.treatment.cure_rate * 100).toFixed(1)}% vs ${(r.by_arm.control.cure_rate * 100).toFixed(1)}%, PAR30 ${(r.par_trend.at(-1).par30 * 100).toFixed(1)}%, fee ${r.fee.total}`);

  console.log(errors.length ? `ERRORS ${JSON.stringify(errors)}` : "NO ERRORS");
  await b.close();
  process.exit(errors.length ? 1 : 0);
})().catch((e) => {
  console.error("FAILED", e);
  process.exit(1);
});
