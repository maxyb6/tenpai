# Build prompt: Tenpai Collections (lender console, demo build)

You are building a working demo of Tenpai Collections, a collections platform for microfinance institutions (MFIs) in Myanmar and Cambodia. The demo will be shown to a Myanmar MFI on 5 or 6 November 2026 and must also run on a real loan-book export once an NDA is signed. Build it so the pilot version (real imports, real Telegram, real payment partner) slots into the same code rather than replacing it.

## 1. What Tenpai is

Tenpai is software the lender runs on its own book, under its own brand. It finds overdue borrowers, contacts them digitally first, offers plans they can afford within the lender's rules, takes payment through a licensed partner, and sends credit officers only where a visit is needed. Loans stay on the lender's books. Tenpai never buys debt, never holds borrower money, and never contacts a borrower under its own name.

Product reference: InDebted's **Receive** (indebted.co/solution/receive), its first-party collections platform, plus its **Comply** layer (indebted.co/product/comply). Not InDebted Collect, which is an outsourced agency. Copy the model, not the look:

| InDebted Receive / Comply | Tenpai equivalent |
|---|---|
| Ingests customer, account and communication data from the lender's systems | Imports the Mifos X overdue export (CSV/XLSX); any core banking file via column mapping |
| AI decisioning: behavioural scoring, segmentation, next-best action | Rules-based ranking with visible reason codes; ML later behind the same interface |
| Branded multichannel journeys (email, SMS, WhatsApp) | Lender-branded Telegram bot and Telegram Mini App; SMS only for opt-in |
| Branded self-serve portal: set up and change plans, pay in a few taps, unique secure link in every message | Mini App: see balance, pick one of 2-3 affordable plans, pay by QR or wallet deeplink; signed per-borrower link |
| Hardship and vulnerability pathways, contact limits | Affordability re-check, restructure plans within policy, hard contact limits, automation pauses on vulnerability |
| Comply Firewall: every outbound message checked against rules before send, with a trace | Send gate: every message checked against contact rules; allowed/blocked decision stored with rule ID |
| Comply Safeguard: detects vulnerability in inbound messages | Inbound reply classifier flags illness, death, disaster, job loss, migration, complaints; pauses automation and routes to a manager |
| Comply Audit | Immutable, exportable message and decision log |
| Pilot to prove uplift; 130+ dashboards | Control group from day one; a handful of dashboards that answer leadership's questions |

What InDebted does not have and Tenpai must: field credit officers as a channel (visit lists, outcome logging, photos), group and individual loans, savings-deposit behaviour as a risk signal, restructuring that respects MFI policy and loan classification, local scripts (Burmese, Khmer), local QR payments, and a Mifos posting file instead of an API into an enterprise CRM.

## 2. Whose product this is

Every screen belongs to the lender. The person logged in works at the MFI. Design each screen around a question that person asks (listed in section 6).

Users, all lender staff, switchable via a role picker in the demo:
- **Head of collections** (primary user, default role): runs strategy, sets rules, watches results.
- **Branch manager**: approves exceptions, manages officers, handles complaints. Sees only their branch.
- **Credit officer**: works today's visit list on a phone. Sees only their assigned borrowers.
- **Leadership** (CEO/CFO): read-only results, PAR, recovery against control, fees.

The borrower is not a console user. The borrower sees only a Telegram bot and Mini App carrying the lender's name and logo. In the console, show what the borrower saw as a phone-frame preview on the borrower's account page.

## 3. Non-negotiables

1. Lender's brand on everything the borrower sees. "Tenpai" appears nowhere borrower-facing.
2. Lender's rules decide. Policy (plan limits, contact limits, approval thresholds, scripts) lives in Settings, is versioned, and every decision records the policy version it used.
3. Tenpai never holds money. Payments go from borrower to the lender's account at the partner bank or provider. Tenpai only receives payment notifications and matches them.
4. Approved scripts only. No generated free text is sent to borrowers. Messages are lender-approved templates with variables filled in. An LLM may classify inbound replies; it may not write outbound ones.
5. Every action is an event in an append-only log. Screens read projections built from events. Nothing is edited in place without a new event.
6. Ranking is explainable. Every rank shows its reason codes ("31 days overdue", "2 of 3 promises broken", "savings deposits stopped 6 weeks ago").
7. Control group from the first import. A random holdout gets the lender's existing process and is measured identically.
8. Sample data is labelled as sample data, and simulated results as simulated, on every screen where they appear.

## 4. Markets

Market is a tenant setting. Seed two demo tenants and default to Myanmar.

| | Myanmar (default) | Cambodia |
|---|---|---|
| Borrower language | Burmese, Unicode only. Detect Zawgyi in inbound text (Google myanmar-tools) and convert (ICU Zawgyi-my) | Khmer |
| Currency | MMK, no decimals | USD and KHR, per loan |
| Payment rail (mock in demo) | MMQR / mobile wallet (KBZPay, Wave, AYA Pay style) | KHQR via a Bakong-connected partner bank |
| Quiet days | Thingyan, Thadingyut etc. (editable list) | Khmer New Year, Pchum Ben etc. (editable list) |
| Time zone | Asia/Yangon (UTC+6:30) | Asia/Phnom_Penh (UTC+7) |

Lender console UI is English. Officer view has an English/local-language toggle. Borrower-facing text is in local script with an English shadow copy visible to lender staff. All seeded local-language scripts are drafts and must show "Draft, needs native review" until a reviewer approves them in Settings.

## 5. The flow when a payment is missed

Build this as a case state machine per overdue loan.

1. **Import.** Lender uploads the Mifos export. Tenpai validates, maps columns, upserts loans and borrowers, opens a case per overdue loan, and assigns control or treatment (stratified random by bucket and branch, 15% control by default, locked for the life of the case).
2. **Score and segment** (section 7). Each case gets a score and one segment:
   - *Nudge*: likely to self-cure. Telegram reminder with pay link.
   - *Plan*: can't pay in full. Offer restructure options.
   - *Visit*: no Telegram link, no response after N attempts, high amount at stake, or broken promises.
   - *Sensitive*: vulnerability flag, dispute, complaint, deceased, or lender-tagged. No automation; a manager owns it.
3. **Contact.** The send gate checks every planned message (section 9). Allowed messages go out; blocked ones are logged with rule ID and rescheduled.
4. **Borrower responds** in the Mini App: pay in full, promise to pay (date and amount), or "I can't pay". "I can't pay" asks three short affordability questions, then shows 2-3 plans.
5. **Plan inside policy**: auto-approved, agreement generated, schedule recorded. **Outside policy**: goes to the branch manager's queue showing exactly which limit it breaches and by how much. One tap to approve, reject, or counter with another option.
6. **Payment.** Borrower pays via deeplink or QR; provider notification arrives; Tenpai matches to the loan by payment reference; unmatched payments go to a manual queue. Matched payments go into the next Mifos posting file.
7. **No response or broken promise.** Case escalates per the bucket strategy (second reminder, then visit). Visit cases land on the assigned officer's list for the next working day.
8. **Officer logs outcome**: paid, promised, not home, refused, hardship, dispute, moved away, deceased. Outcome feeds back into the case.
9. **Close** as cured (back to current), restructured, recovered, or handed to the lender's legal/write-off process (export only, out of Tenpai's scope).

Lifecycle buckets (editable): pre-due (D-3 to D0), 1-7, 8-30, 31-60, 61-90, 90+. Each bucket has a strategy (channel, number of attempts, when to escalate to a visit), edited in Settings as a simple table, not a visual flow builder.

## 6. Screens (lender console)

Left nav. Lender name and logo top left, small Tenpai mark beneath. Role switcher top right. "Sample data" banner on demo tenants.

### 6.1 Portfolio health: "How bad is my book today?"
- Upload for Mifos export (CSV/XLSX), column-mapping step with saved mappings, validation report (missing phones, duplicate loan IDs, negative balances, future dates).
- "Anonymise on import" toggle: hashes names, phones and ID numbers, keeps everything else. Needed for testing on a real lender's historical files.
- Health check (the free tier; must stand alone): overdue book by bucket (count and amount), PAR1/PAR30/PAR90 by branch and officer, top 50 ranked visit list (downloadable), and payments that appear unposted (money sitting in savings or suspense, or last repayment date after the arrears calculation date).
- One-page PDF of the health check on the lender's letterhead.

### 6.2 Today: "Who do we chase today, and how?"
- Ranked case list: borrower, branch, officer, bucket, amount overdue, score, segment, next action, reason codes, Telegram linked (yes/no), control flag.
- Filters by branch, officer, bucket, segment. Bulk actions: send approved reminder, assign to visit, mark sensitive.
- Counters: messages scheduled today, blocked by rules, plans awaiting approval, visits assigned, promises due today.

### 6.3 Borrower account: "What has happened with this borrower?"
- Header: loan details, schedule, arrears, savings balance and deposit trend, group (if a group loan), officer.
- One timeline of every event: import, scores, messages sent/blocked/read, replies, promises, plans, approvals, payments, visits, complaints.
- Phone-frame preview of the borrower's Telegram chat and Mini App exactly as sent, local script with English shadow.
- Actions: send a template, log a call, record a promise, generate plan options, assign a visit, flag sensitive, pause automation.

### 6.4 Approvals: "What needs my sign-off?"
- Queue of out-of-policy plans and other exceptions. Each card: borrower, original vs proposed schedule, capacity figures, the rule breached and by how much, officer note. Approve / reject / counter in one tap. Decision and approver stored as events. SLA timer (default 24h); borrower gets an automatic holding message.

### 6.5 Field: "Where should my officers go?"
- Manager view: visits by officer, workload balance, completion rate, today's outcomes.
- Officer view (mobile web route `/field`, installable PWA): today's visits in priority order grouped by village or ward, tap-to-call, outcome buttons, promise capture (date and amount), notes, photo capture with timestamp and GPS. Large touch targets; must work on a cheap Android phone at 360px wide. Design for an offline queue but don't build it in the demo.

### 6.6 Payments: "Has the money arrived, and is it posted?"
- Payment requests issued, payments received, matched, unmatched (manual match screen), reversed.
- Posting file: pick a date range, produce a file in the Mifos X bulk-import format for loan repayments. Columns configurable; default: office, loan account number, transaction date, amount, payment type, receipt/reference number, note. Confirm against the lender's Mifos version. Mark rows exported; a payment can never be exported twice.
- Restructure export: loans with accepted plans, new schedule and a restructured flag, so the lender's credit team books the reschedule in Mifos and applies its own loan classification and provisioning. Tenpai flags; it does not reclassify.

### 6.7 Results: "Is this working?" (Leadership, Head of collections)
- Treatment vs control by bucket: cure rate, recovery rate, roll rate, promise-kept rate, days to cure.
- PAR30 trend. This is the number the lender's funders watch; make it prominent.
- Cost: officer visits avoided (vs control visit rate), messages sent, cost per unit recovered (inputs: cost per officer visit, cost per message, editable).
- Fee: editable formula, default = monthly platform fee + success fee % x incremental cash, where incremental cash = (treated recovery rate - control recovery rate) x treated overdue balance at case open. Show the working, not just the result.
- Definitions shown on hover:
  - PAR30 = outstanding principal of loans with any instalment more than 30 days overdue / total outstanding principal.
  - Cure rate = cases returned to current / cases opened, per bucket and period.
  - Recovery rate = cash collected on cases / amount overdue at case open.
  - Roll rate = share of balance moving to the next bucket in the period.
- Every chart on demo tenants carries "Simulated".

### 6.8 Compliance: "Can we prove we treat borrowers fairly?"
- Message log: every attempted message, allowed/blocked, rule ID, policy version, template version, timestamps, delivery and read status. Filter and export.
- Consent records: when and how each borrower opted in to Telegram; opt-outs.
- Contact-limit breaches prevented, by rule.
- Vulnerability flags: inbound text, classification, reviewer, outcome.
- Complaints: borrower raises one from the Mini App or by typing "complaint"; goes to a manager with an SLA; status tracked.
- Borrower charter: lender-editable page published in the Mini App (how we contact you, when we won't, your right to ask for a plan, how to complain).

### 6.9 Settings: "What are our rules?"
- Policy: max tenor extension, max restructures per loan, minimum instalment, max share of capacity a plan may take, penalty and interest waiver limits, eligible products, auto-approval ceiling by amount, who approves what.
- Strategy table per bucket.
- Contact rules (section 9).
- Ranking weights (section 7) with a preview of how the top 20 changes.
- Scripts: template library per language, variables, version history, approval status (draft / approved, approver name).
- Brand: lender name, logo, bot display name, Mini App colours.
- Integrations: Mifos column mapping, payment provider (mock / partner), Telegram bot token, data hosting region note.
- Users and roles.
- Every policy edit creates a new version; nothing applies retroactively.

## 7. Ranking v1 (rules, explainable)

Two scores per case, 0-100:
- **Pay likelihood**: bucket base rate, adjusted by on-time ratio over the last 6 instalments, promises-kept ratio, savings deposits stopped (no deposit in N weeks where the borrower previously deposited regularly), Telegram linked and responsive, prior restructure (negative), loan cycle (repeat borrowers positive).
- **Stake**: amount overdue and outstanding principal, normalised within the book.

Priority is a weighted blend; weights live in Settings. Segment rules map scores and flags to Nudge / Plan / Visit / Sensitive. Store score inputs and outputs as an event so the reason codes shown are exactly what drove the decision. Expose a `Ranker` interface so an ML model can replace the rules later without touching screens.

## 8. Restructure plan generator

Affordability uses my existing Python credit engine. Define `capacity(borrower, inputs) -> {monthly_capacity, method, inputs_used}` with a stub for the demo: (household income - household expenses - other debt repayments) x max share from policy. Inputs come from the original loan appraisal if it is in the import, updated by the borrower's three Mini App answers (has income changed, by how much, any new debts), optionally confirmed by the officer.

Generate up to three options, each checked against policy:
- **Catch-up**: regular instalment plus arrears spread over the next N instalments.
- **Reschedule**: arrears capitalised, tenor extended up to the policy max, lower instalment.
- **Short relief**: reduced payments for 1-2 periods, then resume with tenor extended.

For each: new instalment, new end date, total the borrower pays, within policy (yes/no, and which rule if no). Never show the borrower an option above their capacity. An accepted plan produces an agreement (PDF, local language, lender letterhead) and a Telegram confirmation.

## 9. Messaging and contact rules

**Telegram constraint, design around it:** a Telegram bot cannot message anyone who has not started it. Opt-in paths:
- At disbursement or during an officer visit: borrower scans a QR or taps a deep link (`t.me/<lenderbot>?start=<signed token>`) and shares their phone number via the bot's contact button; Tenpai links the Telegram user to the borrower.
- Overdue borrowers not yet linked: one SMS with the deep link (pluggable SMS provider, mock in demo), subject to the same contact rules.
- Borrowers who don't opt in fall to the Visit segment.

Show Telegram link rate as a headline metric on Today and Results. It caps everything digital.

Default contact rules (all editable):
- Quiet hours: nothing outside 08:00-19:00 local time.
- Max 1 outbound per day and 3 per week per borrower, across channels.
- Nothing on listed holidays; Sundays off (toggle).
- All automation stops on: opt-out, open complaint, dispute, vulnerability flag, deceased, manual pause.
- No contact with anyone but the borrower (guarantors, group members, family) by default. If the lender enables group or guarantor contact, it needs manager approval per case and its own template set.
- No threats, no mention of police, land, collateral seizure or public shaming. Enforced at template approval with a banned-phrase check.

**Send gate**: one function every outbound message passes through. Returns allowed or blocked, with rule ID, policy version and next allowed send time. Log every decision.

Templates (seed English plus draft local script): pre-due reminder, due-day reminder, 3 days late, 7 days late, promise confirmation, promise reminder, promise broken, plan offer, plan approved, plan pending approval, payment received, visit notice, complaint received, opt-out confirmation.

**Inbound**: classify replies (keyword lists per language in the demo; LLM classifier behind an interface later) into will pay, already paid, can't pay, dispute, complaint, vulnerability (illness, death, disaster, job loss, migrated), stop, other. Vulnerability, dispute, complaint and stop pause automation and route to the manager.

**Live mode**: if `TELEGRAM_BOT_TOKEN` is set, run a real bot (python-telegram-bot or aiogram) so I can demo on a real phone. Otherwise use an in-app simulated chat that renders identically to the preview.

## 10. Payments

`PaymentProvider` interface: `create_request(loan, amount) -> {reference, qr_payload, qr_png, deeplink, expires_at}`, `parse_notification(payload) -> Payment`, `import_statement(file) -> [Payment]`.
- MockProvider for the demo: unique reference per request, QR image (python `qrcode`), and a "simulate payment" action in the demo panel.
- KHQR and MMQR providers are stubs with TODOs; the real ones go through a licensed partner bank or payment provider.
- Borrowers often can't scan a QR on the phone they're reading it on. The Mini App shows the wallet/bank deeplink button first and "save QR to photos" second.
- Matching: by reference first, then amount + phone + date window, otherwise manual queue. Partial payments and overpayments are allowed and recorded as such.

## 11. Data model

Postgres. Core tables: tenants, policies (versioned JSON), users, branches, officers, borrowers, loans, schedules, savings_snapshots, cases, telegram_links, templates (versioned), messages, promises, plans, approvals, payment_requests, payments, posting_batches, visits, complaints, flags.

`events` (append-only): id, tenant_id, case_id, loan_id, borrower_id, actor (system / user id / borrower), type, payload JSON, policy_version, created_at. Event types at minimum: loan_imported, case_opened, control_assigned, scored, segment_changed, message_planned, message_blocked, message_sent, message_delivered, message_read, reply_received, reply_classified, telegram_linked, opted_out, ptp_created, ptp_kept, ptp_broken, plan_options_generated, plan_accepted, approval_requested, approval_decided, agreement_generated, payment_requested, payment_received, payment_matched, payment_exported, visit_assigned, visit_outcome, complaint_opened, complaint_closed, flag_raised, automation_paused, case_closed.

This log is the long-term asset: it becomes training data for ranking and the base for credit scoring. Make it complete and queryable from day one.

## 12. Demo data and simulation

Deterministic seed generator:
- One fictional MFI per market. Name and logo editable in Settings so a prospect can see their own brand.
- 3 branches, 12 officers, about 1,500 active loans with about 250 overdue across all buckets; individual and group loans; savings accounts with deposit histories; loan sizes realistic for each market; clearly fictional Burmese and Khmer names; phone numbers in an obviously fake range.
- 8 weeks of simulated history with a 15% control group so Results has something to show. Simulated uplift must be modest and plausible, and labelled "Simulated".
- A sample Mifos X export (CSV) in `/sample_data` so the import can be demoed from scratch.

Demo panel (behind a "Demo" menu): advance clock one day, trigger a borrower reply (pick from a list), simulate a payment, reset the demo tenant.

## 13. The 5-minute demo path (must run end to end without errors)

1. Portfolio health: upload the sample Mifos file, map columns, see the health check and PAR by branch.
2. Today: ranked list; open the top Nudge case and read its reason codes.
3. Borrower account: Telegram reminder in Burmese under the lender's name; borrower replies "can't pay this week"; Mini App asks three questions and shows three plans.
4. Borrower picks a plan outside policy; switch role to Branch manager; approve it in one tap; borrower receives confirmation and agreement.
5. Simulate payment; see it matched; generate the Mifos posting file.
6. Advance the clock; a non-responder moves to Visit; switch to Credit officer at phone width; log a visit outcome with photo and promise.
7. Compliance: a message blocked by quiet hours with its rule ID, and a vulnerability reply that paused automation.
8. Results: treatment vs control, PAR30 trend, visits avoided, fee working. All marked Simulated.

## 14. Tech stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Postgres 16 via Docker Compose. Pydantic models for policy and events.
- Jobs: APScheduler driven by a clock abstraction so the demo clock can be advanced.
- Credit engine: import from `engine/` (my existing code); stub if absent.
- Telegram: python-telegram-bot or aiogram; Mini App served from the same frontend.
- Frontend: React, TypeScript, Vite, Tailwind, Recharts, React Router. Officer view responsive to 360px.
- PDFs: WeasyPrint or similar, with Noto Sans Myanmar and Noto Sans Khmer embedded.
- One command to run: `docker compose up`, then `make seed`.
- Tests: send gate, ranking, plan generator, payment matching, posting file (no double export), control assignment (stable and stratified).
- Config via `.env`; no secrets in code. Data hosting region is a config note for now (Singapore or in-country, per lender).

## 15. Design

Palette "Sage & Slate":
- Slate `#2F3E46`: text, nav background, primary dark
- Deep slate `#354F52`: secondary dark
- Green slate `#52796F`: primary actions, links
- Sage `#84A98C`: positive deltas, success
- Pale sage `#CAD2C5`: borders, subtle fills
- Background `#E6EAE3`, cards `#FFFFFF`
- Muted amber and red for warning and danger status only, toned to sit with the palette.

Wordmark "tenpai", lowercase, rounded geometric sans (Outfit or similar). UI text in Inter. Noto Sans Myanmar and Noto Sans Khmer for local script. Logo mark: three stacked rounded cards with a small sage square in the front card; I'll supply the SVG, use a placeholder until then.

Feel: calm, dense, operational. Tables for lists. Right-aligned numbers with tabular figures. No stock illustrations, no gradients. The borrower Mini App uses the lender's colours, not Tenpai's.

## 16. Out of scope for the demo

ML ranking, Mifos API integration, live KHQR/MMQR, real SMS (mock only), voice reminders, officer offline mode, production auth and SSO, cross-lender insights, credit decisioning UI.

## 17. Done means

- The 5-minute path runs end to end on a fresh `docker compose up` and seed.
- A different Mifos-style CSV with renamed columns imports via the mapping step.
- No message can be sent that breaks a contact rule; tests prove it.
- No payment can be exported twice; tests prove it.
- Every number on Results traces back to events.
- Every borrower-facing screen shows only the lender's brand.
- Sample and simulated labels appear wherever seed data is used.

## 18. Build order

Work in this order and show me each stage running before moving on:
1. Schema, event log, seed generator, sample Mifos file.
2. Import, column mapping, anonymise toggle, health check and PDF.
3. Ranking, Today, borrower account timeline.
4. Templates, send gate, simulated Telegram and Mini App, inbound classification.
5. Plan generator, approvals, agreement PDF.
6. Mock payments, matching, posting file, restructure export.
7. Field: manager and officer views.
8. Results with control group, Compliance, Settings.
9. Demo panel and polish; run the 5-minute path three times clean.

Ask me before adding dependencies outside this list or changing the data model in a way that breaks the event log.
