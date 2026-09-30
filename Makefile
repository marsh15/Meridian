API_PORT := 8393
WEB_PORT := 3001

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'

dev: ## Full dev stack: Postgres + migrations + seed + API + web (Ctrl-C stops all)
	./scripts/dev.sh

db: ## Start Postgres + Kafka and wait for both to be healthy
	docker compose up -d --wait

down: ## Stop Postgres + Kafka
	docker compose down

kafka-topics: ## Provision the exchange.* topics (idempotent)
	./scripts/provision-topics.sh

kafka-dump: ## Peek at recent messages on the exchange.* topics
	docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
		--bootstrap-server localhost:9092 --topic exchange.trade-events \
		--from-beginning --max-messages 5 --timeout-ms 3000 || true

relay: ## Outbox→Kafka relay (needs make db up)
	cd services/api && uv run python -m relay

consumers: ## The three Kafka consumers (candles, volume, analytics)
	cd services/api && uv run python -m consumers

events: ## Relay + consumers together (Ctrl-C stops both)
	./scripts/events.sh

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

test-unit: ## Web unit tests (Vitest: AMM mirror vs Python fixtures)
	cd apps/web && npm run test:unit

test-e2e: ## Web e2e (Playwright happy path; boots the stack itself)
	cd apps/web && npm run test:e2e

.PHONY: help dev db down api web migrate seed test typecheck test-unit test-e2e \
	kafka-topics kafka-dump relay consumers events
