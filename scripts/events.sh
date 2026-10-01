#!/usr/bin/env bash
# Event backbone: relay (outbox→Kafka) + the three consumers, together.
# Assumes infra is up (any `make db` / `make dev`); Ctrl-C or either process
# dying stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

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

echo "==> relay   outbox → exchange.trade-events / exchange.market-events"
(cd services/api && OTLP_ENDPOINT=http://localhost:4319 exec uv run python -m relay) &
pids+=($!)

echo "==> consumers  candles · volume · analytics  (group per read model)"
(cd services/api && OTLP_ENDPOINT=http://localhost:4319 exec uv run python -m consumers) &
pids+=($!)

while kill -0 "${pids[@]}" >/dev/null 2>&1; do
  sleep 1
done
