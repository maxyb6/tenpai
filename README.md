# Tenpai Collections (demo build)

Lender-run collections platform for MFIs in Myanmar and Cambodia. See
`docs/build-prompt.md` for the full spec. All seeded data is fictional sample
data; all simulated results are labelled as simulated.

## Run

```bash
docker compose up --build
```

Open http://localhost:8000. On first start the sample data seeds itself (about 4 minutes; the page
says so and refreshes). One image serves the console and the API.

Without Docker (Postgres 16 running locally, Python 3.12):

```bash
pip install -r backend/requirements.txt
make migrate && make seed && make dev
```

Console on http://localhost:5173, API on http://localhost:8000 (`/docs` for the OpenAPI UI).
Without Docker, run the frontend with `cd frontend && npm install && npm run dev`.

Seed for a specific demo date: `make seed ARGS="--as-of 2026-11-05"`. The seed writes the
sample Mifos exports to `sample_data/` and imports them through the real pipeline.

## Layout

- `backend/app/models.py` – tables. `events` is append-only (DB trigger).
- `backend/app/events.py` – `emit()`, the only writer to the event log.
- `backend/app/policy.py` – versioned lender policy (Pydantic).
- `backend/app/ingest/` – column mapping, validation, upsert, case opening.
- `backend/app/domain/control.py` – stratified control-group assignment.
- `backend/app/seed/` – deterministic sample book and Mifos CSV writer.
- `sample_data/` – sample Mifos X exports (loans, schedule, savings) per market.

## Tests

```bash
make test
```

## Demo tenants

`make seed` creates three tenants, all fictional and labelled as sample data:

- **Myanmar demo** (`mm-demo`): 1,500 loans, 8 weeks of simulated history replayed through the
  real engine (send gate, replies, promises, plans, approvals, visits, payments). Results come from
  those events and are labelled Simulated.
- **Myanmar: first import** (`mm-new`): same brand and policy, no book. Use it to show the import,
  column mapping and the free health check from scratch.
- **Cambodia demo** (`kh-demo`): Khmer, USD and KHR loans.

Seeding takes about 2 minutes per tenant (the history replay). "Reset demo tenant" in the Demo
menu does the same for one tenant.

## The 5-minute demo path

1. Switch to *Myanmar: first import*. Portfolio health → Import → the three files in `sample_data/`
   (`mifos_*_mm.csv`) → Validate and import. Health check, PAR by branch, unposted payments, PDF.
2. Switch to *Myanmar demo*. Demo menu → **Open the demo borrower** (it finds a Nudge case where
   the next steps produce an out-of-policy plan and tells you the income figure to type).
3. Send a template (Burmese, under the lender's name). In the phone panel pick the borrower reply
   "I can't pay this week". Mini App tab → "မပေးနိုင်ပါ" → less → type the income → plans.
4. Choose the plan marked as needing branch approval. Switch role to Branch manager (that branch) →
   Approvals → Approve. The borrower gets the confirmation and agreement.
5. Back on the borrower: Simulate payment due now → matched. Payments → Generate posting file.
6. Demo menu → Advance clock one day (new visits appear). Open `/field` at phone width as the credit
   officer → open a visit → Promised, amount, date, photo → Save.
7. Demo menu → Set time to 20:30; send a template → blocked by CR-08 (rule ID in Compliance).
   A vulnerability reply ("My mother is in hospital") pauses automation and appears under flags.
8. Results: treatment vs control with a 95% interval, PAR30 trend, visits avoided, fee working.

`frontend/e2e/demo-path.cjs` runs the whole path in a headless browser:

```bash
cd frontend && node e2e/demo-path.cjs /tmp/demo-shots
```

## Live Telegram

Set `TELEGRAM_BOT_TOKEN` (BotFather) and `PUBLIC_BASE_URL` (an https URL serving the frontend, needed
for Mini App buttons). The API starts a polling bot. On a borrower page, "Telegram opt-in QR" gives a
signed `t.me/<bot>?start=` link: scan it with a real phone, share the phone number when the bot asks,
and that phone receives the borrower's messages. On demo tenants the phone need not match the sample
number (recorded as unverified); on a real tenant it must.

## What is stubbed

- Credit engine: `app/credit/engine.py` uses `engine.capacity()` if an `engine` package is importable,
  otherwise (income − expenses − debt) × policy share.
- Payments: mock provider; `MMQRProvider` and `KHQRProvider` are stubs that need a licensed partner.
- SMS: mock (only the one Telegram invite is ever sent by SMS).
- Mifos column names and the posting-file layout follow Mifos conventions but must be confirmed
  against the lender's Mifos version.
- Burmese and Khmer scripts are drafts flagged "needs native review". Demo tenants may send them;
  a real tenant's send gate blocks them until a reviewer clears them in Settings.

## Deploy (Render)

`render.yaml` is a blueprint: one Docker web service plus Postgres 16, both in Singapore.

1. In Render: **New → Blueprint**, connect GitHub, pick `maxyb6/tenpai`.
2. When asked, set `DEMO_PASSWORD` (the console asks for it; any username). Optionally set
   `DEMO_AS_OF` to the demo date and `TELEGRAM_BOT_TOKEN`.
3. Apply. First deploy builds the image (about 5 minutes), then seeds (about 4 minutes).

The blueprint uses paid plans (Starter web service, basic-256mb Postgres, roughly USD 13 a month):
free web services sleep and take a minute to wake, and free databases expire after 30 days, which
is the wrong risk for a live demo. Uploaded files (visit photos, agreement PDFs) live on the
container's disk and are lost on redeploy; fine for a demo, not for a pilot.

To refresh the dates before a demo: Demo menu → Reset demo tenant (about 2 minutes per tenant),
or redeploy with a new `DEMO_AS_OF` after clearing the database.
