#!/usr/bin/env bash
# One-command dev stack: Postgres + migrations + seed + FastAPI + Next.js.
# Ctrl-C (or either process dying) stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> starting Postgres + Kafka"
docker compose up -d --wait

echo "==> provisioning Kafka topics"
./scripts/provision-topics.sh

# bootstrap web deps on a fresh clone; `uv run` syncs the API on its own
if [ ! -d apps/web/node_modules ]; then
  echo "==> installing web dependencies"
  (cd apps/web && npm install)
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
(cd services/api && exec uv run uvicorn app.main:app --reload --port 8393) &
pids+=($!)

echo "==> web  http://localhost:3001"
(cd apps/web && exec npm run dev) &
pids+=($!)

# when either process dies, take the other with it
while kill -0 "${pids[@]}" >/dev/null 2>&1; do
  sleep 1
done
