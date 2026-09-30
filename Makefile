API_PORT := 8393
WEB_PORT := 3001

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'

dev: ## Full dev stack: Postgres + migrations + seed + API + web (Ctrl-C stops all)
	./scripts/dev.sh

db: ## Start Postgres and wait for it to be healthy
	docker compose up -d --wait

down: ## Stop Postgres
	docker compose down

api: ## API only, with reload (assumes Postgres is up: make db)
	cd services/api && uv run uvicorn app.main:app --reload --port $(API_PORT)

web: ## Web only (assumes the API is running)
	cd apps/web && npm run dev

migrate: ## Apply Alembic migrations
	cd services/api && uv run alembic upgrade head

seed: ## Seed the demo world (idempotent)
	cd services/api && uv run python -m app.seed

test: ## API test suite
	cd services/api && uv run pytest

typecheck: ## Web typecheck
	cd apps/web && npm run typecheck

.PHONY: help dev db down api web migrate seed test typecheck
