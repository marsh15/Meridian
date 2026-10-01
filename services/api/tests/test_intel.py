"""Intelligence layer (phase 6): briefs, explanations, and chart markers.

The LLM and retrieval are stubbed here — these tests pin the CONTRACT
(parsing, citation binding, caching, auth, rate limits, error shapes). The
live path against Ollama is verified manually and documented in ADR 0010.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.intel import briefs as briefs_mod
from app.intel import explain as explain_mod
from app.intel.provider import LLMError, _extract_json
from app.intel.rerank import rerank
from app.intel.retrieval import RawSource


def _src(title, publisher="Reuters", days_old=1, url=None):
    return RawSource(
        title=title,
        url=url or f"https://example.com/{abs(hash(title)) % 99999}",
        publisher=publisher,
        published_at=datetime.now(UTC) - timedelta(days=days_old),
        snippet=title.lower(),
    )


def _patch_pipeline(monkeypatch, module, model_output, sources):
    calls = []

    async def fake_gather(query, *, limit=8):
        return sources

    async def fake_chat(messages, *, max_tokens=1400):
        calls.append(messages)
        return model_output

    monkeypatch.setattr(module, "gather_sources", fake_gather)
    monkeypatch.setattr(module, "chat_json", fake_chat)
    return calls


GOOD_BRIEF = {
    "headline": "Fed path still data-dependent",
    "summary": "The market prices a cut as likely. Recent inflation prints "
               "support easing, but strong employment complicates the picture.",
    "bullish": [{"claim": "Inflation is trending to target", "citation": 1},
                {"claim": "Historical base rates favor cuts in this window", "citation": None}],
    "bearish": [{"claim": "Labor market remains hot", "citation": 2}],
    "catalysts": [{"what": "Next CPI release", "when_hint": "mid-month", "citation": 1}],
    "source_assessments": [{"idx": 1, "quality": "high"}, {"idx": 2, "quality": "medium"}],
    "source_note": "One strong wire story, one aggregator piece.",
}


# ------------------------------ pure units ----------------------------------


def test_extract_json_strips_think_blocks_and_fences():
    assert _extract_json('<think>reasoning</think>{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert _extract_json('prose {"a": {"b": 2}} more prose') == {"a": {"b": 2}}
    with pytest.raises(LLMError):
        _extract_json("no json here")


def test_rerank_prefers_overlap_and_caps_per_publisher():
    on_topic = [_src(f"Fed rate cut inflation story {i}", publisher="Wire") for i in range(3)]
    off_topic = [_src("Local sports team wins championship")]
    ranked = rerank("Will the Fed cut rates amid falling inflation?", "", "Economics",
                    on_topic + off_topic, top=4)
    assert ranked, "expected ranked results"
    titles = [s.title for _score, s in ranked]
    assert "Local sports team wins championship" not in titles
    # three wire stories, cap 2
    assert sum(1 for _s, s in ranked if s.publisher == "Wire") <= 2


def test_rerank_recency_breaks_ties():
    fresh = _src("Fed decision looms", days_old=0)
    stale = _src("Fed decision looms", days_old=60)
    ranked = rerank("Fed decision", "", "Economics", [stale, fresh], top=2)
    assert ranked[0][1] is fresh


# ------------------------------- briefs -------------------------------------


async def test_brief_generation_binds_real_citations(client, alice, monkeypatch):
    sources = [_src("CPI inflation cools to 2.1%"), _src("Jobs report beats expectations")]
    calls = _patch_pipeline(monkeypatch, briefs_mod, GOOD_BRIEF, sources)
    monkeypatch.setattr(settings, "llm_base_url", "http://stub:1/v1")

    r = await client.post("/api/markets", json={
        "question": "Will the Fed cut rates before July amid cooling inflation?",
        "category": "Economics", "closesAt": "2099-01-01", "initialYes": 60,
    })
    slug = r.json()["market"]["slug"]

    r = await client.post(f"/api/markets/{slug}/brief")
    assert r.status_code == 200, r.text
    brief = r.json()["brief"]
    assert brief["headline"] == GOOD_BRIEF["headline"]
    # the web contract is camelCase — regression-guard the alias serialization
    assert "sourceNote" in brief
    assert "publishedAt" in brief["sources"][0]
    # citations bind to the retrieved sources — the model can't invent URLs
    cited = [p["citation"] for p in brief["bullish"] + brief["bearish"] if p["citation"]]
    urls = {s["idx"]: s["url"] for s in brief["sources"]}
    for idx in cited:
        assert urls[idx] in {s.url for s in sources}
    assert brief["sources"][0]["quality"] == "high"

    # second GET is served from the artifact cache — model called once
    r = await client.get(f"/api/markets/{slug}/brief")
    assert r.status_code == 200
    assert len(calls) == 1


async def test_brief_rejects_empty_model_output(client, alice, monkeypatch):
    _patch_pipeline(monkeypatch, briefs_mod, {"headline": "x", "summary": ""}, [])
    monkeypatch.setattr(settings, "llm_base_url", "http://stub:1/v1")
    r = await client.post("/api/markets", json={
        "question": "Will this broken model output get rejected cleanly?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    r = await client.post(f"/api/markets/{slug}/brief")
    assert r.status_code == 502


async def test_brief_503_without_llm(client, alice):
    # settings default LLM_BASE_URL="" in tests
    r = await client.post("/api/markets", json={
        "question": "Will briefs fail cleanly without any LLM configured?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    r = await client.post(f"/api/markets/{slug}/brief")
    assert r.status_code == 503
    assert "LLM_BASE_URL" in r.json()["error"]
    r = await client.get(f"/api/markets/{slug}/brief")
    assert r.status_code == 404


async def test_brief_rate_limited(client, alice, fake_redis, monkeypatch):
    _patch_pipeline(monkeypatch, briefs_mod, GOOD_BRIEF, [])
    monkeypatch.setattr(settings, "llm_base_url", "http://stub:1/v1")
    monkeypatch.setattr(settings, "intel_requests_per_hour", 1)
    r = await client.post("/api/markets", json={
        "question": "Is the intel endpoint itself rate limited per user?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    assert (await client.post(f"/api/markets/{slug}/brief")).status_code == 200
    assert (await client.post(f"/api/markets/{slug}/brief")).status_code == 429


# ------------------------------ explanations --------------------------------


GOOD_EXPLAIN = {
    "narrative": "YES rose 14¢ over the window. The move is dominated by a "
                 "single large buy; news flow was quiet.",
    "drivers": [
        {"kind": "trade_flow", "weight": 0.7, "evidence": "$30 buy at 52¢"},
        {"kind": "liquidity", "weight": 0.3, "evidence": "thin book amplified the print"},
    ],
    "confidence": "medium",
}


async def test_explain_uses_window_data_and_caches(client, alice, monkeypatch):
    sources = [_src("Quiet news day for this market", days_old=0)]
    calls = _patch_pipeline(monkeypatch, explain_mod, GOOD_EXPLAIN, sources)
    monkeypatch.setattr(settings, "llm_base_url", "http://stub:1/v1")

    r = await client.post("/api/markets", json={
        "question": "Will the explain endpoint ground itself in real trades?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 3000})
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/markets/{slug}/explain?range=1d")
    assert r.status_code == 200, r.text
    ex = r.json()["explanation"]
    assert ex["range"] == "1d"
    assert "window" in ex and "from" in ex["window"]
    assert ex["drivers"][0]["kind"] == "trade_flow"
    # the model saw the real trade in its prompt (amounts format as $30)
    assert "$30" in calls[0][1]["content"]

    # cached for the range — model called once
    r = await client.get(f"/api/markets/{slug}/explain?range=1d")
    assert r.status_code == 200
    assert len(calls) == 1


async def test_explain_requires_auth(client, alice):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        r = await anon.get("/api/markets/will-anything/explain?range=1d")
        assert r.status_code in (401, 404)  # 404 hits before auth on bad slug


async def test_explain_404_on_unknown_market(client, alice):
    r = await client.get("/api/markets/no-such-market-ever/explain?range=1d")
    assert r.status_code == 404


# ---------------------------- chart markers ---------------------------------


async def test_candles_carry_event_timeline_markers(client, alice):
    from sqlalchemy import text

    from app.db import engine

    r = await client.post("/api/markets", json={
        "question": "Do sharp moves and large trades land on the chart?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    market_id = None
    async with engine.begin() as conn:
        market_id = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": slug})).scalar_one()
        # three hourly buckets ending flat, then a spike: 50, 50, 50, 70
        for hours_ago, price in ((4, 50), (3, 50), (2, 50), (1, 70)):
            await conn.execute(
                text("INSERT INTO price_history (market_id, price_cents, created_at) "
                     "VALUES (:m, :p, now() - make_interval(hours => :h))"),
                {"m": market_id, "p": price, "h": hours_ago})
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 4000})
    assert r.status_code == 200

    r = await client.get(f"/api/markets/{slug}/candles?range=1d")
    assert r.status_code == 200, r.text
    kinds = {m["kind"] for m in r.json()["markers"]}
    assert "open" in kinds
    assert "trade-large" in kinds          # the $40 buy clears the threshold
    assert "move" in kinds                 # the 50 → 70 spike
    dirs = {m["dir"] for m in r.json()["markers"] if m["kind"] == "trade-large"}
    assert dirs == {"up"}                  # a YES buy pushes up
