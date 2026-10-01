"""SSE tick fan-out (phase 5, ADR 0009).

Without Redis every SSE client holds a dedicated Postgres connection
LISTENing on `market_ticks` — connections scale with browsers, not load.
With Redis, the process runs ONE bridge: a single Postgres LISTEN
connection that republishes every committed tick to the Redis channel
`meridian:ticks`; SSE clients subscribe there instead. Postgres keeps its
transactional semantics (pg_notify still fires only on commit — Redis is
pure fan-out, never the source of truth), and with >1 API instance every
instance's clients see every tick.
"""

import asyncio
import logging

import asyncpg

from app import redis as redis_mod
from app.config import settings

log = logging.getLogger("meridian.fanout")

CHANNEL = "meridian:ticks"


class TickHub:
    """Process-wide pg LISTEN → Redis PUBLISH bridge."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._starter: asyncio.Task | None = None
        self._pg: asyncpg.Connection | None = None
        self.active_streams = 0

    @property
    def enabled(self) -> bool:
        return self._task is not None

    async def start(self) -> None:
        if self._task is not None or self._starter is not None:
            return
        r = await redis_mod.get_redis()
        if r is not None:
            self._task = asyncio.create_task(self._bridge(r))
            return
        # Redis briefly down at boot: keep retrying in the background; SSE
        # clients fall back to per-client pg LISTEN until it comes up
        self._starter = asyncio.create_task(self._start_when_ready())

    async def _start_when_ready(self) -> None:
        while settings.redis_url:
            await asyncio.sleep(5.0)
            r = await redis_mod.get_redis()
            if r is not None:
                self._starter = None
                self._task = asyncio.create_task(self._bridge(r))
                return
        self._starter = None

    async def stop(self) -> None:
        for attr in ("_starter", "_task"):
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, attr, None)
        if self._pg is not None:
            try:
                await self._pg.close()
            except Exception:
                pass
            self._pg = None

    async def _bridge(self, r) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                conn = await asyncpg.connect(settings.asyncpg_dsn)
                self._pg = conn

                def on_notify(_c, _pid, _ch, payload: str) -> None:
                    # called on the event-loop thread; schedule the publish
                    loop.call_soon_threadsafe(self._publish_now, r, payload)

                await conn.add_listener("market_ticks", on_notify)
                await asyncio.Future()  # parked until cancelled/crashed
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("tick bridge dropped — reconnecting in 1s", exc_info=True)
                await asyncio.sleep(1)
            finally:
                if self._pg is not None:
                    try:
                        await self._pg.close()
                    except Exception:
                        pass
                    self._pg = None

    def _publish_now(self, r, payload: str) -> None:
        async def _publish() -> None:
            try:
                await r.publish(CHANNEL, payload)
            except Exception:
                log.warning("tick publish failed", exc_info=True)

        asyncio.ensure_future(_publish())

    async def subscribe(self):
        """A Redis pubsub subscribed to the tick channel, or None when the
        hub isn't running (caller falls back to direct pg LISTEN)."""
        r = await redis_mod.get_redis()
        if r is None or not self.enabled:
            return None
        pubsub = r.pubsub()
        await pubsub.subscribe(CHANNEL)
        return pubsub


tick_hub = TickHub()
