"""LangGraph pipeline: fetch -> extract -> dedupe -> brief -> save."""
from __future__ import annotations

from datetime import date

from langgraph.graph import END, StateGraph

import config
from src import llm, sources
from src.schema import RadarState


def fetch_sources(state: RadarState) -> RadarState:
    print("[1/5] fetching sources…")
    return {"raw_items": sources.fetch_all()}


def extract_pain_points(state: RadarState) -> RadarState:
    items = state.get("raw_items", [])
    print(f"[2/5] extracting pain points from {len(items)} posts…")
    return {"pain_points": llm.extract_pain_points(items)}


def dedupe_similar(state: RadarState) -> RadarState:
    pp = state.get("pain_points", [])
    print(f"[3/5] deduping {len(pp)} pain points…")
    return {"deduped": llm.dedupe(pp)}


def generate_daily_brief(state: RadarState) -> RadarState:
    opps = state.get("deduped", [])
    raw = state.get("raw_items", [])
    print(f"[4/5] writing brief from {len(opps)} opportunities…")
    today = date.today().isoformat()
    id_to_url = {it.id: it.url for it in raw}
    brief = llm.write_brief(opps, today, len(raw), id_to_url)
    return {"brief_markdown": brief}


def save_results(state: RadarState) -> RadarState:
    print("[5/5] saving…")
    config.BRIEFS_DIR.mkdir(exist_ok=True)
    path = config.BRIEFS_DIR / f"{date.today().isoformat()}.md"
    path.write_text(state.get("brief_markdown", ""), encoding="utf-8")
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
