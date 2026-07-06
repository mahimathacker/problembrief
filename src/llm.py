"""All LLM calls: extract pain points, dedupe into opportunities, write brief.

Provider-agnostic — set RADAR_PROVIDER=anthropic (default) or openai.
"""
from __future__ import annotations

import json

import config
from src.schema import Deduped, Extraction, MarketThesis, Opportunity, PainPoint, SourceItem

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

_EXTRACT_SYS = f"""You analyze posts, comment threads, AND web articles — from developer \
communities and the wider web — and extract concrete, buildable PAIN POINTS: real \
frustrations, repeated complaints, or unmet needs someone could turn into a product. \
The pain can belong to DEVELOPERS, to NORMAL BUSINESSES (restaurants, clinics, shops, \
agencies, real-estate, logistics, gyms, law firms…), or to EVERYDAY people — all are \
welcome.

Reading the input:
- A post may include a "Top comments:" section. Treat comments as the strongest \
evidence — agreement, "me too", described workarounds, and "is there a way to…" all \
signal real, shared pain.
- Some items are web articles describing an industry's problems. Extract the real \
underlying pain they describe; don't reject an item just because it's an article.
- Some items may be public Reddit web-search results (`source=reddit_web`). Treat them \
as noisy but valuable complaint signals. Be strict: extract them only when the post \
shows a specific user, a real job-to-be-done, a repeated/manual workaround, money/time \
lost, switching intent, or a clear "is there a tool for X" need. Do NOT turn one vague \
rant, meme, preference, or generic "I hate X" into an opportunity.
- IMPORTANT: do NOT let AI/infra/dev-tooling topics crowd out everything else. Actively \
pull problems from OTHER categories too — normal businesses, and other tech areas (web, \
mobile, data, fintech, e-commerce, healthcare, marketing). Variety across categories is \
a goal.

What to extract:
- Be strict but keep category coverage: return the strongest 2-6 pain points per batch \
(or zero if the batch has no real signal). When a batch contains both builder/dev/AI \
pain and small-business/vertical pain, keep at least one of each if both are concrete.
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

    from collections import Counter

    print(f"  - extracted by category: {dict(Counter(p.category for p in out))}")
    for p in out:
        print(f"      [{p.category}] pain{p.pain} mkt{p.market_signal} build{p.buildability} · {p.summary}")
    return out


# --- 2. dedupe -----------------------------------------------------------

_DEDUPE_SYS = """You merge a list of pain points into a set of DISTINCT leads. A later \
step researches the market and writes the thesis, and code then picks a \
category-balanced shortlist — so your ONLY job here is to merge true duplicates and keep \
everything else. Do NOT judge the market, pick winners, cap the count, or reject \
feature-shaped or vendor-adjacent ideas.

Rules:
- Merge only real duplicates / near-duplicates (the same core problem); combine their \
source_ids. Do NOT merge clearly different problems together.
- Keep EVERY distinct pain, across ALL categories. Do not collapse to a few themes and \
do not let one category (like AI) crowd out the rest. Return the full distinct set — \
typically most of the input.
- Drop ONLY exact duplicates or items that are not real problems.
- Keep each item's `category` unchanged. When merging, set frequency to how many \
distinct posts mention it; take the strongest pain/market_signal among merged items; \
keep buildability and personal_interest as your best estimate.
- Keep the clearest one-sentence summary and the single best piece of evidence.
- Leave `composite` at 0 — it is computed downstream.
- Do not invent new pain points; only consolidate what's given."""


_THESIS_SYS = """You are a pragmatic founder writing a grounded BUILDABILITY THESIS for \
ONE problem, using live web-research context.

Core judgment — WHO is the competition? A market crowded with small, focused startups \
that charge money is a GREEN FLAG: demand is validated and you can win with a sharp \
angle (like Tavily/Exa in search APIs). But if a BIG company — OpenAI, Anthropic, \
Google, Microsoft, GitHub, AWS, Notion, and the like — or the dominant existing tool \
could add this as a feature, or already does the job ~80%, that is a RED FLAG: if they \
do 80% today they will do 100% in their next release, and a small team cannot win.

Three tests that DECIDE conviction:
1. Big-company test: could a big platform or the leading existing tool just add this as \
a feature? If yes → conviction LOW. (Most flashy AI-infra ideas fail this — everyone \
chases them and the model vendors absorb them.)
2. Niche-depth test: the best ideas serve a SMALL, SPECIFIC group you can't split \
further — "independent physiotherapy clinics", not "healthcare"; "furniture Shopify \
stores", not "e-commerce". Broad ideas ("all developers", "all SaaS teams") are weak.
3. Boring test: boring, unglamorous, service-type problems are GOOD — few people want to \
build them, so there is room. Cool AI ideas are the most crowded and the most absorbable.

Rules:
- Write EVERY text field in very simple, plain English: short sentences, everyday words, \
no jargon (no "wedge", "moat", "incumbent", "greenfield", "leverage"). Say "big existing \
companies" instead of "incumbents". Write so a smart non-native English speaker gets it.
- Ground every claim in the provided web context. Do NOT invent competitors or pricing. \
If the context is thin, say so and lower conviction — don't bluff.
- Be honest about feature-vs-product: if the fix obviously belongs inside one existing \
tool, set is_product=false and lower conviction.
- If the context shows pricing or adoption numbers, CITE them in what_exists / \
demand_signal (e.g. "Portkey ~$49/mo", "Kafka is the default backbone"). If pricing \
truly isn't there, say "pricing unclear" in three words — don't write a long disclaimer.
- conviction: HIGH only if it passes all three tests above — a small specific niche, a \
boring/defensible problem, and NOT something a big company can just add. MEDIUM = real \
but broad or partly absorbable. LOW = a big company will likely add it, it's a feature \
not a product, the market is dominated by giants, or the niche is too broad. BE STRICT: \
if the biggest risk is "a big company can add this", conviction CANNOT be high — cap it \
at medium, usually low. Spread conviction honestly; don't default everything to medium.
- biggest_risk must be the honest main reason THIS specific idea fails — vary it, and \
name the specific big company or tool that would absorb it when that's the real risk.
- Set big_company_risk explicitly:
  low = hard for a big platform to absorb because it needs niche workflow/service work.
  medium = a big tool could add part of it, but niche execution still matters.
  high = Microsoft/GitHub/AWS/Google/OpenAI/Anthropic/Notion/etc. or the dominant tool \
could add it as a feature.
- Set niche_score 1-5. 5 means a tiny concrete ICP like "small law firms with 5-30 \
staff doing billable time cleanup", not "developers" or "all security teams".
- Set boring_score 1-5. 5 means dull service-like operational work; 1 means trendy AI \
infra or a flashy feature many builders will chase.
Return a single thesis."""


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


def _passes_lead_bar(o: Opportunity) -> bool:
    """A real, concrete, buildable pain that isn't junk. Whether the MARKET is real is
    decided later by live web enrichment — we don't demand proof of budget here (forums
    rarely contain it), we just filter out fluff and tiny one-setting fixes."""
    if o.pain < 4 or o.buildability < 3:
        return False
    text = " ".join((o.summary, o.evidence, o.category)).lower()
    if any(term in text for term in _WEAK_OPPORTUNITY_TERMS):
        return False
    return True


def dedupe(
    pain_points: list[PainPoint], source_items: list[SourceItem] | None = None
) -> list[Opportunity]:
    """Merge pain points into distinct, ranked leads (real pain, junk filtered out).
    Market validation happens later, in the enrichment step — not here."""
    if not pain_points:
        return []
    ranked = sorted(pain_points, key=_composite, reverse=True)[: config.MAX_PAIN_POINTS]
    payload = json.dumps([p.model_dump() for p in ranked])
    parsed = _parse(_DEDUPE_SYS, f"Pain points:\n{payload}", Deduped, 16000)
    opps = parsed.opportunities if parsed else []
    for o in opps:
        o.composite = _composite(o)
    print(f"  - dedupe produced {len(opps)} candidate leads")

    leads, dropped = [], []
    for o in opps:
        (leads if _passes_lead_bar(o) else dropped).append(o)
    for o in dropped:
        print(f"    dropped (junk/too small): [{o.category}] {o.summary}")
    leads.sort(key=lambda o: o.composite, reverse=True)
    print(f"  - {len(leads)} real leads kept:")
    for o in leads:
        print(f"      [{o.category}] composite {o.composite} · {o.summary}")
    return leads


def write_thesis(lead: Opportunity, context: str) -> MarketThesis | None:
    """Turn one lead + live web-research context into a grounded buildability thesis."""
    user = f"""Problem (from developer forums):
{lead.summary}

Evidence: {lead.evidence}

Live web research context (existing tools, pricing, demand — may be empty):
{context or '(no web research available — judge cautiously and lower conviction)'}

Write the buildability thesis."""
    thesis = _parse(_THESIS_SYS, user, MarketThesis, 4000)
    if thesis:
        thesis.source_ids = lead.source_ids
        thesis.category = lead.category
    return thesis


# --- 3. brief ------------------------------------------------------------

_BRIEF_SYS = """You write a daily 'builder brief' for someone who studies developer \
problems every morning and wants buildable SaaS/startup ideas.

Write in VERY SIMPLE, plain English. Short sentences. Everyday words. No jargon or fancy \
vocabulary — never use words like "wedge", "moat", "leverage", "paradigm", "incumbent", \
or "greenfield". Explain each idea like you're talking to a smart friend who is not a \
native English speaker. Be direct and concrete, no hype. A crowded market is a GOOD \
sign only when it is crowded with focused tools that charge money. A market owned by \
Microsoft/GitHub/AWS/Google/OpenAI/Anthropic or the dominant workflow tool is a danger, \
not validation. Prefer boring, narrow niches. Be honest about confidence. Use Markdown."""

# Human-readable site label per source, so links aren't mislabeled by the model.
_SITE = {
    "hackernews": "Hacker News",
    "lobsters": "Lobsters",
    "devto": "Dev.to",
    "github": "GitHub",
    "web": "Web",
}


def write_brief(
    theses: list[MarketThesis],
    date_str: str,
    item_count: int,
    id_to_url: dict[str, str] | None = None,
    id_to_source: dict[str, str] | None = None,
) -> str:
    id_to_url = id_to_url or {}
    id_to_source = id_to_source or {}

    # Resolve each thesis's source_ids to {site, url} so links are cited verbatim.
    payload_objs = []
    for t in theses:
        d = t.model_dump()
        srcs, seen = [], set()
        for sid in t.source_ids:
            u = id_to_url.get(sid)
            if u and u not in seen:
                seen.add(u)
                srcs.append({"site": _SITE.get(id_to_source.get(sid, ""), "source"), "url": u})
        d["sources"] = srcs[:5]
        payload_objs.append(d)
    payload = json.dumps(payload_objs, indent=2)

    user = f"""Date: {date_str}
Scanned {item_count} posts from Hacker News, Lobsters, Dev.to, and GitHub, then researched \
the top leads on the live web.

Buildability theses (each already grounded in web research):

{payload}

Write the brief in Markdown:
1. '## TL;DR' — 2-3 sentences on the strongest buildable idea today and why. If there are \
zero theses, say the day was thin and stop.
2. '## Buildable Ideas' — one '### <title>' entry per thesis, in this exact line order:
   `**Category:**` the `category` value written nicely — replace underscores with a space \
and capitalize (e.g. "small_business" → "Small business", "ai_agents" → "AI agents").
   `**Problem:**` the pain in one simple line.
   `**What's already out there:**` the real tools + their prices from `what_exists` \
(write "No clear competitor yet" if empty). Many tools already there is a GOOD sign — \
it means people want this.
   `**Who'd pay:**` who buys it, in plain words.
   `**How you'd win:**` how a new tool could still beat what's out there (from `wedge`).
   `**First build:**` the first thing to build (from `mvp`).
   `**Niche test:**` say who the tiny ICP is, then include `niche_score`/5.
   `**Boring test:**` say why this is or is not unsexy operational work, then include \
`boring_score`/5.
   `**Big-company risk:**` include `big_company_risk` and name the likely absorber if \
the risk is medium/high.
   `**Confidence:**` the `conviction` value (high / medium / low), then one short, plain \
line on the biggest reason it could fail.
   `**Sources:**` Markdown links built ONLY from `sources` — use each entry's `site` as \
the link text and its `url` as the target, copied verbatim. Omit if `sources` is empty.
Keep it short and easy to read. Most confident ideas first. Never invent a URL."""
    return _complete(_BRIEF_SYS, user, 8000)
