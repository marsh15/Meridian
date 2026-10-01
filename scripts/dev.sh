#!/usr/bin/env bash
# One-command dev stack: Postgres + migrations + seed + FastAPI + Next.js.
# Ctrl-C (or either process dying) stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> starting Postgres + Kafka + Redis + telemetry"
docker compose up -d --wait

echo "==> provisioning Kafka topics"
./scripts/provision-topics.sh

# bootstrap workspace deps on a fresh clone; `uv run` syncs the API itself
if [ ! -d node_modules ]; then
  echo "==> installing workspace dependencies (pnpm)"
  pnpm install
fi

echo "==> applying migrations"
(cd services/api && uv run alembic upgrade head)

echo "==> seeding demo world"
(cd services/api && uv run python -m app.seed)

pids=()
cleanup() {
  trap - EXIT INT TERM
  if [ ${#pids[@]} -gt 0 ]; then
    kill "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

echo "==> api  http://127.0.0.1:8393  (docs at /docs)"
(cd services/api && OTLP_ENDPOINT=http://localhost:4319 exec uv run uvicorn app.main:app --reload --port 8393) &
pids+=($!)

echo "==> web  http://localhost:3001"
(cd apps/web && exec pnpm dev) &
pids+=($!)

echo "==> worker  temporal lifecycle (auto-close timers, durable settlement)"
(cd services/api && exec uv run python -m worker) &
pids+=($!)

echo "==> dashboards  grafana http://localhost:3002 · prometheus http://localhost:9091"

# when either process dies, take the other with it
while kill -0 "${pids[@]}" >/dev/null 2>&1; do
  sleep 1
done
