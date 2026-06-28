"""Market enrichment: research each lead on the live web (Tavily) so the brief can
write a GROUNDED buildability thesis — existing tools, pricing, demand — instead of
guessing. Degrades gracefully to no context if TAVILY_API_KEY is unset.
"""
from __future__ import annotations

import httpx

import config


def _search(query: str, max_results: int = 4) -> dict:
    """One Tavily search. Returns the full payload (a synthesized `answer` — which
    often carries pricing/adoption — plus `results`)."""
    if not config.TAVILY_API_KEY:
        return {}
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": config.TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ! tavily search failed for '{query[:50]}…': {e}")
        return {}


def market_context(topic: str) -> str:
    """Research one lead the way a founder would: who builds this, what they charge,
    how big the demand is, and what people gripe about. Returns concatenated evidence.
    """
    if not config.TAVILY_API_KEY:
        return ""
    queries = [
        f"{topic}: existing tools, products and competitors",
        f"{topic} pricing plans and cost per month",
        f"market demand, adoption and funding for tools that solve {topic}",
        f"developers complaining about or willing to pay for {topic}",
    ]
    blocks: list[str] = []
    for q in queries:
        data = _search(q, max_results=4)
        answer = (data.get("answer") or "").strip()
        if answer:
            blocks.append(f"Q: {q}\nSummary: {answer}")
        for res in data.get("results", [])[:3]:
            title = res.get("title", "")
            url = res.get("url", "")
            content = (res.get("content") or "")[:400]
            if title or content:
                blocks.append(f"[{title}] ({url})\n{content}")
    return "\n\n".join(blocks[:18])
