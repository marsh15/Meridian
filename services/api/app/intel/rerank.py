"""Lexical reranker — local, deterministic, no rerank API.

Scores each source against the market's question/description/category:
term overlap dominates, a recency term keeps briefs current, and a
per-publisher cap stops one outlet from filling the whole context window.
"""

import math
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.intel.retrieval import RawSource

STOP = {
    "the", "a", "an", "of", "in", "on", "for", "to", "will", "be", "by",
    "and", "or", "is", "are", "at", "as", "its", "it", "this", "that",
    "than", "then", "into", "over", "after", "before", "does", "do", "did",
    "how", "what", "who", "when", "where", "why", "can", "could", "would",
    "should", "may", "might", "with", "from", "about", "more", "most",
    "there", "their", "his", "her", "they", "them", "any", "all", "each",
}


def tokenize(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", s.lower()) if t not in STOP]


def _overlap_ratio(query_terms: list[str], text: str) -> float:
    if not query_terms:
        return 0.0
    tokens = set(tokenize(text))
    hits = sum(1 for t in query_terms if t in tokens)
    return hits / len(query_terms)


def rerank(
    question: str,
    description: str,
    category: str,
    sources: "list[RawSource]",
    *,
    top: int = 6,
    now: datetime | None = None,
) -> "list[tuple[float, RawSource]]":
    now = now or datetime.now(timezone.utc)
    q_terms = tokenize(f"{question} {category}")
    d_terms = tokenize(description)

    scored: list[tuple[float, "RawSource"]] = []
    for src in sources:
        text = f"{src.title} {src.snippet}"
        q_overlap = _overlap_ratio(q_terms, text)
        d_overlap = _overlap_ratio(d_terms, text)
        # recency amplifies relevance; it must never substitute for it —
        # a fresh but topically irrelevant story is padding
        if q_overlap <= 0 and d_overlap <= 0:
            continue
        score = 2.0 * q_overlap + 0.5 * d_overlap
        if category.lower() in src.title.lower():
            score += 0.2
        if src.published_at is not None:
            age_days = max(0.0, (now - src.published_at).total_seconds() / 86_400)
            score += 0.6 * math.exp(-age_days / 14)
        else:
            score += 0.2  # undated (Wikipedia) — background value
        scored.append((score, src))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    picked: list[tuple[float, "RawSource"]] = []
    per_publisher: dict[str, int] = {}
    for score, src in scored:
        if len(picked) >= top:
            break
        n = per_publisher.get(src.publisher, 0)
        if n >= 2:
            continue
        per_publisher[src.publisher] = n + 1
        picked.append((score, src))
    return picked
