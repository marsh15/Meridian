"""Intelligence endpoints (phase 6): market briefs and move explanations.

GETs are cheap cache reads (404 when nothing fresh exists). POST /brief and
GET /explain generate — they cost an LLM call, so they are authenticated
and share the `intel` rate-limit scope. Every failure mode is a clean
error: 503 when no LLM is configured, 502 when the model misbehaves.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.db import get_session
from app.intel import briefs, explain
from app.intel.provider import LLMError, LLMNotConfigured
from app.ratelimit import intel_limit
from app.routers.markets import CHART_RANGES, load_market

log = logging.getLogger("meridian.intel")

router = APIRouter(prefix="/api")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _market_or_404(session: AsyncSession, slug: str):
    m = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    if m is None:
        raise HTTPException(404, "Market not found.")
    return m


def _map_llm_error(err: LLMError) -> HTTPException:
    if isinstance(err, LLMNotConfigured):
        return HTTPException(503, "Intelligence layer not configured — set LLM_BASE_URL.")
    return HTTPException(502, f"Model call failed: {err}")


@router.get("/markets/{slug}/brief")
async def get_brief(
    slug: str, session: AsyncSession = Depends(get_session)
) -> dict:
    m = await _market_or_404(session, slug)
    cached = await briefs.load_fresh_brief(session, m["id"])
    if cached is None:
        raise HTTPException(404, "No brief yet — POST to generate one.")
    return {"brief": cached}


@router.post("/markets/{slug}/brief")
async def create_brief(
    slug: str,
    user: dict = Depends(intel_limit),
    session: AsyncSession = Depends(get_session),
) -> dict:
    m = await _market_or_404(session, slug)
    metrics.intel_requests.add(1, {"kind": "brief"})
    try:
        payload = await briefs.generate_brief(m)
    except LLMError as err:
        metrics.intel_failures.add(1, {"kind": "brief"})
        raise _map_llm_error(err) from err
    payload["generatedAt"] = _now_iso()
    return {"brief": payload}


@router.get("/markets/{slug}/explain")
async def get_explanation(
    slug: str,
    range: str = Query("1d", pattern="^(1h|6h|1d|1w|1m|all)$"),
    user: dict = Depends(intel_limit),
    session: AsyncSession = Depends(get_session),
) -> dict:
    m = await _market_or_404(session, slug)
    cached = await explain.load_fresh_explanation(session, m["id"], range)
    if cached is not None:
        return {"explanation": cached}
    metrics.intel_requests.add(1, {"kind": "explain"})
    try:
        payload = await explain.generate_explanation(m, range, CHART_RANGES[range][1])
    except LLMError as err:
        metrics.intel_failures.add(1, {"kind": "explain"})
        raise _map_llm_error(err) from err
    payload["generatedAt"] = _now_iso()
    return {"explanation": payload}
