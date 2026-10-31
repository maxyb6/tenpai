.PHONY: up seed test migrate dev

# With Docker
up:
	docker compose up --build

seed:
	@if docker compose ps -q app >/dev/null 2>&1 && [ -n "$$(docker compose ps -q app)" ]; then \
		docker compose exec app python3.12 -m app.cli seed $(ARGS); \
	else \
		cd backend && python -m app.cli seed $(ARGS); \
	fi

# Without Docker (local Postgres 16)
migrate:
	cd backend && alembic upgrade head

dev:
	cd backend && uvicorn app.main:app --reload --port 8000

test:
	cd backend && python -m pytest -q
