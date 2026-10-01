"""Intelligence layer (phase 6, ADR 0010).

Market briefs and move explanations: retrieval → rerank → LLM → validated,
cited structure. Fail-open throughout — without LLM_BASE_URL the endpoints
return a clean 503, and retrieval failures degrade to market-data-only
context. The LLM never supplies URLs: it cites fetched sources by index and
the server fills in the real titles and links, so citations cannot be
hallucinated.
"""
