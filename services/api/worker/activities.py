"""Thin activity wrappers over app.market_lifecycle — all real work happens
in the shared transactional functions, which are idempotent under the
retries Temporal may perform."""

from temporalio import activity

from app import market_lifecycle as lifecycle


@activity.defn
async def close_market(market_id: int) -> bool:
    activity.logger.info("close_market activity: market %s", market_id)
    return await lifecycle.close_market(market_id)


@activity.defn
async def settle_market(market_id: int, outcome: str) -> dict:
    activity.logger.info("settle_market activity: market %s → %s", market_id, outcome)
    return await lifecycle.settle_market(market_id, outcome)
