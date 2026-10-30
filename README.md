# Tenpai Collections (demo build)

Lender-run collections platform for MFIs in Myanmar and Cambodia. See
`docs/build-prompt.md` for the full spec. All seeded data is fictional sample
data; all simulated results are labelled as simulated.

## Run

```bash
cp .env.example .env
docker compose up --build
make seed                       # or: make seed ARGS="--as-of 2026-11-05"
```

Without Docker (Postgres 16 running locally, Python 3.12):

```bash
pip install -r backend/requirements.txt
make migrate && make seed && make dev
```

API on http://localhost:8000 (`/docs` for the OpenAPI UI).

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
