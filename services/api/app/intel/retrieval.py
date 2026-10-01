"""Keyless source retrieval: Google News RSS + Wikipedia.

No search-API keys by design (ADR 0010): RSS gives real, linkable,
dated articles; Wikipedia gives background. Everything fails open —
network errors return fewer or zero sources and the brief still generates
from market data. A real User-Agent is mandatory; the default python UA
gets 403s.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

log = logging.getLogger("meridian.intel.retrieval")

UA = "Meridian/1.0 (prediction-market research; local dev)"
TIMEOUT = 6.0


@dataclass
class RawSource:
    title: str
    url: str
    publisher: str
    published_at: datetime | None
    snippet: str = ""


def _clean(title: str) -> str:
    # Google News titles append " - Publisher"; the <source> tag already
    # carries the publisher separately
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()


async def news_search(query: str, limit: int = 8) -> list[RawSource]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA},
                                     follow_redirects=True) as client:
            resp = await client.get(
                "https://news.google.com/rss/search",
                params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception:
        log.warning("news search failed for %r", query, exc_info=True)
        return []

    out: list[RawSource] = []
    for item in root.iter("item"):
        if len(out) >= limit:
            break
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        source = item.find("source")
        publisher = (source.text or "").strip() if source is not None else "news"
        pub = None
        if raw_date := item.findtext("pubDate"):
            try:
                from email.utils import parsedate_to_datetime

                pub = parsedate_to_datetime(raw_date).astimezone(timezone.utc)
            except ValueError:
                pub = None
        out.append(RawSource(title=_clean(title), url=link, publisher=publisher,
                             published_at=pub))
    return out


async def wiki_background(query: str, limit: int = 2) -> list[RawSource]:
    search = "https://en.wikipedia.org/w/api.php"
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA},
                                 follow_redirects=True) as client:
        try:
            resp = await client.get(search, params={
                "action": "query", "list": "search", "srlimit": str(limit),
                "srsearch": query, "format": "json",
            })
            resp.raise_for_status()
            titles = [hit["title"] for hit in resp.json().get("query", {}).get("search", [])]
        except Exception:
            log.warning("wiki search failed for %r", query, exc_info=True)
            return []
        out: list[RawSource] = []
        for title in titles[:limit]:
            try:
                summary = await client.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
                summary.raise_for_status()
                data = summary.json()
            except Exception:
                continue
            out.append(RawSource(
                title=f"Wikipedia: {title}",
                url=data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                publisher="Wikipedia",
                published_at=None,
                snippet=(data.get("extract") or "")[:400],
            ))
    return out


async def gather_sources(query: str, *, limit: int = 8) -> list[RawSource]:
    """News first (dated, citable), Wikipedia for background; deduped."""
    import asyncio

    news, wiki = await asyncio.gather(news_search(query, limit), wiki_background(query, 2))
    seen: set[str] = set()
    out: list[RawSource] = []
    for src in [*news, *wiki]:
        key = src.url.rsplit("?", 1)[0]
        if not src.url or key in seen:
            continue
        seen.add(key)
        out.append(src)
    return out
