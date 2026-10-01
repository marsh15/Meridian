# ADR 0010: An intelligence layer that earns trust with citations

- Status: Accepted (2026-10-01)
- Phase: 6 (ROADMAP — intelligence)

## Context

The ROADMAP's intelligence phase asked for market briefs (retrieval →
rerank → LLM → structured, cited bull/bear cases, catalysts, source
quality), "explain this move" over a chart range, and event-timeline
overlays. The interesting constraints: no paid API keys should be required
to develop or demo, the output must be verifiable (not a wall of generated
prose), and an LLM outage must degrade as gracefully as every other
optional dependency in this system.

## Decision

**Keyless retrieval.** Google News RSS plus Wikipedia's API, with a real
User-Agent — real, linkable, dated sources and background, no search-API
key. A local lexical reranker (term overlap with the question/description,
a recency boost that can never substitute for topical relevance, a
per-publisher cap) picks the context window. All retrieval fails open to
"no sources".

**One provider shape, any backend.** The LLM client speaks the
OpenAI-compatible chat protocol; `LLM_BASE_URL` selects the deployment:
Ollama on the laptop (free, offline, what this phase was verified against —
qwen3:1.7b produced a fully-cited brief in ~2 minutes), or any hosted API
with a key. Unset means the endpoints answer a clean 503. Reasoning-model
quirks are handled in the client (`<think>` stripping, empty-content
fallback, `/no_think` for qwen3, retry without `response_format`).

**The LLM cannot fabricate citations.** It receives numbered sources and
cites by index; the server attaches the titles and URLs the retriever
actually fetched, validates that every index exists, and rates per-source
quality from the model's assessments. A claim's citation can only point at
a real retrieved article — the property the whole feature stands on.

**Explanations are grounded in the exchange's own data first.** "Explain
this range" feeds the model the window's prices, every trade (sides,
sizes, timestamps), lifecycle events, and net flow computed from our
tables; news published *inside* the window is context, not the substance.
Drivers come back typed and weighted (`trade_flow|news|lifecycle|
liquidity|other`, weights 0–1) with a confidence grade.

**Artifacts, not calls.** Briefs and explanations persist in
`intel_artifacts` with the model name and generation time; reads are cheap
cache hits (12h for briefs, 15 min per range for explanations) and both
share one rate-limit scope (6/hour/user by default) because each miss
costs a model call. Generation is authenticated; a 404 on the brief read
is "nothing yet", not an error.

**The event timeline is deterministic.** Large trades (≥ the window's p90
volume, floor $20) and sharp candle moves (≥ max(8¢, 2× the *median*
absolute candle delta — median, because the moves being detected are
exactly the outliers that inflate a mean) join the lifecycle markers on
the candles endpoint. No model involved; the chart explains itself even
with the LLM off.

## Consequences

- The full pipeline runs locally: `ollama serve`, `LLM_BASE_URL=http://localhost:11434/v1`.
  Verified live: a Fed-rates brief with five real cited sources and
  grounded market stats, and a range explanation driven by the actual
  trades in the window.
- Latency is model-bound (a 1.7b model on a laptop: ~2 min per brief);
  the UI says so, and the cache makes it a one-time cost per market.
- Briefs are cached claims, not live truth — the TTL plus a manual
  regenerate covers staleness; price truth still flows over SSE.
- Hosted upgrades are one env pair away (LLM_BASE_URL + LLM_API_KEY),
  with retrieval quality (a real search API) as the natural next rung.
