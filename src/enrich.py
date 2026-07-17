"""Market enrichment: research each lead on the live web (Tavily) so the brief can
write a GROUNDED buildability thesis — existing tools, pricing, demand — instead of
guessing. Degrades gracefully to no context if TAVILY_API_KEY is unset.
"""
from __future__ import annotations

import re

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


_TITLE_SPLIT_RE = re.compile(r"\s+[-|:]\s+|\s+[–—]\s+")
_NOISE_WORDS = {
    "best",
    "top",
    "pricing",
    "plans",
    "alternatives",
    "reviews",
    "software",
    "tools",
    "apps",
    "guide",
    "comparison",
    "features",
}


def _candidate_name(title: str) -> str:
    """Best-effort competitor name from a search result title."""
    title = re.sub(r"\([^)]*\)", "", title or "").strip()
    first = _TITLE_SPLIT_RE.split(title, maxsplit=1)[0].strip()
    first = re.sub(r"^(best|top)\s+\d+\s+", "", first, flags=re.I).strip()
    first = re.sub(r"\s+(pricing|plans|reviews|alternatives|software|tool|app)$", "", first, flags=re.I).strip()
    words = first.split()
    if not words or len(words) > 5:
        return ""
    if all(w.lower().strip(".,") in _NOISE_WORDS for w in words):
        return ""
    return first


def _competitor_candidates(topic: str) -> list[str]:
    data = _search(f"{topic} software tools competitors pricing", max_results=8)
    names: list[str] = []
    seen = set()
    for res in data.get("results", []):
        name = _candidate_name(res.get("title", ""))
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names[: config.PRICING_LOOKUPS_PER_LEAD]


def _pricing_blocks(topic: str) -> list[str]:
    """Target pricing pages/snippets instead of hoping broad market search includes them."""
    blocks: list[str] = []
    broad = _search(f"{topic} pricing plans monthly cost software", max_results=5)
    answer = (broad.get("answer") or "").strip()
    if answer:
        blocks.append(f"Pricing search for topic: {topic}\nSummary: {answer}")

    candidates = _competitor_candidates(topic)
    for name in candidates:
        data = _search(f"{name} pricing plans monthly cost", max_results=3)
        answer = (data.get("answer") or "").strip()
        if answer:
            blocks.append(f"Pricing lookup: {name}\nSummary: {answer}")
        for res in data.get("results", [])[:2]:
            title = res.get("title", "")
            url = res.get("url", "")
            content = (res.get("content") or "")[:700]
            text = f"{title} {content}".lower()
            if any(k in text for k in ("pricing", "$", "/mo", "per month", "free", "plan")):
                blocks.append(f"Pricing result: {name}\n[{title}] ({url})\n{content}")
    return blocks


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
    pricing = _pricing_blocks(topic)
    if pricing:
        blocks.append("=== Targeted pricing evidence ===")
        blocks.extend(pricing)
    return "\n\n".join(blocks[:26])
