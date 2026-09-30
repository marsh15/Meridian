"""Outbox→Kafka relay (ROADMAP phase 2, ADR 0006).

Publishes unread outbox_events rows to the exchange.* topics, keyed by
market_id so every event for one market lands on one partition and stays
totally ordered. Delivery is AT-LEAST-ONCE: the claim transaction stays
open across the Kafka publish and commits the published_at marks only
after the broker acks — a crash in between replays those rows on
restart, and consumers dedupe. Full contract: docs/failure-model.md.

Run it:  uv run python -m relay     (from services/api; needs Kafka up)
"""
