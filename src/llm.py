"""All LLM calls: extract pain points, dedupe into opportunities, write brief.

Provider-agnostic — set RADAR_PROVIDER=anthropic (default) or openai.
"""
from __future__ import annotations

import json

import config
from src.schema import Deduped, Extraction, Opportunity, OpportunityReview, PainPoint, SourceItem

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


def _openai_temperature_kwargs() -> dict:
    """Some newer OpenAI models only accept the default temperature."""
    if config.OPENAI_MODEL.startswith("gpt-5"):
        return {}
    return {"temperature": 0}


def _parse(system: str, user: str, schema, max_tokens: int):
    """Structured output → a validated pydantic object (or None)."""
    if config.PROVIDER == "openai":
        completion = _openai().beta.chat.completions.parse(
            model=config.OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            **_openai_temperature_kwargs(),
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
        temperature=0,
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
            **_openai_temperature_kwargs(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return completion.choices[0].message.content or ""
    msg = _anthropic().messages.create(
        model=config.MODEL,
        max_tokens=max_tokens,
        temperature=0,
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
- Reject self-improvement/content-marketing posts: career advice, learning journeys, \
"I wish I documented more", tool overload, productivity anxiety, personal workflow \
regret, or generic documentation habits are not product opportunities unless there is \
explicit team budget or compliance/revenue risk.
- Reject vendor/platform complaints when the obvious solution belongs to the vendor \
itself. Only extract them when an independent third-party wedge is clearly useful and \
buyers already spend money to manage that risk.
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
- DROP self-improvement, personal productivity, documentation journey, tool overload, \
and "centralized hub" ideas unless the evidence shows urgent team-level budget, \
compliance risk, or revenue loss.
- DROP vendor-specific bugs, deprecations, rate limits, outages, and missing features \
when the best answer is "the vendor should fix it." Do not convert those into generic \
monitoring dashboards, patched forks, or alerting tools unless the evidence proves \
people already pay for that workaround.
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


_VERIFY_SYS = """You are the skeptical final quality gate for a daily problem brief.

Your job is NOT to find a way to make each idea work. Your job is to reject weak ideas.
Default to keep=false unless the evidence clearly supports a real opportunity.

Keep an opportunity only if ALL of these are true:
1. The pain is external and concrete, not a personal reflection, tutorial, content post,
   career advice, vague productivity anxiety, or "too many tools" feeling.
2. The affected user has an urgent or recurring workflow/business problem, not a mild
   annoyance, one-off bug, deprecation warning, or missing setting.
3. The buyer/adopter is specific and believable from the evidence. Generic buyers like
   "developers", "teams", "SaaS companies", "enterprises", or "platforms" are not enough.
4. The first product wedge is independently valuable. Reject if the best solution is
   "the vendor should fix it", a patched fork, generic monitoring dashboard, centralized
   hub, curated list, guide, wrapper, plugin, or simple automation.
5. Market signal is proven by the evidence: budget, paid workaround, switching intent,
   compliance/revenue risk, strong adoption pressure, or repeated workaround pain.
6. The opportunity could plausibly become a durable product or business, not merely a
   nice feature, internal script, or small open-source contribution.

Scoring from the previous model is untrusted. Re-score mentally from the evidence and
reject anything that was inflated. Return one decision for every input index."""


def _composite(obj) -> float:
    """Weighted sum of the five 1-5 sub-scores (works on PainPoint or Opportunity)."""
    return round(sum(getattr(obj, k) * w for k, w in config.WEIGHTS.items()), 3)


_WEAK_OPPORTUNITY_TERMS = (
    "auto-save",
    "autosave",
    "centralized hub",
    "decision paralysis",
    "documentation journey",
    "documentation tools",
    "self-improvement",
    "tool overload",
    "overwhelming variety",
    "productivity anxiety",
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
    "node.js 20 deprecation",
    "deprecation warning",
    "patched action",
    "rate limiting",
    "rate limits",
    "monitoring tool",
    "usage analytics",
)


def _passes_opportunity_bar(o: Opportunity) -> bool:
    """Deterministic guardrail against polished but weak product ideas."""
    if o.pain < 4 or o.market_signal < 4:
        return False
    if o.frequency < 4 and o.market_signal < 5:
        return False
    if o.buildability < 2:
        return False

    text = " ".join((o.summary, o.evidence, o.category)).lower()
    if any(term in text for term in _WEAK_OPPORTUNITY_TERMS):
        # Allow small-sounding ideas only when the model found exceptional market pull.
        return o.pain >= 5 and o.market_signal >= 5 and o.frequency >= 4
    return True


def _bar_reject_reason(o: Opportunity) -> str:
    if o.pain < 4:
        return f"pain too low ({o.pain})"
    if o.market_signal < 4:
        return f"market signal too low ({o.market_signal})"
    if o.frequency < 4 and o.market_signal < 5:
        return f"frequency too low ({o.frequency}) without exceptional market signal"
    if o.buildability < 2:
        return f"buildability too low ({o.buildability})"

    text = " ".join((o.summary, o.evidence, o.category)).lower()
    if any(term in text for term in _WEAK_OPPORTUNITY_TERMS):
        return "weak-opportunity pattern without exceptional evidence"
    return "unknown"


def _passes_research_lead_bar(o: Opportunity) -> bool:
    """Keep real-but-unproven pains visible without calling them opportunities."""
    if o.pain < 4 or o.frequency < 3 or o.buildability < 3:
        return False
    if o.market_signal < 3:
        return False

    text = " ".join((o.summary, o.evidence, o.category)).lower()
    if any(term in text for term in _WEAK_OPPORTUNITY_TERMS):
        return False
    return True


def _verify_opportunities(
    opps: list[Opportunity], source_items: list[SourceItem] | None = None
) -> list[Opportunity]:
    if not opps:
        return []

    source_lookup = {it.id: it for it in source_items or []}
    payload = json.dumps(
        [
            {
                "index": i,
                "summary": o.summary,
                "category": o.category,
                "evidence": o.evidence,
                "source_ids": o.source_ids,
                "pain": o.pain,
                "frequency": o.frequency,
                "buildability": o.buildability,
                "market_signal": o.market_signal,
                "personal_interest": o.personal_interest,
                "composite": o.composite,
                "source_context": [
                    {
                        "id": sid,
                        "source": source_lookup[sid].source,
                        "title": source_lookup[sid].title,
                        "text": source_lookup[sid].text[:1200],
                    }
                    for sid in o.source_ids
                    if sid in source_lookup
                ],
            }
            for i, o in enumerate(opps)
        ],
        indent=2,
    )
    parsed = _parse(
        _VERIFY_SYS,
        "Review these candidate opportunities against their source_context. Return "
        "keep=false for weak, inflated, or unsupported ideas. If source_context is "
        "available, trust it more than the summary/evidence fields:\n\n"
        f"{payload}",
        OpportunityReview,
        8000,
    )
    if not parsed:
        return []

    for d in parsed.decisions:
        if not d.keep:
            print(f"    verifier rejected #{d.index}: {d.reason}")

    keep_indexes = {
        d.index
        for d in parsed.decisions
        if d.keep and 0 <= d.index < len(opps)
    }
    return [o for i, o in enumerate(opps) if i in keep_indexes]


def dedupe(
    pain_points: list[PainPoint], source_items: list[SourceItem] | None = None
) -> tuple[list[Opportunity], list[Opportunity]]:
    if not pain_points:
        return [], []
    # Pre-rank by composite and cap, so the model's output stays within budget and
    # we dedupe the strongest signals rather than the long tail.
    ranked = sorted(pain_points, key=_composite, reverse=True)[: config.MAX_PAIN_POINTS]
    payload = json.dumps([p.model_dump() for p in ranked])
    parsed = _parse(_DEDUPE_SYS, f"Pain points:\n{payload}", Deduped, 16000)
    opps = parsed.opportunities if parsed else []
    for o in opps:
        o.composite = _composite(o)
    print(f"  - dedupe produced {len(opps)} candidate opportunities")

    gated = []
    research_leads = []
    for o in opps:
        if _passes_opportunity_bar(o):
            gated.append(o)
        else:
            reason = _bar_reject_reason(o)
            if _passes_research_lead_bar(o):
                research_leads.append(o)
                print(f"    research lead: {o.summary} ({reason})")
            else:
                print(f"    score gate rejected: {o.summary} ({reason})")
    print(f"  - score gate kept {len(gated)}/{len(opps)} candidates")
    print(f"  - research lead gate kept {len(research_leads)} candidates")

    opps = _verify_opportunities(gated, source_items)
    print(f"  - verifier kept {len(opps)}/{len(gated)} candidates")
    opps.sort(key=lambda o: o.composite, reverse=True)
    research_leads.sort(key=lambda o: o.composite, reverse=True)
    return opps, research_leads[: config.TOP_N]


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
    research_leads: list[Opportunity] | None = None,
) -> str:
    id_to_url = id_to_url or {}
    id_to_source = id_to_source or {}
    top = opps[: config.TOP_N]
    leads = (research_leads or [])[: config.TOP_N]

    # Resolve each opportunity's source_ids to {site, url} so the model cites links
    # verbatim with the correct site label instead of guessing either.
    def with_sources(items: list[Opportunity]) -> list[dict]:
        payload_objs = []
        for o in items:
            d = o.model_dump()
            srcs, seen = [], set()
            for sid in d.get("source_ids", []):
                u = id_to_url.get(sid)
                if u and u not in seen:
                    seen.add(u)
                    srcs.append({"site": _SITE.get(id_to_source.get(sid, ""), "source"), "url": u})
            d["sources"] = srcs[:5]
            payload_objs.append(d)
        return payload_objs

    payload_objs = with_sources(top)
    lead_payload_objs = with_sources(leads)
    payload = json.dumps(payload_objs, indent=2)
    lead_payload = json.dumps(lead_payload_objs, indent=2)

    user = f"""Date: {date_str}
Scanned {item_count} posts from Hacker News, Lobsters, Dev.to, and GitHub.

Strict opportunities (buyer-backed, already scored, sorted by composite):

{payload}

Research leads (real pain, but market/buyer proof is not strong enough yet):

{lead_payload}

Write the brief with:
1. A 2-3 sentence '## TL;DR' of the day's strongest signal. If there are zero strict \
opportunities but some research leads, say that clearly: "No proven opportunities, but \
N research leads worth validating."
2. '## Opportunities' — include one '### ' entry per strict opportunity. If there are \
none, write exactly: `None passed the opportunity bar today.`
Each strict opportunity entry must include: the problem, why now, who'd pay, a one-line \
buildability read, and a `**The build:**` line naming the single concrete thing to ship \
first (the MVP wedge — what's actually possible to build next). \
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
3. '## Research Leads' — include up to {config.TOP_N} leads. These are NOT validated \
opportunities. For each, use one '### ' entry with:
   `**Signal:**` the concrete pain.
   `**Why it is not ready:**` what buyer/market proof is missing.
   `**Validate next:**` one specific research action or question.
   `**Sources:**` links copied from `sources`.
If there are no research leads, write exactly: `None.`
4. '## Watchlist' — one line only if there is a weaker pattern not covered above.
Keep it skimmable. Never upgrade research leads into opportunities."""
    return _complete(_BRIEF_SYS, user, 8000)
