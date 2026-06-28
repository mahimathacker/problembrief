"""All LLM calls: extract pain points, dedupe into opportunities, write brief.

Provider-agnostic — set RADAR_PROVIDER=anthropic (default) or openai.
"""
from __future__ import annotations

import json

import config
from src.schema import Deduped, Extraction, Opportunity, PainPoint, SourceItem

_CATS = ", ".join(config.CATEGORIES)
_INTERESTS = ", ".join(config.INTERESTS)

# Clients are created lazily so you only need the key for the provider you use.
_anthropic_client = None
_openai_client = None


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def _openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI()
    return _openai_client


def _parse(system: str, user: str, schema, max_tokens: int):
    """Structured output → a validated pydantic object (or None)."""
    if config.PROVIDER == "openai":
        completion = _openai().beta.chat.completions.parse(
            model=config.OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=schema,
        )
        return completion.choices[0].message.parsed
    resp = _anthropic().messages.parse(
        model=config.MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    return resp.parsed_output


def _complete(system: str, user: str, max_tokens: int) -> str:
    """Plain-text completion."""
    if config.PROVIDER == "openai":
        completion = _openai().chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return completion.choices[0].message.content or ""
    msg = _anthropic().messages.create(
        model=config.MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


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
- Be strict: return only the strongest 1-4 pain points per batch (or zero if the batch \
does not contain a real opportunity). A thin day is better than a fake brief.
- Favor REAL, GENUINE problems whose solution would meaningfully help people — \
developers OR everyday/non-technical users. Real impact on real people matters more \
than novelty or cleverness.
- Prefer specific problems ("X has no good way to do Y") over broad topics ("AI is hard").
- The goal is a HIGH-QUALITY PRODUCT OPPORTUNITY — a real problem with a clear user, \
a believable buyer/adopter, repeated or intense pain, and a plausible wedge a small \
team could ship. Useful tools are welcome, but only if they could become a durable \
product, business, or widely adopted workflow.
- Reject "just a feature" ideas: one app/library missing a setting, a small UX fix, \
a how-to guide, a curated list, a compatibility tweak, a wrapper around one API, or \
generic automation with no clear buyer.
- Reject weak market logic: if the only buyer is a vague group like "developers", \
"SaaS companies", "platforms", or "enterprises" without evidence of budget, adoption, \
switching, compliance pressure, revenue loss, or repeated workaround pain, do not extract it.
- SKIP nice-to-haves and saturated categories (yet-another note-taking / journaling / \
to-do / blogging app, personal-productivity fluff) unless the discussion shows people \
actually paying or switching.
- `evidence` must be a real quote or close paraphrase from the post/comments.
- Each pain point must cite the source id(s) it came from.
- category must be exactly one of: {_CATS}.

Scoring (1-5 — calibrate honestly; most things are 2-3, reserve 5):
- pain: 1 = mild annoyance, 5 = blocks real work / felt daily.
- frequency: 1 = one mention, 5 = echoed across many posts/comments.
- buildability: 1 = needs a huge moat or scale, 5 = a small team could ship a wedge in weeks.
- market_signal: 1 = no sign anyone'd pay/adopt, 5 = budget/adoption pressure, paid \
workarounds, switching intent, compliance risk, or direct purchasing language.
- personal_interest: fit with the user's interests: {_INTERESTS}."""


def extract_pain_points(items: list[SourceItem], batch_size: int = 15) -> list[PainPoint]:
    out: list[PainPoint] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        parsed = _parse(
            _EXTRACT_SYS,
            "Extract pain points from these posts:\n\n" + _render_items(batch),
            Extraction,
            8000,
        )
        if parsed:
            out.extend(parsed.pain_points)
        print(f"  - extracted from batch {start // batch_size + 1}: {len(out)} total")
    return out


# --- 2. dedupe -----------------------------------------------------------

_DEDUPE_SYS = """You are given pain points extracted from many posts. Consolidate them \
into a focused set of opportunities.

Rules:
- Merge duplicates and near-duplicates into one opportunity; combine their source_ids.
- Rank by genuine pain × underserved market × willingness-to-pay/adopt. Keep only ideas \
that could become a strong product opportunity, not merely a feature request or demo.
- DROP anything vague, saturated, low-stakes, generic, or mostly solved by a small \
setting/plugin/script/guide/list. Also drop repo-specific feature requests unless they \
reveal a broader repeated workflow pain with a clear buyer.
- A single-source pain point can survive only if the pain is acute AND market_signal is \
strong. Otherwise treat it as anecdote, not an opportunity.
- AIM for the ~3-5 strongest DISTINCT opportunities. Return fewer, even zero, when the \
day is thin. Do not pad the brief.
- When merging, set frequency to reflect how many distinct posts/comments mention it; \
take the strongest pain/market_signal among merged items; keep buildability and \
personal_interest as your best estimate.
- Keep the clearest one-sentence summary and the single best piece of evidence.
- Leave `composite` at 0 — it is computed downstream.
- Do not invent new pain points; only consolidate what's given."""


def _composite(obj) -> float:
    """Weighted sum of the five 1-5 sub-scores (works on PainPoint or Opportunity)."""
    return round(sum(getattr(obj, k) * w for k, w in config.WEIGHTS.items()), 3)


_WEAK_OPPORTUNITY_TERMS = (
    "auto-save",
    "autosave",
    "browser plugin",
    "browser extension",
    "chrome extension",
    "guide",
    "curated list",
    "vetted list",
    "comparative guide",
    "setting",
    "config tweak",
    "toggle",
    "wrapper",
    "missing field",
    "abortearly",
)


def _passes_opportunity_bar(o: Opportunity) -> bool:
    """Deterministic guardrail against polished but weak product ideas."""
    if o.pain < 4 or o.market_signal < 3:
        return False
    if o.frequency < 3 and o.market_signal < 5:
        return False
    if o.buildability < 2:
        return False

    text = " ".join((o.summary, o.evidence, o.category)).lower()
    if any(term in text for term in _WEAK_OPPORTUNITY_TERMS):
        # Allow small-sounding ideas only when the model found exceptional market pull.
        return o.pain >= 5 and o.market_signal >= 5 and o.frequency >= 4
    return True


def dedupe(pain_points: list[PainPoint]) -> list[Opportunity]:
    if not pain_points:
        return []
    # Pre-rank by composite and cap, so the model's output stays within budget and
    # we dedupe the strongest signals rather than the long tail.
    ranked = sorted(pain_points, key=_composite, reverse=True)[: config.MAX_PAIN_POINTS]
    payload = json.dumps([p.model_dump() for p in ranked])
    parsed = _parse(_DEDUPE_SYS, f"Pain points:\n{payload}", Deduped, 16000)
    opps = parsed.opportunities if parsed else []
    for o in opps:
        o.composite = _composite(o)
    opps = [o for o in opps if _passes_opportunity_bar(o)]
    opps.sort(key=lambda o: o.composite, reverse=True)
    return opps


# --- 3. brief ------------------------------------------------------------

_BRIEF_SYS = """You write a sharp daily 'builder brief' for a founder/engineer who \
studies developer problems every morning. Tone: direct, opinionated, concrete. \
No fluff, no hype. Do not inflate weak ideas into startup-shaped language. If the \
evidence does not support a buyer, urgency, or wedge, say the day is thin rather than \
pretending. Use Markdown."""

# Human-readable site label per source, so links aren't mislabeled by the model.
_SITE = {
    "hackernews": "Hacker News",
    "lobsters": "Lobsters",
    "devto": "Dev.to",
    "github": "GitHub",
}


def write_brief(
    opps: list[Opportunity],
    date_str: str,
    item_count: int,
    id_to_url: dict[str, str] | None = None,
    id_to_source: dict[str, str] | None = None,
) -> str:
    id_to_url = id_to_url or {}
    id_to_source = id_to_source or {}
    top = opps[: config.TOP_N]

    # Resolve each opportunity's source_ids to {site, url} so the model cites links
    # verbatim with the correct site label instead of guessing either.
    payload_objs = []
    for o in top:
        d = o.model_dump()
        srcs, seen = [], set()
        for sid in d.get("source_ids", []):
            u = id_to_url.get(sid)
            if u and u not in seen:
                seen.add(u)
                srcs.append({"site": _SITE.get(id_to_source.get(sid, ""), "source"), "url": u})
        d["sources"] = srcs[:5]
        payload_objs.append(d)
    payload = json.dumps(payload_objs, indent=2)

    user = f"""Date: {date_str}
Scanned {item_count} posts from Hacker News, Lobsters, Dev.to, and GitHub. Top \
opportunities (already scored, sorted by composite):

{payload}

Write the brief with:
1. A 2-3 sentence '## TL;DR' of the day's strongest signal.
2. '## Opportunities' — one '### ' entry per opportunity with: the problem, why now, \
who'd pay, a one-line buildability read, and a `**The build:**` line naming the single \
concrete thing to ship first (the MVP wedge — what's actually possible to build next). \
Be skeptical and precise: do not describe generic buyers. Name the specific team, \
role, budget owner, or adopter only if the supplied evidence supports it. Do not turn \
feature requests, small utilities, guides, lists, or repo-specific bugs into SaaS ideas. \
Then end the entry with these two lines. \
The score line must look EXACTLY like this example — same word labels and '·' separators, \
but substitute the opportunity's real integers for pain / frequency / buildability / \
market_signal / personal_interest:
   `**Score:** pain 4 · freq 3 · build 5 · market 2 · interest 4`
   `**Sources:** ` followed by Markdown links built ONLY from that opportunity's \
`sources` — use each entry's `site` as the link text and its `url` as the link target, \
copied verbatim. Never invent a URL; omit the Sources line if `sources` is empty.
3. '## Watchlist' — one line on weaker-but-interesting threads, if any.
Keep it skimmable. Include every opportunity you're given above (they're already filtered \
and ranked) — one '### ' entry each. Only call the day "thin" in the TL;DR if you were \
genuinely handed just one or two."""
    return _complete(_BRIEF_SYS, user, 8000)
