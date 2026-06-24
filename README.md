# Problembrief

Study real developer problems, every morning.

A daily research agent that scans developer communities, extracts repeated **pain
points**, scores them as buildable opportunities, and writes you a founder/builder
brief in Markdown.

This is **V1 — the thinnest useful slice**: Hacker News + Reddit → extract → dedupe →
score → brief to a file. No database, no dashboard yet. Get a brief you'd actually
read first; widen from there.

## Pipeline (LangGraph)

```
fetch_sources → extract_pain_points → dedupe_similar → generate_daily_brief → save_results
```

- **fetch_sources** — Hacker News (Algolia API), Lobsters (`hottest.json`), and Dev.to
  (`/api/articles`) — all no-auth and on by default. Reddit is **opt-in** and currently
  gated behind Reddit's Responsible Builder Policy, so it stays off unless you have
  approved API credentials. One failing source won't kill the run.
- **extract_pain_points** — Claude reads each batch and pulls concrete, buildable
  problems, each tagged with a category and 1–5 scores (pain, frequency,
  buildability, market signal, personal interest), citing its source posts.
- **dedupe_similar** — Claude merges near-duplicates into single opportunities.
- **generate_daily_brief** — a composite score is computed in code, and Claude writes
  a skimmable Markdown brief from the top opportunities.
- **save_results** — writes `briefs/YYYY-MM-DD.md`.

Extraction/scoring quality is the whole point, so it runs on **Claude Opus 4.8** with
structured outputs.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add your ANTHROPIC_API_KEY
```

## Run

```bash
python -m src.main
```

The brief prints to your terminal and saves to `briefs/`.

## Configure

Everything tunable lives in `config.py` (override via `.env`):

- `RADAR_SUBREDDITS` — which subreddits to scan
- `RADAR_INTERESTS` — biases the `personal_interest` score and the brief's framing
- `RADAR_MAX_PER_SOURCE` — posts pulled per source
- `RADAR_TOP_N` — opportunities included in the brief
- `WEIGHTS` — composite-score weighting (edit in `config.py`)

## Roadmap

- **V1.x** — pull HN/Reddit comments (where the real pain hides), add Product Hunt +
  GitHub trending, persist runs to Supabase.
- **V2** — wrap as an API; deliver the brief to Telegram / email / Notion / Slack on a
  9 AM cron. Add a dashboard with save / dismiss / mark-useful.

## Notes

- Reddit's public JSON is rate-limited; if a subreddit gets skipped, that's why.
- A daily run on Opus 4.8 over ~150 posts is a few cents to low dollars depending on
  volume; lower `RADAR_MAX_PER_SOURCE` or batch sizes to trim cost.
