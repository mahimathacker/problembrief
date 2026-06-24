"""Fetch + lightly clean posts from developer communities.

Sources:
  - Hacker News  (Algolia API)      — no auth, works out of the box
  - Lobsters     (hottest.json)     — no auth, works out of the box
  - Reddit       (official OAuth)    — opt-in; needs free API credentials, because
                                       Reddit now 403s unauthenticated .json scraping
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


# --- Reddit (official OAuth, opt-in) -------------------------------------

def _reddit_token() -> str | None:
    """Application-only OAuth token. Returns None if creds aren't configured."""
    if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
        return None
    try:
        r = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET),
            headers={"User-Agent": config.USER_AGENT},
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        print(f"  ! reddit auth failed: {e}")
        return None


def fetch_reddit(subreddits: list[str], limit: int) -> list[SourceItem]:
    """Top-of-day posts via Reddit's OAuth API. Skipped if no credentials."""
    token = _reddit_token()
    if not token:
        print("  - reddit: skipped (set REDDIT_CLIENT_ID/SECRET to enable — see README)")
        return []

    items: list[SourceItem] = []
    headers = {"Authorization": f"bearer {token}", "User-Agent": config.USER_AGENT}
    with httpx.Client(timeout=20, headers=headers) as c:
        for sub in subreddits:
            try:
                r = c.get(
                    f"https://oauth.reddit.com/r/{sub}/top",
                    params={"t": "day", "limit": limit},
                )
                r.raise_for_status()
                children = r.json().get("data", {}).get("children", [])
            except Exception as e:
                print(f"  ! reddit/{sub} skipped: {e}")
                continue

            for j, child in enumerate(children):
                d = child.get("data", {})
                title = d.get("title") or ""
                if not title or d.get("stickied"):
                    continue
                items.append(
                    SourceItem(
                        id=f"reddit-{sub}-{j}",
                        source="reddit",
                        subreddit=sub,
                        title=title,
                        text=_clean(d.get("selftext")),
                        url=f"https://www.reddit.com{d.get('permalink', '')}",
                        points=int(d.get("ups") or 0),
                        num_comments=int(d.get("num_comments") or 0),
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
    ):
        try:
            got = fn()
            print(f"  - {name}: {len(got)} items")
            items += got
        except Exception as e:
            print(f"  ! {name} skipped: {e}")

    reddit = fetch_reddit(config.SUBREDDITS, config.MAX_PER_SOURCE)
    if reddit:
        print(f"  - reddit: {len(reddit)} items")
    items += reddit

    return items
