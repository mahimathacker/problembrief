"""Cross-run dedup: remember which source URLs were surfaced in recent briefs so the
same problems don't repeat day after day. Backed by a small JSON file (state/seen.json)
that the daily workflow commits back to the repo — a lightweight 'database' with no
external service.

seen.json shape:  { "<url>": "YYYY-MM-DD (date last surfaced)" }
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import config


def _load() -> dict:
    try:
        return json.loads(config.SEEN_PATH.read_text())
    except Exception:
        return {}


def _save(seen: dict) -> None:
    config.SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))


def _within(day_str: str, days: int) -> bool:
    try:
        return date.fromisoformat(day_str) >= date.today() - timedelta(days=days)
    except Exception:
        return False


def filter_unseen(items, days: int):
    """Drop source items whose URL was surfaced in a brief within the last `days`."""
    seen = _load()
    fresh = [
        it for it in items
        if not (it.url and it.url in seen and _within(seen[it.url], days))
    ]
    dropped = len(items) - len(fresh)
    if dropped:
        print(f"  - dedup: dropped {dropped} items already surfaced in the last {days}d")
    return fresh


def record(opps, id_to_url: dict, retention_days: int) -> None:
    """Mark the surfaced opportunities' source URLs as seen today; prune old entries."""
    seen = _load()
    today = date.today().isoformat()
    for o in opps:
        for sid in o.source_ids:
            url = id_to_url.get(sid)
            if url:
                seen[url] = today
    seen = {url: d for url, d in seen.items() if _within(d, retention_days)}
    _save(seen)
