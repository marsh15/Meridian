"""Fixed-window rate limits backed by Redis (phase 5).

One INCR + EXPIRE per request per scope. Windows are aligned to wall-clock
epochs (no per-key timers), so a burst at a window edge can admit up to
2×limit across two adjacent windows — acceptable for abuse prevention, not
a quota system. Every failure mode (Redis disabled, Redis down, command
error) fails open: a limiter outage must never take the API down.
"""

import time

from fastapi import Depends, HTTPException, Request

from app import metrics
from app import redis as redis_mod
from app.config import settings
from app.deps import require_user


def _client_ip(request: Request) -> str:
    # Proxy headers are only honest when every request passes through a
    # proxy we control that sets/overwrites them (Fly does). Gated by
    # TRUST_PROXY_HEADERS — otherwise the socket peer is the only address a
    # client can't spoof per request.
    if settings.trust_proxy_headers:
        if fly := request.headers.get("fly-client-ip"):
            return fly.strip()
        if xff := request.headers.get("x-forwarded-for"):
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _enforce(scope: str, key: str, limit: int, window: int) -> None:
    r = await redis_mod.get_redis()
    if r is None:
        return
    now = time.time()
    slug = int(now // window)
    redis_key = f"rl:{scope}:{key}:{slug}"
    try:
        # SET NX carries the TTL atomically with the counter's creation —
        # a crash between INCR and EXPIRE can never leave a timeless key
        created = await r.set(redis_key, 1, ex=window + 1, nx=True)
        count = 1 if created else await r.incr(redis_key)
    except Exception:
        return
    if count > limit:
        metrics.ratelimit_rejections.add(1, {"scope": scope})
        retry = max(1, int(window - (now % window)) + 1)
        raise HTTPException(
            429,
            f"Too many requests. Retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )


async def auth_limit(request: Request) -> None:
    """Signup/login: per client IP."""
    await _enforce("auth", _client_ip(request), settings.auth_requests_per_minute, 60)


async def order_limit(user: dict = Depends(require_user)) -> dict:
    """Order placement: per user (idempotent replays still count — a client
    retrying a storm is exactly what this catches)."""
    await _enforce("orders", f"u{user['id']}", settings.orders_per_minute, 60)
    return user


async def create_market_limit(user: dict = Depends(require_user)) -> dict:
    await _enforce("creates", f"u{user['id']}", settings.market_creates_per_hour, 3600)
    return user


async def reset_limit(user: dict = Depends(require_user)) -> dict:
    """Account reset: sells back positions and mints the difference."""
    await _enforce("reset", f"u{user['id']}", settings.account_resets_per_hour, 3600)
    return user


async def intel_limit(user: dict = Depends(require_user)) -> dict:
    """Briefs and explanations — each one costs an LLM call."""
    await _enforce("intel", f"u{user['id']}", settings.intel_requests_per_hour, 3600)
    return user
