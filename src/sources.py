"""Fetch + lightly clean posts from developer communities.

Sources (all no-auth, on by default):
  - Hacker News  (Algolia API)
  - Lobsters     (hottest.json)
  - Dev.to       (/api/articles)
  - GitHub       (issue Search API; optional GITHUB_TOKEN raises the rate limit)
"""
from __future__ import annotations

import re

import httpx

import config
from src.schema import SourceItem

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None, limit: int = 1200) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)  # strip HTML
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# --- Hacker News ---------------------------------------------------------

def fetch_hackernews(limit: int) -> list[SourceItem]:
    """HN front-page stories via the free Algolia API (no key, no auth)."""
    url = "https://hn.algolia.com/api/v1/search"
    params = {"tags": "front_page", "hitsPerPage": limit}
    with httpx.Client(timeout=20, headers={"User-Agent": config.USER_AGENT}) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        hits = r.json().get("hits", [])

    items: list[SourceItem] = []
    for i, h in enumerate(hits):
        title = h.get("title") or h.get("story_title") or ""
        if not title:
            continue
        items.append(
            SourceItem(
                id=f"hn-{i}",
                source="hackernews",
                title=title,
                text=_clean(h.get("story_text") or h.get("comment_text")),
                url=h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                points=int(h.get("points") or 0),
                num_comments=int(h.get("num_comments") or 0),
            )
        )
    return items


# --- Lobsters ------------------------------------------------------------

def fetch_lobsters(limit: int) -> list[SourceItem]:
    """Hottest stories from lobste.rs (open JSON, no auth)."""
    with httpx.Client(timeout=20, headers={"User-Agent": config.USER_AGENT}) as c:
        r = c.get("https://lobste.rs/hottest.json")
        r.raise_for_status()
        stories = r.json()[:limit]

    items: list[SourceItem] = []
    for i, s in enumerate(stories):
        title = s.get("title") or ""
        if not title:
            continue
        items.append(
            SourceItem(
                id=f"lobsters-{i}",
                source="lobsters",
                title=title,
                text=_clean(s.get("description")),
                url=s.get("url") or s.get("comments_url") or "",
                points=int(s.get("score") or 0),
                num_comments=int(s.get("comment_count") or 0),
            )
        )
    return items


# --- Dev.to --------------------------------------------------------------

def fetch_devto(limit: int) -> list[SourceItem]:
    """Top dev.to articles from the last week (open API, no auth)."""
    with httpx.Client(timeout=20, headers={"User-Agent": config.USER_AGENT}) as c:
        r = c.get("https://dev.to/api/articles", params={"top": 7, "per_page": limit})
        r.raise_for_status()
        articles = r.json()

    items: list[SourceItem] = []
    for i, a in enumerate(articles):
        title = a.get("title") or ""
        if not title:
            continue
        items.append(
            SourceItem(
                id=f"devto-{i}",
                source="devto",
                title=title,
                text=_clean(a.get("description")),
                url=a.get("url") or "",
                points=int(a.get("positive_reactions_count") or 0),
                num_comments=int(a.get("comments_count") or 0),
            )
        )
    return items


# --- GitHub Issues -------------------------------------------------------

def fetch_github(queries: list[str], limit: int, token: str = "") -> list[SourceItem]:
    """Search GitHub issues for pain signals (feature requests, 'is there a way to').

    Works unauthenticated; a token just raises the rate limit. Each result is a
    real, documented developer need — high signal for buildable pain points.
    """
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items: list[SourceItem] = []
    seen: set[str] = set()
    with httpx.Client(timeout=20, headers=headers) as c:
        for qi, q in enumerate(queries):
            try:
                r = c.get(
                    "https://api.github.com/search/issues",
                    params={"q": q, "sort": "reactions", "order": "desc", "per_page": limit},
                )
                r.raise_for_status()
                hits = r.json().get("items", [])
            except Exception as e:
                print(f"  ! github query {qi + 1} skipped: {e}")
                continue

            for j, h in enumerate(hits):
                if h.get("pull_request"):  # Search mixes issues + PRs; drop PRs
                    continue
                url = h.get("html_url") or ""
                title = h.get("title") or ""
                if not title or url in seen:
                    continue
                seen.add(url)
                items.append(
                    SourceItem(
                        id=f"github-{qi}-{j}",
                        source="github",
                        title=title,
                        text=_clean(h.get("body")),
                        url=url,
                        points=int((h.get("reactions") or {}).get("total_count") or 0),
                        num_comments=int(h.get("comments") or 0),
                    )
                )
    return items


# --- Orchestrator --------------------------------------------------------

def fetch_all() -> list[SourceItem]:
    items: list[SourceItem] = []

    for name, fn in (
        ("hackernews", lambda: fetch_hackernews(config.MAX_PER_SOURCE)),
        ("lobsters", lambda: fetch_lobsters(config.MAX_PER_SOURCE)),
        ("devto", lambda: fetch_devto(config.MAX_PER_SOURCE)),
        ("github", lambda: fetch_github(config.GITHUB_QUERIES, config.MAX_PER_SOURCE, config.GITHUB_TOKEN)),
    ):
        try:
            got = fn()
            print(f"  - {name}: {len(got)} items")
            items += got
        except Exception as e:
            print(f"  ! {name} skipped: {e}")

    return items
