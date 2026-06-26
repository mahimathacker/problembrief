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

_EXTRACT_SYS = f"""You analyze posts AND their comment threads from developer \
communities and extract concrete, buildable PAIN POINTS — real frustrations, repeated \
complaints, or unmet needs someone could turn into a product.

Reading the input:
- A post may include a "Top comments:" section. Treat comments as the strongest \
evidence — agreement, "me too", described workarounds, and "is there a way to…" all \
signal real, shared pain.

What to extract:
- Be SELECTIVE. Quality over coverage: return at most the 3-4 strongest pain points \
per batch, or zero if there's no real signal. A vague theme is worse than nothing.
- Prefer specific problems ("X has no good way to do Y") over broad topics ("AI is hard").
- `evidence` must be a real quote or close paraphrase from the post/comments.
- Each pain point must cite the source id(s) it came from.
- category must be exactly one of: {_CATS}.

Scoring (1-5 — calibrate honestly; most things are 2-3, reserve 5):
- pain: 1 = mild annoyance, 5 = blocks real work / felt daily.
- frequency: 1 = one mention, 5 = echoed across many posts/comments.
- buildability: 1 = needs a huge moat or scale, 5 = a small team could ship a useful MVP in weeks.
- market_signal: 1 = no sign anyone'd pay, 5 = people asking for it or paying for workarounds.
- personal_interest: fit with the user's interests: {_INTERESTS}."""


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

_DEDUPE_SYS = """You are given pain points extracted from many posts. Consolidate them \
into a focused set of opportunities.

Rules:
- Merge duplicates and near-duplicates into one opportunity; combine their source_ids.
- DROP anything vague, one-off, or not genuinely buildable — a short sharp list beats a \
long mushy one.
- When merging, set frequency to reflect how many distinct posts/comments mention it; \
take the strongest pain/market_signal among merged items; keep buildability and \
personal_interest as your best estimate.
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


def write_brief(
    opps: list[Opportunity],
    date_str: str,
    item_count: int,
    id_to_url: dict[str, str] | None = None,
) -> str:
    id_to_url = id_to_url or {}
    top = opps[: config.TOP_N]

    # Resolve each opportunity's source_ids to real URLs so the model can cite them
    # verbatim instead of inventing links.
    payload_objs = []
    for o in top:
        d = o.model_dump()
        urls, seen = [], set()
        for sid in d.get("source_ids", []):
            u = id_to_url.get(sid)
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
        d["sources"] = urls[:5]
        payload_objs.append(d)
    payload = json.dumps(payload_objs, indent=2)

    user = f"""Date: {date_str}
Scanned {item_count} posts from Hacker News, Lobsters, Dev.to, and GitHub. Top \
opportunities (already scored, sorted by composite):

{payload}

Write the brief with:
1. A 2-3 sentence '## TL;DR' of the day's strongest signal.
2. '## Opportunities' — one '### ' entry per opportunity with: the problem, why now, \
who'd pay, a buildability read, the score line `pain/freq/build/market/interest`, and \
finally a `**Sources:** ` line of Markdown links built ONLY from that opportunity's \
`sources` URLs, each labeled by its site (GitHub / Hacker News / Lobsters / Dev.to). \
Copy URLs verbatim — never invent one; omit the line if `sources` is empty.
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
