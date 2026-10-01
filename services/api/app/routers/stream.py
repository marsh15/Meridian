"""SSE live-price streams (ADR 0004, fan-out in ADR 0009).

Ticks originate as pg_notify inside the trade/resolve transaction and are
delivered by Postgres on commit, so a rolled-back trade never reaches the
stream. Delivery to clients goes through the process-wide Redis fan-out
hub when Redis is available (one Postgres LISTEN per process); otherwise
each client falls back to its own Postgres LISTEN connection. A comment
heartbeat every 15 s keeps proxies from closing idle connections.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

import asyncpg
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.config import settings
from app.db import SessionFactory
from app.fanout import tick_hub

router = APIRouter(prefix="/api")

HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(data: dict) -> str:
    return f"event: tick\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def _market_snapshot(slug: str) -> dict | None:
    async with SessionFactory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT slug, event_seq, q_yes, q_no, status, outcome "
                    "FROM markets WHERE slug = :slug"
                ),
                {"slug": slug},
            )
        ).first()
    if row is None:
        return None
    from app.amm import price_yes

    price = 100 if row.status == "resolved" and row.outcome == "yes" else (
        0 if row.status == "resolved" else round(price_yes(row.q_yes, row.q_no) * 100)
    )
    return {"type": "tick", "slug": row.slug, "seq": row.event_seq, "price": price,
            "status": row.status, "outcome": row.outcome}


async def _tick_stream(slug: str | None) -> AsyncIterator[str]:
    pubsub = await tick_hub.subscribe()
    if pubsub is not None:
        tick_hub.active_streams += 1
        try:
            # subscribed before the snapshot, so nothing ticks in between
            if slug is not None:
                snapshot = await _market_snapshot(slug)
                if snapshot is not None:
                    yield _sse(snapshot)
            # get_message handles its own timeout per call; wrapping an
            # async generator's __anext__ in wait_for instead corrupts the
            # generator on cancel and busy-loops the event loop
            while True:
                try:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=15.0
                    )
                except Exception:
                    # broken pubsub (redis restart mid-stream): end the
                    # stream; the browser's EventSource reconnects and
                    # falls back or resubscribes
                    return
                if msg is None:
                    yield ": ping\n\n"
                    continue
                data = json.loads(msg["data"])
                if slug is None or data.get("slug") == slug:
                    yield _sse(data)
        finally:
            tick_hub.active_streams -= 1
            with contextlib.suppress(Exception):
                await pubsub.aclose()
        return

    # fallback: no Redis — one dedicated Postgres LISTEN per client
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_notify(_conn, _pid, _channel, payload: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    await conn.add_listener("market_ticks", on_notify)
    try:
        if slug is not None:
            snapshot = await _market_snapshot(slug)
            if snapshot is not None:
                yield _sse(snapshot)
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            data = json.loads(payload)
            if slug is None or data.get("slug") == slug:
                yield _sse(data)
    finally:
        await conn.close()


@router.get("/stream")
async def stream_all() -> StreamingResponse:
    """Every market's ticks — used by the home page ticker tape."""
    return StreamingResponse(_tick_stream(None), media_type="text/event-stream", headers=HEADERS)


@router.get("/markets/{slug}/stream")
async def stream_market(slug: str) -> StreamingResponse:
    # The existence check runs on a short-lived session on purpose: a
    # yield-dependency would hold its pooled connection (in an open read
    # transaction) until the stream ends — minutes per viewer — and ~15
    # concurrent viewers would exhaust the pool for the whole API.
    async with SessionFactory() as session:
        exists = await session.execute(text("SELECT 1 FROM markets WHERE slug = :s"), {"s": slug})
        if exists.first() is None:
            raise HTTPException(404, "Market not found.")
    return StreamingResponse(_tick_stream(slug), media_type="text/event-stream", headers=HEADERS)
