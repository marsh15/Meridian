"""SSE live-price streams (ADR 0004).

Each client holds one dedicated asyncpg connection LISTENing on
`market_ticks`. Events fire via pg_notify inside the trade/resolve
transaction and are delivered by Postgres on commit, so a rolled-back trade
never reaches the stream. A comment heartbeat every 15 s keeps proxies from
closing idle connections.
"""

import asyncio
import json
from collections.abc import AsyncIterator

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionFactory, get_session

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
            except asyncio.TimeoutError:
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
async def stream_market(
    slug: str, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    exists = await session.execute(text("SELECT 1 FROM markets WHERE slug = :s"), {"s": slug})
    if exists.first() is None:
        from fastapi import HTTPException

        raise HTTPException(404, "Market not found.")
    return StreamingResponse(_tick_stream(slug), media_type="text/event-stream", headers=HEADERS)
