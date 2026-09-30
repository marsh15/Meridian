#!/usr/bin/env bash
# Provision the exchange.* Kafka topics (idempotent — safe on every boot).
# Partitioned with keys = market_id, so all events for one market land on
# one partition and stay totally ordered; 6 partitions spread the load.
set -euo pipefail
cd "$(dirname "$0")/.."

KAFKA="docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh"
BOOTSTRAP="--bootstrap-server localhost:9092"

create() {
  local topic="$1" partitions="$2" retention="$3"
  echo "==> topic ${topic}"
  $KAFKA $BOOTSTRAP --create --if-not-exists \
    --topic "$topic" --partitions "$partitions" --config "retention.ms=${retention}"
}

# infinite retention: the outbox is replayable, but re-publishing history is
# an UPDATE away — see docs/failure-model.md before shrinking this in prod
create exchange.trade-events  6 -1
create exchange.market-events 6 -1
# dead letters from consumer handler failures; bounded so cruft self-cleans
create exchange.dlq           1 604800000

echo "==> topics now on the broker:"
$KAFKA $BOOTSTRAP --list
