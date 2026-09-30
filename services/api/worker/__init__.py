"""Temporal lifecycle worker (ADR 0008).

Runs MarketLifecycleWorkflow for every live market: a durable timer
auto-closes the market at closes_at (replacing the old in-process
sweeper), then the workflow waits — indefinitely, crash-safely — for the
creator's resolution signal and settles through the same transactional
functions the API uses. Run it:  uv run python -m worker
"""
