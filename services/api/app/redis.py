"""Redis access for the API (phase 5): rate limiting, the hot-market cache,
and SSE tick fan-out.

One process-wide client, created lazily. Every caller treats Redis as an
optimization, never a dependency: on connection failure the cache misses,
the rate limiter allows, and the SSE stream falls back to per-client
Postgres LISTEN. A failed connection is retried after a short cooldown —
a blip at startup must not disable Redis for the process lifetime. Set
REDIS_URL="" to disable Redis entirely.
"""

import contextlib
import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from app import metrics
from app.config import settings

log = logging.getLogger("meridian.redis")

_client: Any = None
_retry_at = 0.0
_last_warn = 0.0

RETRY_COOLDOWN_S = 5.0
WARN_EVERY_S = 60.0


async def get_redis() -> Any | None:
    """The shared redis.asyncio client, or None when disabled/unavailable."""
    global _client, _retry_at, _last_warn
    if not settings.redis_url:
        return None
    if _client is not None:
        return _client
    now = monotonic()
    if now < _retry_at:
        return None
    import redis.asyncio as aioredis

    _retry_at = now + RETRY_COOLDOWN_S  # applies when this attempt fails
    try:
        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1.0
        )
        await client.ping()
    except Exception as err:
        if now - _last_warn > WARN_EVERY_S:
            log.warning("redis unreachable at %s — failing open (%s: %s)",
                        settings.redis_url, type(err).__name__, err)
            _last_warn = now
        return None
    _client = client
    return client


async def close_redis() -> None:
    global _client, _retry_at
    if _client is not None:
        await _client.aclose()
    _client, _retry_at = None, 0.0


async def cache_get_json(key: str) -> Any | None:
    """Cached JSON value or None (miss, disabled, or Redis down)."""
    r = await get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
    except Exception:
        return None
    if raw is None:
        metrics.cache_misses.add(1)
        return None
    import json

    try:
        value = json.loads(raw)
    except ValueError:
        return None
    metrics.cache_hits.add(1)
    return value


async def cache_set_json(key: str, value: Any, ttl: float) -> bool:
    r = await get_redis()
    if r is None:
        return False
    import json

    try:
        # timedelta accepts fractional TTLs; redis-py rejects float ex=
        await r.set(key, json.dumps(value, separators=(",", ":")),
                    ex=timedelta(seconds=ttl))
        return True
    except Exception:
        return False


# the hot GET /api/markets payload; content-changing writes purge it so a
# client can never observe a list that predates its own write
MARKETS_CACHE_KEY = "cache:markets:v1"


async def invalidate_markets_cache() -> None:
    r = await get_redis()
    if r is None:
        return
    with contextlib.suppress(Exception):
        await r.delete(MARKETS_CACHE_KEY)


def reset_for_tests() -> None:
    """Swap in a fresh state (tests inject fakeredis via this module)."""
    global _client, _retry_at, _last_warn
    _client, _retry_at, _last_warn = None, 0.0, 0.0
