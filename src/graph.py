"""LangGraph pipeline: fetch -> extract -> dedupe -> enrich -> brief -> save."""
from __future__ import annotations

from datetime import date

from langgraph.graph import END, StateGraph

import config
from src import enrich, llm, sources, store
from src.schema import RadarState


def fetch_sources(state: RadarState) -> RadarState:
    print("[1/6] fetching sources…")
    items = sources.fetch_all()
    items = store.filter_unseen(items, config.DEDUP_DAYS)
    return {"raw_items": items}


def extract_pain_points(state: RadarState) -> RadarState:
    items = state.get("raw_items", [])
    print(f"[2/6] extracting pain points from {len(items)} posts…")
    return {"pain_points": llm.extract_pain_points(items)}


def dedupe_similar(state: RadarState) -> RadarState:
    pp = state.get("pain_points", [])
    raw = state.get("raw_items", [])
    print(f"[3/6] deduping {len(pp)} pain points…")
    return {"deduped": llm.dedupe(pp, raw)}


_BUILDER_CATEGORIES = {
    "ai_agents",
    "devtools",
    "dx",
    "automation",
    "apis_sdks",
    "databases",
    "web",
    "mobile",
    "data",
    "security",
}

_BUSINESS_CATEGORIES = {
    "fintech",
    "ecommerce",
    "healthtech",
    "marketing",
    "vertical_saas",
    "small_business",
    "creator_tools",
    "consumer",
}


def _add_diverse(chosen, leads, limit, per_category=2):
    counts = {}
    for o in chosen:
        c = o.category or "other"
        counts[c] = counts.get(c, 0) + 1
    for o in leads:
        if o in chosen:
            continue
        c = o.category or "other"
        if counts.get(c, 0) < per_category:
            chosen.append(o)
            counts[c] = counts.get(c, 0) + 1
        if len(chosen) >= limit:
            break


def _select_diverse(leads, n, per_category=2):
    """Pick top leads while reserving room for both builder/dev/AI and business pain."""
    chosen = []
    builder = [o for o in leads if (o.category or "other") in _BUILDER_CATEGORIES]
    business = [o for o in leads if (o.category or "other") in _BUSINESS_CATEGORIES]

    if builder:
        chosen.append(builder[0])
    if business and len(chosen) < n:
        chosen.append(business[0])

    _add_diverse(chosen, leads, n, per_category)
    if len(chosen) >= n:
        return chosen[:n]
    for o in leads:  # if caps left us short, fill the rest by score
        if o not in chosen:
            chosen.append(o)
            if len(chosen) >= n:
                break
    return chosen


def _lead_sources(lead, id_to_source):
    return {id_to_source.get(sid, "") for sid in lead.source_ids}


def _ensure_source_slot(chosen, leads, source, id_to_source, limit):
    """Reserve one enrichment slot for an important source if it produced a real lead."""
    if not leads or not any(source in _lead_sources(o, id_to_source) for o in leads):
        return chosen
    if any(source in _lead_sources(o, id_to_source) for o in chosen):
        return chosen

    source_leads = [o for o in leads if source in _lead_sources(o, id_to_source)]
    if not source_leads:
        return chosen
    pick = source_leads[0]
    if pick in chosen:
        return chosen
    if len(chosen) < limit:
        chosen.append(pick)
    else:
        chosen[-1] = pick
    return chosen


def enrich_leads(state: RadarState) -> RadarState:
    raw = state.get("raw_items", [])
    id_to_source = {it.id: it.source for it in raw}
    all_leads = state.get("deduped", [])
    leads = _select_diverse(all_leads, config.ENRICH_TOP_N)
    leads = _ensure_source_slot(leads, all_leads, "reddit_web", id_to_source, config.ENRICH_TOP_N)
    print(f"[4/6] enriching {len(leads)} leads with live market research…")
    if leads:
        cats = ", ".join(o.category or "other" for o in leads)
        print(f"  - selected categories: {cats}")
        source_names = [
            "+".join(sorted(s for s in _lead_sources(o, id_to_source) if s)) or "unknown"
            for o in leads
        ]
        print(f"  - selected sources: {', '.join(source_names)}")
    theses = []
    for lead in leads:
        context = enrich.market_context(lead.summary)
        thesis = llm.write_thesis(lead, context)
        if thesis:
            theses.append(thesis)
            print(f"  - thesis: {thesis.title} (conviction={thesis.conviction})")
    theses = _filter_and_rank_theses(theses)
    return {"theses": theses}


def _thesis_score(t) -> int:
    conviction = (t.conviction or "").lower()
    conviction_score = {"high": 3, "medium": 2, "low": 1}.get(conviction, 1)
    risk_penalty = {"high": 3, "medium": 1, "low": 0}.get(
        (t.big_company_risk or "").lower(), 1
    )
    return conviction_score * 3 + t.niche_score + t.boring_score - risk_penalty


def _passes_boring_niche_tests(t) -> bool:
    risk = (t.big_company_risk or "").lower()
    if not t.is_product:
        return False
    if risk == "high":
        return False
    if t.niche_score < 3:
        return False
    return True


def _fallback_research_lead(t) -> bool:
    """Keep a few low-confidence leads when the strict buildable bar finds nothing."""
    conviction = (t.conviction or "").lower()
    if t.niche_score < 3:
        return False
    if t.boring_score < 3:
        return False
    return conviction in {"low", "medium", "high"}


def _filter_and_rank_theses(theses):
    kept, dropped = [], []
    for t in theses:
        (kept if _passes_boring_niche_tests(t) else dropped).append(t)
    for t in dropped:
        print(
            "  - dropped thesis: "
            f"{t.title} (big_company_risk={t.big_company_risk}, "
            f"niche={t.niche_score}, boring={t.boring_score}, product={t.is_product})"
        )
    kept.sort(key=_thesis_score, reverse=True)
    if not kept and theses:
        fallback = [t for t in theses if _fallback_research_lead(t)]
        fallback.sort(key=_thesis_score, reverse=True)
        kept = fallback[: min(3, len(fallback))]
        if kept:
            print(f"  - strict gate kept 0; keeping {len(kept)} research leads")
    print(f"  - final theses kept after boring/niche tests: {len(kept)}")
    return kept


def generate_daily_brief(state: RadarState) -> RadarState:
    theses = state.get("theses", [])
    raw = state.get("raw_items", [])
    print(f"[5/6] writing brief from {len(theses)} theses…")
    today = date.today().isoformat()
    id_to_url = {it.id: it.url for it in raw}
    id_to_source = {it.id: it.source for it in raw}
    brief = llm.write_brief(theses, today, len(raw), id_to_url, id_to_source)
    return {"brief_markdown": brief}


def save_results(state: RadarState) -> RadarState:
    print("[6/6] saving…")
    config.BRIEFS_DIR.mkdir(exist_ok=True)
    path = config.BRIEFS_DIR / f"{date.today().isoformat()}.md"
    path.write_text(state.get("brief_markdown", ""), encoding="utf-8")

    # Remember what we surfaced today so it won't repeat for DEDUP_DAYS.
    raw = state.get("raw_items", [])
    id_to_url = {it.id: it.url for it in raw}
    store.record(state.get("theses", []), id_to_url, config.SEEN_RETENTION_DAYS)

    return {"brief_path": str(path)}


def build_graph():
    g = StateGraph(RadarState)
    g.add_node("fetch_sources", fetch_sources)
    g.add_node("extract_pain_points", extract_pain_points)
    g.add_node("dedupe_similar", dedupe_similar)
    g.add_node("enrich_leads", enrich_leads)
    g.add_node("generate_daily_brief", generate_daily_brief)
    g.add_node("save_results", save_results)

    g.set_entry_point("fetch_sources")
    g.add_edge("fetch_sources", "extract_pain_points")
    g.add_edge("extract_pain_points", "dedupe_similar")
    g.add_edge("dedupe_similar", "enrich_leads")
    g.add_edge("enrich_leads", "generate_daily_brief")
    g.add_edge("generate_daily_brief", "save_results")
    g.add_edge("save_results", END)
    return g.compile()
