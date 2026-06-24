"""Fetch + lightly clean posts from Hacker News and Reddit (no auth needed)."""
from __future__ import annotations

import re

import httpx

import config
from src.schema import SourceItem

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None, limit: int = 1200) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)  # strip HTML (HN comment/text fields)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


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


def fetch_reddit(subreddits: list[str], limit: int) -> list[SourceItem]:
    """Top-of-day posts per subreddit via Reddit's public .json (no auth)."""
    items: list[SourceItem] = []
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as c:
        for sub in subreddits:
            try:
                r = c.get(
                    f"https://www.reddit.com/r/{sub}/top.json",
                    params={"t": "day", "limit": limit},
                )
                r.raise_for_status()
                children = r.json().get("data", {}).get("children", [])
            except Exception as e:  # one bad subreddit shouldn't kill the run
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


def fetch_all() -> list[SourceItem]:
    items: list[SourceItem] = []
    try:
        hn = fetch_hackernews(config.MAX_PER_SOURCE)
        print(f"  - hackernews: {len(hn)} items")
        items += hn
    except Exception as e:
        print(f"  ! hackernews skipped: {e}")

    reddit = fetch_reddit(config.SUBREDDITS, config.MAX_PER_SOURCE)
    print(f"  - reddit: {len(reddit)} items")
    items += reddit
    return items
