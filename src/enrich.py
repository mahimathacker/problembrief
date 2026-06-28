"""Market enrichment: research each lead on the live web (Tavily) so the brief can
write a GROUNDED buildability thesis — existing tools, pricing, demand — instead of
guessing. Degrades gracefully to no context if TAVILY_API_KEY is unset.
"""
from __future__ import annotations

import httpx

import config


def _search(query: str, max_results: int = 4) -> list[dict]:
    if not config.TAVILY_API_KEY:
        return []
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": config.TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        print(f"  ! tavily search failed for '{query[:50]}…': {e}")
        return []


def market_context(topic: str) -> str:
    """Run a few targeted searches for one lead and return concatenated snippets.

    Mirrors the manual research a founder would do: who already builds this, what
    they charge, and whether the demand is real and repeated.
    """
    if not config.TAVILY_API_KEY:
        return ""
    queries = [
        f"existing tools, products and pricing for: {topic}",
        f"best alternatives for: {topic}",
        f"developers complaining about or asking for: {topic}",
    ]
    blocks: list[str] = []
    for q in queries:
        for res in _search(q, max_results=4):
            title = res.get("title", "")
            url = res.get("url", "")
            content = (res.get("content") or "")[:500]
            if title or content:
                blocks.append(f"[{title}] ({url})\n{content}")
    return "\n\n".join(blocks[:12])
