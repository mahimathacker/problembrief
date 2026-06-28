"""Fetch + lightly clean posts from developer communities.

Sources (all no-auth, on by default):
  - Hacker News  (Algolia API)
  - Lobsters     (hottest.json)
  - Dev.to       (/api/articles)
  - GitHub       (issue Search API; optional GITHUB_TOKEN raises the rate limit)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import httpx

import config
from src.schema import SourceItem

_TAG_RE = re.compile(r"<[^>]+>")


def _daily_rotation(pool: list[str], k: int) -> list[str]:
    """Pick k items from the pool, rotating the start by the date — so a different
    subset runs each day and the brief stops circling the same topics."""
    n = len(pool)
    if n <= k:
        return pool
    start = date.today().toordinal() % n
    return [pool[(start + i) % n] for i in range(k)]


def _clean(text: str | None, limit: int = 1200) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)  # strip HTML
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


_PAIN_SIGNAL_RE = re.compile(
    r"\b("
    r"alternative|blocked|bottleneck|broken|can't|cannot|complex|confusing|"
    r"difficult|friction|frustrat(?:e|ed|ing)|hard|missing|pain|problem|"
    r"slow|struggle|workaround|waste|wish"
    r")\b",
    re.IGNORECASE,
)

_LOW_SIGNAL_RE = re.compile(
    r"\b("
    r"career|documenting my|journey|learned|motivation|productivity|"
    r"self[- ]improvement|should have started|tutorial"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_pain_article(title: str, description: str) -> bool:
    text = f"{title} {description}"
    if _LOW_SIGNAL_RE.search(text):
        return False
    return bool(_PAIN_SIGNAL_RE.search(text))


def _append_comments(item: SourceItem, comments: list[str]) -> None:
    """Fold a thread's top comments into the item's text (capped to bound tokens)."""
    if comments:
        joined = "\n- ".join(comments)
        item.text = (item.text + f"\n\nTop comments:\n- {joined}").strip()[:4000]


def _hn_comments(object_id: str, client: httpx.Client, n: int) -> list[str]:
    """Top comments for an HN item via the Algolia item endpoint (breadth-first)."""
    try:
        r = client.get(f"https://hn.algolia.com/api/v1/items/{object_id}")
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    out: list[str] = []
    queue = list(data.get("children") or [])
    while queue and len(out) < n:
        node = queue.pop(0)
        t = _clean(node.get("text"), 400)
        if t:
            out.append(t)
        queue.extend(node.get("children") or [])
    return out


def _gh_comments(comments_url: str, client: httpx.Client, n: int) -> list[str]:
    """Top comments for a GitHub issue via its comments_url."""
    try:
        r = client.get(comments_url, params={"per_page": n})
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    return [t for cm in data[:n] if (t := _clean(cm.get("body"), 400))]


# --- Hacker News ---------------------------------------------------------

def fetch_hackernews(limit: int) -> list[SourceItem]:
    """HN searched for recent pain/complaint phrases (not the front page), so it
    surfaces real gripes and 'is there a better X' asks. Enriched with top comments."""
    phrases = _daily_rotation(config.HN_PAIN_PHRASES, config.HN_PHRASES_PER_DAY)
    cutoff_ts = int(
        (datetime.now(timezone.utc) - timedelta(days=config.HN_RECENCY_DAYS)).timestamp()
    )
    per_phrase = max(5, limit // max(1, len(phrases)) + 2)

    items: list[SourceItem] = []
    rows = []  # (item, object_id, num_comments) for comment enrichment
    seen_ids: set[str] = set()
    with httpx.Client(timeout=20, headers={"User-Agent": config.USER_AGENT}) as c:
        for phrase in phrases:
            try:
                r = c.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={
                        "query": phrase,
                        "tags": "story",
                        "numericFilters": f"created_at_i>{cutoff_ts}",
                        "hitsPerPage": per_phrase,
                    },
                )
                r.raise_for_status()
                hits = r.json().get("hits", [])
            except Exception as e:
                print(f"  ! hn search '{phrase}' skipped: {e}")
                continue

            for h in hits:
                oid = str(h.get("objectID"))
                title = h.get("title") or h.get("story_title") or ""
                if not title or oid in seen_ids:
                    continue
                seen_ids.add(oid)
                item = SourceItem(
                    id=f"hn-{len(items)}",
                    source="hackernews",
                    title=title,
                    text=_clean(h.get("story_text") or h.get("comment_text")),
                    url=h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                    points=int(h.get("points") or 0),
                    num_comments=int(h.get("num_comments") or 0),
                )
                items.append(item)
                rows.append((item, oid, item.num_comments))
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break

        if config.FETCH_COMMENTS:
            for item, oid, _ in sorted(rows, key=lambda x: x[2], reverse=True)[
                : config.COMMENTS_MAX_THREADS
            ]:
                _append_comments(item, _hn_comments(oid, c, config.COMMENTS_PER_THREAD))

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
    """Top dev.to articles from the last week, filtered for explicit pain signals."""
    with httpx.Client(timeout=20, headers={"User-Agent": config.USER_AGENT}) as c:
        r = c.get("https://dev.to/api/articles", params={"top": 7, "per_page": limit * 3})
        r.raise_for_status()
        articles = r.json()

    items: list[SourceItem] = []
    for i, a in enumerate(articles):
        title = a.get("title") or ""
        description = _clean(a.get("description"))
        if not title:
            continue
        if not _looks_like_pain_article(title, description):
            continue
        items.append(
            SourceItem(
                id=f"devto-{i}",
                source="devto",
                title=title,
                text=description,
                url=a.get("url") or "",
                points=int(a.get("positive_reactions_count") or 0),
                num_comments=int(a.get("comments_count") or 0),
            )
        )
        if len(items) >= limit:
            break
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

    # Recency window: surface issues created recently, not the all-time most-reacted
    # ones (which would repeat every day). Skipped if a query sets its own created:.
    cutoff = (date.today() - timedelta(days=config.GITHUB_RECENCY_DAYS)).isoformat()

    items: list[SourceItem] = []
    rows = []  # (item, comments_url, num_comments) for comment enrichment
    seen: set[str] = set()
    with httpx.Client(timeout=20, headers=headers) as c:
        for qi, q in enumerate(queries):
            q_full = q if "created:" in q else f"{q} created:>{cutoff}"
            try:
                r = c.get(
                    "https://api.github.com/search/issues",
                    params={"q": q_full, "sort": "reactions", "order": "desc", "per_page": limit},
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
                item = SourceItem(
                    id=f"github-{qi}-{j}",
                    source="github",
                    title=title,
                    text=_clean(h.get("body")),
                    url=url,
                    points=int((h.get("reactions") or {}).get("total_count") or 0),
                    num_comments=int(h.get("comments") or 0),
                )
                items.append(item)
                rows.append((item, h.get("comments_url") or "", item.num_comments))

        if config.FETCH_COMMENTS:
            for item, curl, _ in sorted(rows, key=lambda x: x[2], reverse=True)[
                : config.COMMENTS_MAX_THREADS
            ]:
                if curl:
                    _append_comments(item, _gh_comments(curl, c, config.COMMENTS_PER_THREAD))

    return items


# --- Orchestrator --------------------------------------------------------

def fetch_all() -> list[SourceItem]:
    items: list[SourceItem] = []

    for name, fn in (
        ("hackernews", lambda: fetch_hackernews(config.MAX_PER_SOURCE)),
        ("lobsters", lambda: fetch_lobsters(config.MAX_PER_SOURCE)),
        ("devto", lambda: fetch_devto(config.MAX_PER_SOURCE)),
        ("github", lambda: fetch_github(
            _daily_rotation(config.GITHUB_QUERIES, config.GITHUB_QUERIES_PER_DAY),
            config.MAX_PER_SOURCE,
            config.GITHUB_TOKEN,
        )),
    ):
        try:
            got = fn()
            print(f"  - {name}: {len(got)} items")
            items += got
        except Exception as e:
            print(f"  ! {name} skipped: {e}")

    return items
