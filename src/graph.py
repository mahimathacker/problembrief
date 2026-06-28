"""LangGraph pipeline: fetch -> extract -> dedupe -> brief -> save."""
from __future__ import annotations

from datetime import date

from langgraph.graph import END, StateGraph

import config
from src import llm, sources, store
from src.schema import RadarState


def fetch_sources(state: RadarState) -> RadarState:
    print("[1/5] fetching sources…")
    items = sources.fetch_all()
    items = store.filter_unseen(items, config.DEDUP_DAYS)
    return {"raw_items": items}


def extract_pain_points(state: RadarState) -> RadarState:
    items = state.get("raw_items", [])
    print(f"[2/5] extracting pain points from {len(items)} posts…")
    return {"pain_points": llm.extract_pain_points(items)}


def dedupe_similar(state: RadarState) -> RadarState:
    pp = state.get("pain_points", [])
    raw = state.get("raw_items", [])
    print(f"[3/5] deduping {len(pp)} pain points…")
    opps, leads = llm.dedupe(pp, raw)
    return {"deduped": opps, "research_leads": leads}


def generate_daily_brief(state: RadarState) -> RadarState:
    opps = state.get("deduped", [])
    leads = state.get("research_leads", [])
    raw = state.get("raw_items", [])
    print(f"[4/5] writing brief from {len(opps)} opportunities and {len(leads)} leads…")
    today = date.today().isoformat()
    id_to_url = {it.id: it.url for it in raw}
    id_to_source = {it.id: it.source for it in raw}
    brief = llm.write_brief(opps, today, len(raw), id_to_url, id_to_source, leads)
    return {"brief_markdown": brief}


def save_results(state: RadarState) -> RadarState:
    print("[5/5] saving…")
    config.BRIEFS_DIR.mkdir(exist_ok=True)
    path = config.BRIEFS_DIR / f"{date.today().isoformat()}.md"
    path.write_text(state.get("brief_markdown", ""), encoding="utf-8")

    # Remember what we surfaced today so it won't repeat for DEDUP_DAYS.
    raw = state.get("raw_items", [])
    id_to_url = {it.id: it.url for it in raw}
    surfaced = state.get("deduped", [])[: config.TOP_N]
    store.record(surfaced, id_to_url, config.SEEN_RETENTION_DAYS)

    return {"brief_path": str(path)}


def build_graph():
    g = StateGraph(RadarState)
    g.add_node("fetch_sources", fetch_sources)
    g.add_node("extract_pain_points", extract_pain_points)
    g.add_node("dedupe_similar", dedupe_similar)
    g.add_node("generate_daily_brief", generate_daily_brief)
    g.add_node("save_results", save_results)

    g.set_entry_point("fetch_sources")
    g.add_edge("fetch_sources", "extract_pain_points")
    g.add_edge("extract_pain_points", "dedupe_similar")
    g.add_edge("dedupe_similar", "generate_daily_brief")
    g.add_edge("generate_daily_brief", "save_results")
    g.add_edge("save_results", END)
    return g.compile()
