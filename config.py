"""Central config for Problembrief. Reads .env, exposes plain values."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Provider & model ----------------------------------------------------
# Backend LLM: "anthropic" (default), "openai", "gemini", or "github_models".
# Switch providers when you're low on one provider's credits.
PROVIDER = os.getenv("RADAR_PROVIDER", "anthropic").strip().lower()
FALLBACK_PROVIDERS = [
    p.strip().lower()
    for p in os.getenv("RADAR_FALLBACK_PROVIDERS", "").split(",")
    if p.strip()
]

# Anthropic model (used when PROVIDER=anthropic). Quality is the whole point, so
# default to the most capable Claude model.
MODEL = os.getenv("RADAR_MODEL", "claude-opus-4-8").strip()

# OpenAI model + key (used when RADAR_PROVIDER=openai).
OPENAI_MODEL = os.getenv("RADAR_OPENAI_MODEL", "gpt-5.5").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

# Gemini model + key (used when RADAR_PROVIDER=gemini). Uses Google's REST API via
# httpx, so no separate SDK is required.
GEMINI_MODEL = os.getenv("RADAR_GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# GitHub Models (used when RADAR_PROVIDER=github_models or as a fallback).
# In GitHub Actions this can use the built-in GITHUB_TOKEN if the workflow grants
# `models: read`.
GITHUB_MODELS_MODEL = os.getenv("RADAR_GITHUB_MODEL", "openai/gpt-4o-mini").strip()
GITHUB_MODELS_API_VERSION = os.getenv("RADAR_GITHUB_API_VERSION", "2026-03-10").strip()
GITHUB_MODELS_OWNER = os.getenv("RADAR_GITHUB_OWNER", "").strip() or os.getenv(
    "GITHUB_REPOSITORY_OWNER", ""
).strip()
GITHUB_MODELS_ENDPOINT = os.getenv("RADAR_GITHUB_ENDPOINT", "").strip()
GITHUB_MODELS_TOKEN = (
    os.getenv("GITHUB_MODELS_TOKEN", "").strip()
    or os.getenv("GITHUB_TOKEN", "").strip()
)

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

# Pool of pain-signal queries for the GitHub issue search. A rotating subset runs
# each day (see GITHUB_QUERIES_PER_DAY) so the brief doesn't keep pulling the same
# cluster. Override the whole pool with RADAR_GITHUB_QUERIES (semicolon-separated).
GITHUB_QUERIES = [
    q.strip()
    for q in os.getenv(
        "RADAR_GITHUB_QUERIES",
        ";".join(
            [
                '"feature request" in:title type:issue state:open comments:>3',
                '"is there a way to" in:title type:issue state:open comments:>2',
                '"would be great if" in:title type:issue state:open comments:>2',
                '"any plans to" in:title type:issue state:open comments:>2',
                '"alternative to" in:title type:issue state:open comments:>2',
                '"frustrating" in:body type:issue state:open comments:>3',
                '"workaround for" in:title type:issue state:open comments:>3',
                '"no good way to" in:body type:issue state:open comments:>2',
            ]
        ),
    ).split(";")
    if q.strip()
]
# How many of the pool's queries to run per day (rotated by date).
GITHUB_QUERIES_PER_DAY = int(os.getenv("RADAR_GITHUB_QUERIES_PER_DAY", "3"))

# Only pull GitHub issues created within this many days, so the search surfaces
# fresh pain instead of the same all-time-most-reacted issues every day.
GITHUB_RECENCY_DAYS = int(os.getenv("RADAR_GITHUB_RECENCY_DAYS", "30"))

# Hacker News is searched for pain/complaint phrases (Ask HN, "is there a way to…",
# "alternative to…") instead of the front page — this surfaces real problems and
# gripes about *existing launched products*, not launch/news headlines. A rotating
# subset of phrases runs each day.
HN_PAIN_PHRASES = [
    p.strip()
    for p in os.getenv(
        "RADAR_HN_PHRASES",
        ";".join(
            [
                "is there a way to",
                "is there a better",
                "alternative to",
                "I wish there was",
                "frustrated with",
                "anyone know a tool",
                "why is there no",
                "does anyone have a good",
            ]
        ),
    ).split(";")
    if p.strip()
]
HN_PHRASES_PER_DAY = int(os.getenv("RADAR_HN_PHRASES_PER_DAY", "4"))
HN_RECENCY_DAYS = int(os.getenv("RADAR_HN_RECENCY_DAYS", "21"))

# --- Market enrichment (Tavily web search) -------------------------------
# Each top lead is researched on the live web (existing tools, pricing, demand)
# before the brief writes a grounded buildability thesis — turning a raw pain into
# a product thesis. Without a key, enrichment is skipped and theses are ungrounded
# (lower conviction). Free key: https://tavily.com
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
ENRICH_TOP_N = int(os.getenv("RADAR_ENRICH_TOP_N", "8"))
# Extra pricing searches per enriched lead. Higher means better pricing coverage but
# more Tavily usage.
PRICING_LOOKUPS_PER_LEAD = int(os.getenv("RADAR_PRICING_LOOKUPS_PER_LEAD", "4"))

# Beyond dev forums: discover real-world pain in a small set of categories. A rotating
# subset runs each day. Needs TAVILY_API_KEY; skipped without it.
DISCOVERY_QUERIES = [
    q.strip()
    for q in os.getenv(
        "RADAR_DISCOVERY_QUERIES",
        ";".join(
            [
                "small business owners frustrated with their current software",
                "small shop owners frustrated with inventory billing and WhatsApp orders",
                "real estate agents complain about CRM lead follow up listing software",
                "property managers and landlords software frustrations",
                "gym owners frustrated with booking membership software",
                "personal trainers frustrated with client tracking payments scheduling",
                "patients frustrated with doctor visit preparation symptom tracking",
                "caregivers frustrated with medication tracking appointments and health records",
                "patients with chronic conditions frustrated with medical records and follow up",
                "salon owners frustrated with booking inventory client follow up software",
                "beauty creators frustrated with brand deals invoicing content planning",
                "fashion boutique owners frustrated with inventory orders returns software",
                "accountants and bookkeepers frustrated with their software",
                "CA firms frustrated with client document collection GST tax workflows",
                "marketing agencies frustrated with client approvals reporting project management",
                "creators frustrated with sponsorship invoicing content planning and analytics",
                "non-AI developer tools people are frustrated with",
                "AI agent builders frustrated with evals memory tool calling reliability",
            ]
        ),
    ).split(";")
    if q.strip()
]
DISCOVERY_PER_DAY = int(os.getenv("RADAR_DISCOVERY_PER_DAY", "5"))

# Reddit via public web search, not the Reddit API. This is a temporary discovery
# source while API access is pending. Keep it narrow, pain-oriented, and low-volume.
REDDIT_WEB_QUERIES = [
    q.strip()
    for q in os.getenv(
        "RADAR_REDDIT_WEB_QUERIES",
        ";".join(
            [
                "site:reddit.com/r/smallbusiness frustrated software",
                'site:reddit.com/r/smallbusiness "does anyone know a tool"',
                'site:reddit.com/r/smallbusiness "manual" "software"',
                'site:reddit.com/r/smallbusiness "wish there was"',
                'site:reddit.com/r/realtors "frustrated" "software"',
                'site:reddit.com/r/realestate "property management software"',
                'site:reddit.com/r/personaltraining "client" "software"',
                'site:reddit.com/r/ChronicIllness "doctor" "tracking"',
                'site:reddit.com/r/CaregiverSupport "appointments" "medication"',
                'site:reddit.com/r/salons "booking software"',
                'site:reddit.com/r/Bookkeeping "client documents"',
                'site:reddit.com/r/marketing "client approval"',
                'site:reddit.com/r/SaaS "is there a tool"',
                'site:reddit.com/r/webdev "I hate"',
                'site:reddit.com/r/webdev "is there a way to"',
                'site:reddit.com/r/LocalLLaMA "agent" "frustrated"',
            ]
        ),
    ).split(";")
    if q.strip()
]
REDDIT_WEB_PER_DAY = int(os.getenv("RADAR_REDDIT_WEB_PER_DAY", "3"))
REDDIT_WEB_RESULTS_PER_QUERY = int(os.getenv("RADAR_REDDIT_WEB_RESULTS_PER_QUERY", "5"))
REDDIT_WEB_RECENCY_MONTHS = int(os.getenv("RADAR_REDDIT_WEB_RECENCY_MONTHS", "18"))

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
    # focused v1 categories
    "devtools",
    "ai_agents",
    "small_business",
    "real_estate",
    "fitness",
    "health",
    "fashion_beauty",
    "accounting_ca",
    "marketing_creator_agencies",
]

# --- Scoring weights (composite = weighted sum of the 1-5 sub-scores) -----
WEIGHTS = {
    "pain": 0.30,
    "frequency": 0.20,
    "buildability": 0.10,
    "market_signal": 0.30,
    "personal_interest": 0.10,
}

# Cap how many (highest-scoring) pain points get sent to the dedupe step. Keeps the
# model's output under its token budget and focuses on the strongest signals.
MAX_PAIN_POINTS = int(os.getenv("RADAR_MAX_PAIN_POINTS", "40"))
GEMINI_MAX_PAIN_POINTS = int(os.getenv("RADAR_GEMINI_MAX_PAIN_POINTS", "30"))
GITHUB_MODELS_MAX_PAIN_POINTS = int(os.getenv("RADAR_GITHUB_MAX_PAIN_POINTS", "24"))

# How many opportunities make the brief.
TOP_N = int(os.getenv("RADAR_TOP_N", "5"))

# --- Output --------------------------------------------------------------
ROOT = Path(__file__).parent
BRIEFS_DIR = ROOT / "briefs"

# --- Persistence / cross-run dedup ---------------------------------------
STATE_DIR = ROOT / "state"
SEEN_PATH = STATE_DIR / "seen.json"
# Skip source items already surfaced in a brief within this many days — this is
# what stops the same problems from repeating day after day.
DEDUP_DAYS = int(os.getenv("RADAR_DEDUP_DAYS", "7"))
# Forget seen URLs older than this, so seen.json doesn't grow forever.
SEEN_RETENTION_DAYS = int(os.getenv("RADAR_SEEN_RETENTION_DAYS", "60"))

# A descriptive User-Agent keeps the source APIs happy on unauthenticated reads.
USER_AGENT = "problembrief/0.1 (personal research tool)"

# --- Email delivery via Resend (optional) --------------------------------
# If RESEND_API_KEY is set, the brief is emailed after each run; otherwise skipped.
# The free tier needs no domain: send from the shared onboarding sender to your own
# Resend signup address. See README "Email setup".
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Problembrief <onboarding@resend.dev>")
EMAIL_TO = os.getenv("EMAIL_TO", "")  # your Resend account email (required to send)
