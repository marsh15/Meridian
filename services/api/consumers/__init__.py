"""Kafka consumers — the relay's audience (ROADMAP phase 2).

Three independent consumer groups build read models in Postgres:
candles (OHLCV per market-minute), volume projector (live market_stats),
analytics (flat trade_facts). Each group dedupes against processed_events
in the same transaction that applies the event, turning Kafka's
at-least-once delivery into effectively-once application. Handler
failures retry once, then dead-letter to exchange.dlq and commit.
Contract: docs/failure-model.md.

Run all three:  uv run python -m consumers   (from services/api)
"""
