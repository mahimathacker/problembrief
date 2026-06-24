"""Central config for AI Builder Radar. Reads .env, exposes plain values."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Model ---------------------------------------------------------------
# Default to the most capable Claude model. The extraction/scoring quality is
# the whole point of this tool, so don't downgrade without a reason.
MODEL = os.getenv("RADAR_MODEL", "claude-opus-4-8")

# --- Sources -------------------------------------------------------------
SUBREDDITS = [
    s.strip()
    for s in os.getenv(
        "RADAR_SUBREDDITS",
        "devtools,programming,SaaS,startups,ExperiencedDevs,LocalLLaMA",
    ).split(",")
    if s.strip()
]

# How many items to pull from each source (HN front page + each subreddit).
MAX_PER_SOURCE = int(os.getenv("RADAR_MAX_PER_SOURCE", "25"))

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

# How many opportunities make the brief.
TOP_N = int(os.getenv("RADAR_TOP_N", "8"))

# --- Output --------------------------------------------------------------
ROOT = Path(__file__).parent
BRIEFS_DIR = ROOT / "briefs"

# A descriptive User-Agent keeps HN/Reddit happy on unauthenticated reads.
USER_AGENT = "problembrief/0.1 (personal research tool)"
