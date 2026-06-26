"""Central config for Problembrief. Reads .env, exposes plain values."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Provider & model ----------------------------------------------------
# Backend LLM: "anthropic" (default) or "openai". Switch with RADAR_PROVIDER=openai
# when you're low on one provider's credits.
PROVIDER = os.getenv("RADAR_PROVIDER", "anthropic").lower()

# Anthropic model (used when PROVIDER=anthropic). Quality is the whole point, so
# default to the most capable Claude model.
MODEL = os.getenv("RADAR_MODEL", "claude-opus-4-8")

# OpenAI model + key (used when RADAR_PROVIDER=openai).
OPENAI_MODEL = os.getenv("RADAR_OPENAI_MODEL", "gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# --- Sources -------------------------------------------------------------
# How many items to pull from each source (HN, Lobsters, Dev.to, GitHub).
MAX_PER_SOURCE = int(os.getenv("RADAR_MAX_PER_SOURCE", "25"))

# Comment enrichment: pull discussion from the busiest threads (where real pain
# shows — agreement, workarounds, "is there a way to…"). Costs extra HTTP requests.
FETCH_COMMENTS = os.getenv("RADAR_FETCH_COMMENTS", "1") not in ("0", "false", "False")
COMMENTS_MAX_THREADS = int(os.getenv("RADAR_COMMENTS_MAX_THREADS", "10"))  # per source
COMMENTS_PER_THREAD = int(os.getenv("RADAR_COMMENTS_PER_THREAD", "6"))

# GitHub Issues search runs unauthenticated, but a free token raises the rate
# limit (10 -> 30 search req/min) and avoids 403s. Optional.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Pain-signal queries for the GitHub issue search (one source item per result).
# Override with RADAR_GITHUB_QUERIES (semicolon-separated).
GITHUB_QUERIES = [
    q.strip()
    for q in os.getenv(
        "RADAR_GITHUB_QUERIES",
        '"feature request" in:title type:issue state:open comments:>3'
        ';"is there a way to" in:title type:issue state:open comments:>2',
    ).split(";")
    if q.strip()
]

# --- Personalization -----------------------------------------------------
# Used to bias the "personal_interest" score and the brief's framing.
INTERESTS = [
    s.strip()
    for s in os.getenv(
        "RADAR_INTERESTS",
        "AI agents,developer tooling,automation,APIs,DX",
    ).split(",")
    if s.strip()
]

CATEGORIES = [
    "ai_agents",
    "devtools",
    "dx",
    "automation",
    "apis_sdks",
    "databases",
    "creator_tools",
    "other",
]

# --- Scoring weights (composite = weighted sum of the 1-5 sub-scores) -----
WEIGHTS = {
    "pain": 0.30,
    "frequency": 0.25,
    "buildability": 0.20,
    "market_signal": 0.15,
    "personal_interest": 0.10,
}

# Cap how many (highest-scoring) pain points get sent to the dedupe step. Keeps the
# model's output under its token budget and focuses on the strongest signals.
MAX_PAIN_POINTS = int(os.getenv("RADAR_MAX_PAIN_POINTS", "40"))

# How many opportunities make the brief.
TOP_N = int(os.getenv("RADAR_TOP_N", "8"))

# --- Output --------------------------------------------------------------
ROOT = Path(__file__).parent
BRIEFS_DIR = ROOT / "briefs"

# A descriptive User-Agent keeps the source APIs happy on unauthenticated reads.
USER_AGENT = "problembrief/0.1 (personal research tool)"

# --- Email delivery via Resend (optional) --------------------------------
# If RESEND_API_KEY is set, the brief is emailed after each run; otherwise skipped.
# The free tier needs no domain: send from the shared onboarding sender to your own
# Resend signup address. See README "Email setup".
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Problembrief <onboarding@resend.dev>")
EMAIL_TO = os.getenv("EMAIL_TO", "")  # your Resend account email (required to send)
