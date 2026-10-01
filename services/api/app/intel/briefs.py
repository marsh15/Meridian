"""Market brief orchestration: retrieval → rerank → LLM → validated brief.

The LLM sees numbered sources and cites them by index; the server attaches
the real fetched titles/URLs, so a citation can never link somewhere the
retriever never went. Artifacts persist in intel_artifacts with the model
name for provenance.
"""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.intel.provider import LLMError, chat_json
from app.intel.rerank import rerank
from app.intel.retrieval import RawSource, gather_sources
from app.intel.schemas import Brief, CasePoint, Catalyst, Source

log = logging.getLogger("meridian.intel.briefs")

BRIEF_SYSTEM = (
    "You are a prediction-market analyst. You reason about the probability "
    "the market's question resolves YES, given market data and numbered "
    "sources. Be calibrated, not narrative-hungry: weak evidence means "
    "saying so. Respond with ONLY a JSON object, no markdown, matching "
    'exactly: {"headline": str, "summary": str (2-4 sentences, mention the '
    'current price), "bullish": [{"claim": str, "citation": int|null}] '
    '(2-4 items), "bearish": same shape (2-4 items), "catalysts": '
    '[{"what": str, "when_hint": str, "citation": int|null}] (0-4 items: '
    "dated events that could move this market before close), "
    '"source_assessments": [{"idx": int, "quality": "high"|"medium"|"low"}] '
    "(one per source you used), \"source_note\": str (one sentence on how "
    "trustworthy the sources are for this question)}. `citation` and `idx` "
    "are 1-based source numbers; use null when a claim is your reasoning, "
    "not a source's."
)


async def _market_stats(session: AsyncSession, market_id: int) -> dict[str, Any]:
    """Grounding numbers straight from the exchange's own data."""
    hist = (
        await session.execute(
            text("SELECT price_cents FROM price_history WHERE market_id = :m "
                 "ORDER BY created_at DESC, id DESC LIMIT 24"),
            {"m": market_id},
        )
    ).scalars().all()
    holders = (
        await session.execute(
            text("SELECT COALESCE(SUM(shares), 0) FROM positions "
                 "WHERE market_id = :m AND shares > 0"),
            {"m": market_id},
        )
    ).scalar_one()
    top3 = (
        await session.execute(
            text("SELECT shares FROM positions WHERE market_id = :m AND shares > 0 "
                 "ORDER BY shares DESC LIMIT 3"),
            {"m": market_id},
        )
    ).scalars().all()
    trend = list(reversed([int(p) for p in hist]))
    return {
        "recent_prices": trend,
        "direction": ("rising" if trend and trend[-1] > trend[0] else
                      "falling" if trend and trend[-1] < trend[0] else "flat"),
        "open_interest_shares": round(float(holders), 1),
        "top3_concentration": (round(sum(float(s) for s in top3) / float(holders), 2)
                               if float(holders) > 0 else 0.0),
    }


def _sources_block(ranked: list[tuple[float, RawSource]]) -> str:
    if not ranked:
        return "No external sources were retrieved. Reason from the market data; "\
               "set every citation to null and note the gap in source_note."
    lines = []
    for i, (score, src) in enumerate(ranked, start=1):
        date = src.published_at.strftime("%Y-%m-%d") if src.published_at else "undated"
        snippet = f" — {src.snippet[:220]}" if src.snippet else ""
        lines.append(f"[{i}] {src.title} ({src.publisher}, {date}){snippet}")
    return "\n".join(lines)


async def generate_brief(market: Any) -> dict[str, Any]:
    """Full pipeline for one market; returns the artifact payload. Owns its
    session so callers never juggle a read transaction around the insert."""
    from app.db import SessionFactory

    m = market
    query = f"{m['question']} {m['category']}"
    raw = await gather_sources(query)
    ranked = rerank(m["question"], m["description"] or "", m["category"], raw)
    async with SessionFactory() as session:
        async with session.begin():
            stats = await _market_stats(session, m["id"])

    from app.views import market_view

    view = market_view(m)
    user_prompt = (
        f"Market: {m['question']}\n"
        f"Category: {m['category']}\n"
        f"Description: {m['description'] or '(none)'}\n"
        f"Resolution rules: {m['resolution_rules'] or '(none)'}\n"
        f"Closes: {m['closes_at'].isoformat() if hasattr(m['closes_at'], 'isoformat') else m['closes_at']}\n"
        f"Current YES price: {view['price']} cents (24h change {view['change24h']:+d})\n"
        f"Volume traded: ${view['volumeCents'] / 100:,.0f} across {view['traders']} traders\n"
        f"Price trend (oldest→newest, cents): {stats['recent_prices'][-12:]} ({stats['direction']})\n"
        f"Open interest: {stats['open_interest_shares']} shares; "
        f"top-3 holders own {int(stats['top3_concentration'] * 100)}%\n\n"
        f"Sources:\n{_sources_block(ranked)}\n\n"
        "Write the brief."
    )

    data = await chat_json([
        {"role": "system", "content": BRIEF_SYSTEM},
        {"role": "user", "content": user_prompt},
    ])

    assessments = {int(a["idx"]): a.get("quality", "medium")
                   for a in data.get("source_assessments", [])
                   if isinstance(a, dict) and "idx" in a}
    sources = [
        Source(
            idx=i,
            title=src.title,
            url=src.url,
            publisher=src.publisher,
            published_at=src.published_at.isoformat() if src.published_at else None,
            quality=assessments.get(i, "medium"),
        )
        for i, (_score, src) in enumerate(ranked, start=1)
    ]

    def _valid_cite(value: Any) -> int | None:
        """Accept only in-range 1-based indexes; anything else is 'no source'."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        idx = int(value)
        return idx if 1 <= idx <= len(sources) else None

    def _point(item: Any) -> CasePoint | None:
        if not isinstance(item, dict) or not item.get("claim"):
            return None
        return CasePoint(claim=str(item["claim"])[:400], citation=_valid_cite(item.get("citation")))

    brief = Brief(
        headline=str(data.get("headline", view["question"]))[:200],
        summary=str(data.get("summary", ""))[:1200],
        bullish=[p for p in (_point(x) for x in data.get("bullish", [])) if p][:4],
        bearish=[p for p in (_point(x) for x in data.get("bearish", [])) if p][:4],
        catalysts=[
            Catalyst(what=str(c.get("what", ""))[:300], when_hint=str(c.get("when_hint", ""))[:80],
                     citation=_valid_cite(c.get("citation")))
            for c in data.get("catalysts", []) if isinstance(c, dict) and c.get("what")
        ][:4],
        source_note=str(data.get("source_note", ""))[:300],
        sources=sources,
    )
    if not brief.summary:
        raise LLMError("model returned an empty summary")

    payload = brief.model_dump(by_alias=True)
    async with SessionFactory() as session:
        await session.execute(
            text("INSERT INTO intel_artifacts (market_id, kind, range_key, payload, model) "
                 "VALUES (:m, 'brief', NULL, CAST(:p AS JSONB), :model)"),
            {"m": m["id"], "p": json.dumps(payload), "model": settings.llm_model},
        )
        await session.commit()
    log.info("brief generated for market %s (%d sources)", m["slug"], len(sources))
    return payload


async def load_fresh_brief(session: AsyncSession, market_id: int) -> dict[str, Any] | None:
    """Newest brief younger than the cache window, with generatedAt added."""
    from datetime import timedelta

    row = (
        await session.execute(
            text("SELECT payload, model, created_at FROM intel_artifacts "
                 "WHERE market_id = :m AND kind = 'brief' "
                 "AND created_at > now() - CAST(:age AS interval) "
                 "ORDER BY created_at DESC LIMIT 1"),
            {"m": market_id, "age": timedelta(hours=settings.intel_cache_hours)},
        )
    ).first()
    if row is None:
        return None
    payload = dict(row.payload)
    payload["generatedAt"] = row.created_at.isoformat()
    payload["model"] = row.model
    return payload
