"""All LLM calls: extract pain points, dedupe into opportunities, write brief.

Provider-agnostic — set RADAR_PROVIDER=anthropic (default), openai, gemini, or
github_models.
"""
from __future__ import annotations

import json
import os
import re
import time

import config
from src.schema import Deduped, Extraction, MarketThesis, Opportunity, PainPoint, SourceItem

_CATS = ", ".join(config.CATEGORIES)
_INTERESTS = ", ".join(config.INTERESTS)

# Clients are created lazily so you only need the key for the provider you use.
_anthropic_client = None
_openai_client = None

_PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "github_models": "GitHub Models",
}


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

        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def _openai_temperature_kwargs() -> dict:
    """Some newer OpenAI models only accept the default temperature."""
    if config.OPENAI_MODEL.startswith("gpt-5"):
        return {}
    return {"temperature": 0}


def _provider_chain() -> list[str]:
    providers = [config.PROVIDER, *config.FALLBACK_PROVIDERS]
    out = []
    for p in providers:
        if p and p not in out:
            out.append(p)
    return out


def _provider_has_credentials(provider: str) -> bool:
    if provider == "openai":
        return bool(config.OPENAI_API_KEY)
    if provider == "gemini":
        return bool(config.GEMINI_API_KEY)
    if provider == "github_models":
        return bool(config.GITHUB_MODELS_TOKEN)
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    return False


def _ready_provider_chain() -> list[str]:
    return [p for p in _provider_chain() if _provider_has_credentials(p)]


def _warn_provider_failed(provider: str, err: Exception, fallback: str | None) -> None:
    label = _PROVIDER_LABELS.get(provider, provider)
    msg = str(err).replace("\n", " ")
    if len(msg) > 240:
        msg = msg[:237] + "..."
    if fallback:
        fb_label = _PROVIDER_LABELS.get(fallback, fallback)
        print(f"  ! {label} failed; trying {fb_label}: {msg}")
    else:
        print(f"  ! {label} failed and no fallback remains: {msg}")


def _is_payload_too_large(err: Exception) -> bool:
    response = getattr(err, "response", None)
    if getattr(response, "status_code", None) == 413:
        return True
    msg = str(err).lower()
    return "413" in msg and "payload too large" in msg


def _is_rate_limited(err: Exception) -> bool:
    response = getattr(err, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True
    msg = str(err).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _github_models_generate(
    system: str,
    user: str,
    max_tokens: int,
    *,
    json_mode: bool = False,
) -> str:
    """GitHub Models chat-completions call using the Actions GITHUB_TOKEN/PAT."""
    if not config.GITHUB_MODELS_TOKEN:
        raise RuntimeError(
            "GITHUB_MODELS_TOKEN or GITHUB_TOKEN is required when using GitHub Models"
        )

    import httpx

    payload = {
        "model": config.GITHUB_MODELS_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config.GITHUB_MODELS_TOKEN}",
        "X-GitHub-Api-Version": config.GITHUB_MODELS_API_VERSION,
        "Content-Type": "application/json",
    }
    last_response = None
    for attempt in range(5):
        r = httpx.post(
            "https://models.github.ai/inference/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        if json_mode and r.status_code == 400 and "response_format" in payload:
            payload.pop("response_format", None)
            r = httpx.post(
                "https://models.github.ai/inference/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )
        if r.status_code == 410:
            print(
                "  ! GitHub Models endpoint/API version returned 410 Gone; "
                f"using api version {config.GITHUB_MODELS_API_VERSION}"
            )
        if r.status_code != 429:
            break
        last_response = r
        retry_after = r.headers.get("retry-after")
        delay = int(retry_after) if retry_after and retry_after.isdigit() else 12 * (attempt + 1)
        print(
            f"  ! GitHub Models rate limited; retrying in {delay}s "
            f"(attempt {attempt + 1}/5)"
        )
        time.sleep(delay)
    else:
        assert last_response is not None
        last_response.raise_for_status()

    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"].get("content", "") or ""


def _gemini_generate(system: str, user: str, max_tokens: int, *, json_mode: bool = False) -> str:
    """Gemini REST call. Keeps us from needing another SDK dependency."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required when RADAR_PROVIDER=gemini")

    import httpx

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{config.GEMINI_MODEL}:generateContent"
    )
    generation_config = {
        "temperature": 0,
        "maxOutputTokens": max_tokens,
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation_config,
    }
    last_error = None
    for attempt in range(4):
        r = httpx.post(
            url,
            params={"key": config.GEMINI_API_KEY},
            json=payload,
            timeout=120,
        )
        if r.status_code != 429:
            r.raise_for_status()
            break

        last_error = r
        retry_after = r.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            delay = int(retry_after)
        else:
            delay = 8 * (attempt + 1)
        print(f"  ! gemini rate limited; retrying in {delay}s (attempt {attempt + 1}/4)")
        time.sleep(delay)
    else:
        assert last_error is not None
        last_error.raise_for_status()

    time.sleep(1.2)
    r.raise_for_status()
    data = r.json()
    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    return "".join(p.get("text", "") for p in parts).strip()


def _json_from_text(text: str):
    """Parse JSON, tolerating fenced blocks if a model returns them."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    first_obj = text.find("{")
    first_arr = text.find("[")
    starts = [i for i in (first_obj, first_arr) if i >= 0]
    if starts:
        start = min(starts)
        end = max(text.rfind("}"), text.rfind("]"))
        if end > start:
            text = text[start : end + 1]
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    text = re.sub(r"\bNaN\b|\bInfinity\b|-Infinity", "null", text)
    return json.loads(text)


_DEFAULT_PAIN_SCORES = {
    "pain": 3,
    "frequency": 2,
    "buildability": 3,
    "market_signal": 2,
    "personal_interest": 3,
}


def _coerce_schema_payload(data, schema):
    """Fill conservative defaults when weaker JSON-mode models omit score fields."""
    if schema is Extraction:
        items = data.get("pain_points", []) if isinstance(data, dict) else []
        clean = []
        for item in items:
            if isinstance(item, dict):
                if not item.get("summary"):
                    continue
                item.setdefault("category", config.CATEGORIES[0])
                if item.get("category") not in config.CATEGORIES:
                    item["category"] = config.CATEGORIES[0]
                for key, value in _DEFAULT_PAIN_SCORES.items():
                    item.setdefault(key, value)
                item.setdefault("source_ids", [])
                item.setdefault("evidence", "")
                clean.append(item)
        if isinstance(data, dict):
            data["pain_points"] = clean
        return data

    if schema is Deduped:
        items = data.get("opportunities", []) if isinstance(data, dict) else []
        clean = []
        for item in items:
            if isinstance(item, dict):
                if not item.get("summary"):
                    continue
                item.setdefault("category", config.CATEGORIES[0])
                if item.get("category") not in config.CATEGORIES:
                    item["category"] = config.CATEGORIES[0]
                for key, value in _DEFAULT_PAIN_SCORES.items():
                    item.setdefault(key, value)
                item.setdefault("source_ids", [])
                item.setdefault("evidence", "")
                item.setdefault("composite", 0)
                clean.append(item)
        if isinstance(data, dict):
            data["opportunities"] = clean
        return data

    return data


def _parse_json_completion(
    provider: str,
    system: str,
    user: str,
    schema,
    max_tokens: int,
):
    schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    prompt = (
        f"{user}\n\n"
        "Return ONLY strict valid JSON. No markdown. No comments. No ellipses. "
        "Use double quotes for every key and string. Do not use NaN or Infinity. "
        f"Match this JSON schema exactly:\n{schema_json}"
    )
    last_error = None
    for attempt in range(2):
        if provider == "gemini":
            text = _gemini_generate(system, prompt, max_tokens, json_mode=True)
        elif provider == "github_models":
            text = _github_models_generate(system, prompt, max_tokens, json_mode=True)
        else:
            raise ValueError(f"Provider does not use JSON completion parse: {provider!r}")
        try:
            data = _coerce_schema_payload(_json_from_text(text), schema)
            return schema.model_validate(data)
        except Exception as e:
            last_error = e
            label = _PROVIDER_LABELS.get(provider, provider)
            print(f"  ! {label} returned invalid JSON; retrying ({attempt + 1}/2): {e}")
            prompt = (
                f"{user}\n\n"
                "Your previous response was invalid JSON. Return ONLY a compact JSON object "
                "matching the schema. No prose, no markdown, no truncation, no trailing commas.\n"
                f"Schema:\n{schema_json}"
            )
    raise last_error


def _parse_with_provider(provider: str, system: str, user: str, schema, max_tokens: int):
    if provider == "openai":
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
    if provider in ("gemini", "github_models"):
        return _parse_json_completion(provider, system, user, schema, max_tokens)
    if provider == "anthropic":
        resp = _anthropic().messages.parse(
            model=config.MODEL,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        return resp.parsed_output
    raise ValueError(f"Unknown RADAR_PROVIDER: {provider!r}")


def _parse(system: str, user: str, schema, max_tokens: int):
    """Structured output → a validated pydantic object (or None)."""
    chain = _ready_provider_chain()
    if not chain:
        raise RuntimeError("No configured LLM provider has credentials.")
    for idx, provider in enumerate(chain):
        try:
            return _parse_with_provider(provider, system, user, schema, max_tokens)
        except Exception as e:
            fallback = chain[idx + 1] if idx + 1 < len(chain) else None
            _warn_provider_failed(provider, e, fallback)
            if fallback is None:
                raise


def _complete_with_provider(provider: str, system: str, user: str, max_tokens: int) -> str:
    if provider == "openai":
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
    if provider == "gemini":
        return _gemini_generate(system, user, max_tokens)
    if provider == "github_models":
        return _github_models_generate(system, user, max_tokens)
    if provider == "anthropic":
        msg = _anthropic().messages.create(
            model=config.MODEL,
            max_tokens=max_tokens,
            temperature=0,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")
    raise ValueError(f"Unknown RADAR_PROVIDER: {provider!r}")


def _complete(system: str, user: str, max_tokens: int) -> str:
    """Plain-text completion."""
    chain = _ready_provider_chain()
    if not chain:
        raise RuntimeError("No configured LLM provider has credentials.")
    for idx, provider in enumerate(chain):
        try:
            return _complete_with_provider(provider, system, user, max_tokens)
        except Exception as e:
            fallback = chain[idx + 1] if idx + 1 < len(chain) else None
            _warn_provider_failed(provider, e, fallback)
            if fallback is None:
                raise


def _render_items(items: list[SourceItem]) -> str:
    lines = []
    max_text_chars = 2600 if "github_models" in _provider_chain() else 5000
    for it in items:
        text = it.text or "(link-only post)"
        if len(text) > max_text_chars:
            text = text[:max_text_chars].rsplit(" ", 1)[0] + "…"
        lines.append(
            f"[{it.id}] ({it.source}, {it.points} pts, {it.num_comments} comments)\n"
            f"  title: {it.title}\n"
            f"  body: {text}"
        )
    return "\n\n".join(lines)


def _source_from_id(source_id: str) -> str:
    if source_id.startswith("reddit-web-"):
        return "reddit_web"
    return source_id.split("-", 1)[0]


# --- 1. extract ----------------------------------------------------------

_EXTRACT_SYS = f"""You analyze posts, comment threads, AND web articles and extract \
concrete, buildable PAIN POINTS: real frustrations, repeated complaints, or unmet needs \
someone could turn into a product.

Only extract problems that fit one of these focused categories:
- `devtools`: tools for developers, APIs, CI, testing, docs, SDKs, databases, web/mobile \
engineering, DevOps, security, and developer workflow.
- `ai_agents`: AI agents, coding agents, evals, memory, tool calling, agent reliability, \
AI workflow automation, and AI app builders.
- `small_business`: small shops, restaurants, local services, tutors/coaching classes, \
travel agents, freelancers, and owner-operator admin workflows.
- `real_estate`: realtors, brokers, property managers, landlords, rentals, listings, \
lead follow-up, inspections, leases, and tenant workflows.
- `fitness`: gyms, studios, personal trainers, coaches, memberships, bookings, client \
plans, progress tracking, and payments.
- `health`: general patient/caregiver health admin, doctor visit prep, symptoms, meds, \
records, follow-up, chronic-care coordination, and clinic-facing workflows. Do NOT \
extract disease-specific support/community ideas such as PCOS/PMOS/PCOD support \
platforms unless the same pain clearly generalizes to broader health admin workflows.
- `fashion_beauty`: fashion boutiques, salons, beauty services, cosmetics, inventory, \
appointments, clients, returns, and creator commerce in fashion/beauty.
- `accounting_ca`: accountants, bookkeepers, CA firms, tax/GST, client document \
collection, month-end close, invoices, reconciliation, and finance ops for firms.
- `marketing_creator_agencies`: creators, marketers, small agencies, sponsorships, \
content planning, client approvals, reporting, analytics, and campaign operations.

If a post does not fit these categories, skip it. Do not create an `other` category.

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
- IMPORTANT: do NOT let AI/dev-tooling topics crowd out everything else. If a batch has \
real small business, real estate, fitness, health, fashion/beauty, accounting/CA, or \
marketing/creator/agency pain, extract it too.

What to extract:
- Be strict but keep category coverage: return the strongest 1-4 pain points per batch \
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
- category must be exactly one of: {_CATS}. Never return any other category name.

Scoring (1-5 — calibrate honestly; most things are 2-3, reserve 5):
- pain: 1 = mild annoyance, 5 = blocks real work / felt daily.
- frequency: 1 = one mention, 5 = echoed across many posts/comments.
- buildability: 1 = needs a huge moat or scale, 5 = a small team could ship a wedge in weeks.
- market_signal: 1 = no sign anyone'd pay/adopt, 5 = budget/adoption pressure, paid \
workarounds, switching intent, compliance risk, or direct purchasing language.
- personal_interest: fit with the user's interests: {_INTERESTS}."""


def extract_pain_points(items: list[SourceItem], batch_size: int = 15) -> list[PainPoint]:
    def extract_batch(batch: list[SourceItem], label: str) -> list[PainPoint]:
        try:
            parsed = _parse(
                _EXTRACT_SYS,
                "Extract pain points from these posts:\n\n" + _render_items(batch),
                Extraction,
                8000,
            )
            return parsed.pain_points if parsed else []
        except Exception as e:
            if _is_payload_too_large(e):
                if len(batch) > 1:
                    mid = max(1, len(batch) // 2)
                    print(
                        f"  ! batch {label} too large for fallback model; "
                        f"splitting {len(batch)} items into {mid}+{len(batch) - mid}"
                    )
                    return extract_batch(batch[:mid], f"{label}a") + extract_batch(
                        batch[mid:], f"{label}b"
                    )
                print(
                    f"  ! source item {batch[0].id} is too large for fallback model; skipping"
                )
                return []
            if _is_rate_limited(e):
                print(f"  ! batch {label} skipped after provider rate limits")
                return []
            raise

    if "github_models" in _provider_chain():
        batch_size = min(batch_size, 8)

    out: list[PainPoint] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        batch_no = start // batch_size + 1
        out.extend(extract_batch(batch, str(batch_no)))
        print(f"  - extracted from batch {batch_no}: {len(out)} total")

    from collections import Counter

    print(f"  - extracted by category: {dict(Counter(p.category for p in out))}")
    print(
        "  - extracted by source: "
        f"{dict(Counter(_source_from_id(sid) for p in out for sid in p.source_ids))}"
    )
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
already solves the SAME workflow for the SAME buyer, or can add the exact missing piece \
as a normal next feature, that is a RED FLAG.

Three tests that DECIDE conviction:
1. Big-company test: could a big platform or the leading existing tool add the EXACT \
workflow for the SAME narrow buyer as a simple feature? If yes → conviction LOW. But \
do NOT mark risk high just because big companies exist nearby. If the idea needs niche \
workflow knowledge, messy integrations, setup, compliance, service work, or a buyer the \
big tool does not focus on, risk is medium or low.
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
tool, set is_product=false and lower conviction. But set is_product=true when a small \
team could sell it as a focused workflow for a narrow group, even if bigger tools cover \
part of the job.
- If the context shows pricing or adoption numbers, CITE them in what_exists / \
demand_signal (e.g. "Portkey ~$49/mo", "Kafka is the default backbone"). If pricing \
truly isn't there, say "pricing unclear" in three words — don't write a long disclaimer.
- conviction: HIGH only if it passes all three tests above — a small specific niche, a \
boring/defensible problem, and NOT something a big company can just add. MEDIUM = real \
but broad, partly absorbable, or needs validation. LOW = a big company will likely add \
the exact workflow, it's a feature not a product, the market is dominated by giants for \
the same buyer, or the niche is too broad. BE STRICT, but do not default every researched \
lead to low. A niche boring problem with paying tools nearby is usually medium or high, \
not low.
- biggest_risk must be the honest main reason THIS specific idea fails — vary it, and \
name the specific big company or tool that would absorb it when that's the real risk.
- Set big_company_risk explicitly:
  low = hard for a big platform to absorb because it needs niche workflow, messy setup, \
service work, local context, or a buyer the platform ignores.
  medium = a big tool could add part of it, but niche execution still matters.
  high = Microsoft/GitHub/AWS/Google/OpenAI/Anthropic/Notion/etc. or the dominant tool \
already serves the same buyer and could add the exact workflow as a normal feature.
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
    "pcos",
    "pmos",
    "pcod",
    "pcos patients",
    "pcos support",
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
    providers = _provider_chain()
    if "github_models" in providers:
        cap = min(config.MAX_PAIN_POINTS, config.GITHUB_MODELS_MAX_PAIN_POINTS)
    elif "gemini" in providers:
        cap = min(config.MAX_PAIN_POINTS, config.GEMINI_MAX_PAIN_POINTS)
    else:
        cap = config.MAX_PAIN_POINTS
    ranked = sorted(pain_points, key=_composite, reverse=True)[:cap]
    payload = json.dumps([p.model_dump() for p in ranked])
    try:
        parsed = _parse(_DEDUPE_SYS, f"Pain points:\n{payload}", Deduped, 16000)
    except Exception as e:
        if _is_payload_too_large(e) and len(ranked) > 10:
            print("  ! dedupe payload too large; retrying with top 10 pain points")
            ranked = ranked[:10]
            payload = json.dumps([p.model_dump() for p in ranked])
            parsed = _parse(_DEDUPE_SYS, f"Pain points:\n{payload}", Deduped, 12000)
        elif _is_rate_limited(e):
            print("  ! dedupe skipped after provider rate limits; using top extracted pains")
            direct = [Opportunity(**p.model_dump(), composite=_composite(p)) for p in ranked[:10]]
            direct.sort(key=lambda o: o.composite, reverse=True)
            return direct
        else:
            raise
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
    try:
        thesis = _parse(_THESIS_SYS, user, MarketThesis, 4000)
    except Exception as e:
        if _is_rate_limited(e) or _is_payload_too_large(e):
            print(f"  ! thesis skipped for rate/payload limits: {lead.summary}")
            return None
        raise
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
    "reddit_web": "Reddit",
    "web": "Web",
}


def _source_markdown(sources: list[dict[str, str]]) -> str:
    links = []
    for src in sources:
        site = src.get("site") or "Source"
        url = src.get("url") or ""
        if url:
            links.append(f"[{site}]({url})")
    return ", ".join(links)


def _ensure_source_lines(markdown: str, payload_objs: list[dict]) -> str:
    """Make source links deterministic; models sometimes omit them on research leads."""
    for obj in payload_objs:
        title = obj.get("title")
        sources_md = _source_markdown(obj.get("sources", []))
        if not title or not sources_md:
            continue

        heading = f"### {title}"
        start = markdown.find(heading)
        if start < 0:
            continue
        next_start = markdown.find("\n### ", start + len(heading))
        end = next_start if next_start >= 0 else len(markdown)
        block = markdown[start:end]
        if "**Sources:**" in block:
            continue

        insert = f"\n**Sources:** {sources_md}\n"
        if block.endswith("\n\n"):
            replacement = block.rstrip() + insert + "\n\n"
        else:
            replacement = block.rstrip() + insert + "\n"
        markdown = markdown[:start] + replacement + markdown[end:]
    return markdown


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
Scanned {item_count} posts from Hacker News, Lobsters, Dev.to, GitHub, Reddit web \
results, and the wider web, then researched the top leads on the live web.

Buildability theses (each already grounded in web research):

{payload}

Write the brief in Markdown:
1. '## TL;DR' — 2-3 sentences on the strongest buildable idea today and why. If all \
theses are low-confidence, not standalone products, or high big-company risk, say there \
were no proven buildable ideas but there are research leads worth checking.
2. If there are theses with `is_product=true`, `big_company_risk` not high, and \
`conviction` high or medium, write '## Buildable Ideas' for those first.
3. For the remaining theses, write '## Research Leads' and make it clear they need \
validation before building.
For each thesis in either section, use one '### <title>' entry in this exact line order:
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
If there are zero theses, write only TL;DR and say the day was thin.
Keep it short and easy to read. Most confident ideas first. Never invent a URL."""
    try:
        brief = _complete(_BRIEF_SYS, user, 8000)
        return _ensure_source_lines(brief, payload_objs)
    except Exception as e:
        if _is_rate_limited(e) or _is_payload_too_large(e):
            print("  ! final brief writer hit provider limits; writing fallback brief")
            if not theses:
                return (
                    "## TL;DR\n"
                    "Problembrief found no completed theses today because the LLM provider "
                    "hit quota or rate limits during the run.\n\n"
                    "## Buildable Ideas\n"
                    "None.\n"
                )
            lines = [
                "## TL;DR",
                "Problembrief found research leads today, but the final writer hit provider "
                "quota or rate limits. Review these partial leads manually.",
                "",
                "## Research Leads",
            ]
            for t in theses:
                srcs, seen = [], set()
                for sid in t.source_ids:
                    u = id_to_url.get(sid)
                    if u and u not in seen:
                        seen.add(u)
                        srcs.append({"site": _SITE.get(id_to_source.get(sid, ""), "source"), "url": u})
                sources_md = _source_markdown(srcs[:5])
                lines.extend(
                    [
                        f"### {t.title}",
                        f"**Category:** {(t.category or '').replace('_', ' ').title()}",
                        f"**Problem:** {t.problem}",
                        f"**Who'd pay:** {t.buyer}",
                        f"**First build:** {t.mvp}",
                        f"**Confidence:** {t.conviction}. {t.biggest_risk}",
                        f"**Sources:** {sources_md}" if sources_md else "",
                        "",
                    ]
                )
            return "\n".join(lines).strip() + "\n"
        raise
