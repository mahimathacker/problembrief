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
    source_ids: list[str] = Field(description="ids of the posts this came from.")
    pain: int = Field(ge=1, le=5, description="How acute/frequent the frustration is.")
    frequency: int = Field(ge=1, le=5, description="How often this comes up across posts.")
    buildability: int = Field(ge=1, le=5, description="How feasible for a small team to ship.")
    market_signal: int = Field(ge=1, le=5, description="Evidence people would pay/adopt.")
    personal_interest: int = Field(ge=1, le=5, description="Fit with the user's interests.")


class Extraction(BaseModel):
    """Wrapper so structured output returns a list."""

    pain_points: list[PainPoint]


class Opportunity(PainPoint):
    """A merged pain point after dedupe, plus a composite score added in code."""

    composite: float = 0.0


class Deduped(BaseModel):
    opportunities: list[Opportunity]


class RadarState(TypedDict, total=False):
    raw_items: list[SourceItem]
    pain_points: list[PainPoint]
    deduped: list[Opportunity]
    brief_markdown: str
    brief_path: str
