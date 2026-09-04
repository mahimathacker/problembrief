"""Pydantic models (for Claude structured outputs) and the LangGraph state."""
from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    """One fetched post, normalized across sources."""

    id: str  # short stable id, e.g. "hn-3", "github-0-7"
    source: str  # hackernews | lobsters | devto | github
    title: str
    text: str = ""
    url: str = ""
    points: int = 0
    num_comments: int = 0


class PainPoint(BaseModel):
    """A concrete, buildable pain point extracted from one or more posts."""

    summary: str = Field(description="One sentence: the problem, stated plainly.")
    category: str = Field(description="One of the configured categories.")
    evidence: str = Field(description="A short quote or paraphrase showing the pain.")
    current_workaround: str = Field(
        default="",
        description="What users do today instead, if visible in the source.",
    )
    manual_steps: list[str] = Field(
        default_factory=list,
        description="Repeated manual steps in the current workflow, if visible.",
    )
    user_role: str = Field(default="", description="The person doing or feeling the work.")
    buyer_role: str = Field(default="", description="The person likely to pay or approve.")
    source_ids: list[str] = Field(description="ids of the posts this came from.")
    pain: int = Field(description="1-5: how acute/frequent the frustration is.")
    frequency: int = Field(description="1-5: how often this comes up across posts.")
    buildability: int = Field(description="1-5: how feasible for a small team to ship.")
    market_signal: int = Field(description="1-5: evidence people would pay/adopt.")
    personal_interest: int = Field(description="1-5: fit with the user's interests.")


class Extraction(BaseModel):
    """Wrapper so structured output returns a list."""

    pain_points: list[PainPoint]


class Opportunity(PainPoint):
    """A merged pain point after dedupe, plus a composite score added in code."""

    composite: float = 0.0


class Deduped(BaseModel):
    opportunities: list[Opportunity]


class OpportunityDecision(BaseModel):
    """A critic pass decision for one deduped opportunity."""

    index: int = Field(description="Zero-based index of the opportunity being reviewed.")
    keep: bool = Field(description="True only if this is brief-worthy.")
    reason: str = Field(description="Short reason for keep/reject.")


class OpportunityReview(BaseModel):
    decisions: list[OpportunityDecision]


class MarketThesis(BaseModel):
    """A grounded buildability thesis for one lead, written after live web research."""

    title: str = Field(description="Short, concrete name for the opportunity.")
    category: str = Field(default="", description="Category tag (set from the lead).")
    problem: str = Field(description="The pain, in one or two plain sentences.")
    what_people_do_today: str = Field(
        default="",
        description="The current workaround or manual workflow.",
    )
    job_software_could_take_over: str = Field(
        default="",
        description="The broader operational job software could own end-to-end.",
    )
    what_still_needs_human: str = Field(
        default="",
        description="The judgment, exception handling, or relationship work humans keep.",
    )
    what_exists: list[str] = Field(
        description="Existing tools/competitors with pricing where known; empty if greenfield."
    )
    demand_signal: str = Field(
        description="Evidence of real, repeated demand or willingness to pay (or its absence)."
    )
    buyer: str = Field(description="The specific user/buyer who would adopt or pay.")
    is_product: bool = Field(
        description="True if a standalone product/SaaS; false if really a feature of an existing tool."
    )
    wedge: str = Field(description="The differentiated angle — where a new entrant wins.")
    mvp: str = Field(description="The first concrete thing to build to test it.")
    conviction: str = Field(description="high | medium | low — grounded in the evidence.")
    biggest_risk: str = Field(description="The main reason this could fail.")
    why_now: str = Field(
        default="",
        description="What changed recently that makes this newly painful or buildable.",
    )
    big_company_risk: str = Field(
        default="unknown",
        description="low | medium | high — risk that a big platform or dominant tool adds it.",
    )
    niche_score: int = Field(
        default=3,
        description="1-5: 5 means a tiny specific ICP that cannot be segmented much further.",
    )
    boring_score: int = Field(
        default=3,
        description="1-5: 5 means boring/service-like/unsexy work with less builder competition.",
    )
    source_ids: list[str] = Field(default_factory=list, description="Originating post ids.")


class RadarState(TypedDict, total=False):
    raw_items: list[SourceItem]
    pain_points: list[PainPoint]
    deduped: list[Opportunity]
    research_leads: list[Opportunity]
    theses: list[MarketThesis]
    brief_markdown: str
    brief_path: str
