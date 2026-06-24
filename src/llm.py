"""All Claude calls: extract pain points, dedupe into opportunities, write brief."""
from __future__ import annotations

import json

import anthropic

import config
from src.schema import Deduped, Extraction, Opportunity, PainPoint, SourceItem

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

_CATS = ", ".join(config.CATEGORIES)
_INTERESTS = ", ".join(config.INTERESTS)


def _render_items(items: list[SourceItem]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"[{it.id}] ({it.source}, {it.points} pts, {it.num_comments} comments)\n"
            f"  title: {it.title}\n"
            f"  body: {it.text or '(link-only post)'}"
        )
    return "\n\n".join(lines)


# --- 1. extract ----------------------------------------------------------

_EXTRACT_SYS = f"""You analyze posts from developer communities and extract concrete, \
buildable PAIN POINTS — real frustrations, repeated complaints, or unmet needs that \
someone could turn into a product.

Rules:
- Only extract genuine pain points. Skip announcements, hype, and pure news.
- Each pain point must cite the source id(s) it came from.
- category must be exactly one of: {_CATS}.
- Score each 1-5. personal_interest reflects fit with the user's interests: {_INTERESTS}.
- Prefer specific problems ("X has no good way to do Y") over vague themes.
- It's fine to return zero pain points for a batch with no real signal."""


def extract_pain_points(items: list[SourceItem], batch_size: int = 15) -> list[PainPoint]:
    out: list[PainPoint] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        resp = _client.messages.parse(
            model=config.MODEL,
            max_tokens=8000,
            system=_EXTRACT_SYS,
            messages=[
                {
                    "role": "user",
                    "content": "Extract pain points from these posts:\n\n"
                    + _render_items(batch),
                }
            ],
            output_format=Extraction,
        )
        parsed = resp.parsed_output
        if parsed:
            out.extend(parsed.pain_points)
        print(f"  - extracted from batch {start // batch_size + 1}: {len(out)} total")
    return out


# --- 2. dedupe -----------------------------------------------------------

_DEDUPE_SYS = """You are given a list of pain points extracted from many posts. \
Merge duplicates and near-duplicates into a single opportunity each.

Rules:
- Combine source_ids from all merged items.
- When merging, set frequency to reflect how many distinct posts mention it (higher = \
more posts). Take the strongest pain/market_signal among merged items; keep buildability \
and personal_interest as the considered best estimate.
- Keep the clearest one-sentence summary and the single best piece of evidence.
- Leave `composite` at 0 — it is computed downstream.
- Do not invent new pain points; only consolidate what's given."""


def _composite(obj) -> float:
    """Weighted sum of the five 1-5 sub-scores (works on PainPoint or Opportunity)."""
    return round(sum(getattr(obj, k) * w for k, w in config.WEIGHTS.items()), 3)


def dedupe(pain_points: list[PainPoint]) -> list[Opportunity]:
    if not pain_points:
        return []
    # Pre-rank by composite and cap, so the model's output stays within budget and
    # we dedupe the strongest signals rather than the long tail.
    ranked = sorted(pain_points, key=_composite, reverse=True)[: config.MAX_PAIN_POINTS]
    payload = json.dumps([p.model_dump() for p in ranked])
    resp = _client.messages.parse(
        model=config.MODEL,
        max_tokens=16000,
        system=_DEDUPE_SYS,
        messages=[{"role": "user", "content": f"Pain points:\n{payload}"}],
        output_format=Deduped,
    )
    opps = resp.parsed_output.opportunities if resp.parsed_output else []
    for o in opps:
        o.composite = _composite(o)
    opps.sort(key=lambda o: o.composite, reverse=True)
    return opps


# --- 3. brief ------------------------------------------------------------

_BRIEF_SYS = """You write a sharp daily 'builder brief' for a founder/engineer who \
studies developer problems every morning. Tone: direct, opinionated, concrete. \
No fluff, no hype. Use Markdown."""


def write_brief(opps: list[Opportunity], date_str: str, item_count: int) -> str:
    top = opps[: config.TOP_N]
    payload = json.dumps([o.model_dump() for o in top], indent=2)
    user = f"""Date: {date_str}
Scanned {item_count} posts from Hacker News, Lobsters, Dev.to, and GitHub. Top \
opportunities (already scored, \
sorted by composite):

{payload}

Write the brief with:
1. A 2-3 sentence '## TL;DR' of the day's strongest signal.
2. '## Opportunities' — one '### ' entry per opportunity with: the problem, why now, \
who'd pay, a buildability read, and the score line `pain/freq/build/market/interest`.
3. '## Watchlist' — one line on weaker-but-interesting threads, if any.
Keep it skimmable."""
    msg = _client.messages.create(
        model=config.MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=_BRIEF_SYS,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")
