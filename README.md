# Problembrief

Study real developer problems, every morning.

A daily research agent that scans developer communities, extracts repeated **pain
points**, scores them as buildable opportunities, and writes you a founder/builder
brief in Markdown.

This is **V1 — the thinnest useful slice**: fetch → extract → dedupe → score → brief
to a file. No database, no dashboard yet. Get a brief you'd actually read first; widen
from there.

## Pipeline (LangGraph)

```
fetch_sources → extract_pain_points → dedupe_similar → generate_daily_brief → save_results
```

- **fetch_sources** — Hacker News (Algolia), Lobsters (`hottest.json`), Dev.to
  (`/api/articles`), and GitHub Issues (Search API, querying feature-requests and
  "is there a way to…" issues created in the last ~30 days, by reactions) — all no-auth
  and on by default. The busiest HN + GitHub threads are enriched with their **top
  comments**, where the real pain shows. Then a **cross-run dedup** drops anything
  already surfaced in a brief within the last `RADAR_DEDUP_DAYS` (default 7) — so the
  same problems don't repeat day after day. A free `GITHUB_TOKEN` just raises GitHub's
  rate limit. One failing source won't kill the run.
- **extract_pain_points** — Claude reads each batch and pulls concrete, buildable
  problems, each tagged with a category and 1–5 scores (pain, frequency,
  buildability, market signal, personal interest), citing its source posts.
- **dedupe_similar** — Claude merges near-duplicates into single opportunities.
- **generate_daily_brief** — a composite score is computed in code, and Claude writes
  a skimmable Markdown brief from the top opportunities.
- **save_results** — writes `briefs/YYYY-MM-DD.md` and records the surfaced
  opportunities' source URLs to `state/seen.json` (the dedup store). On the daily cron,
  both are committed back to the repo — a lightweight, service-free "database".

Extraction/scoring quality is the whole point, so it defaults to **Claude Opus 4.8**
with structured outputs. To switch backends when you're low on credits, set
`RADAR_PROVIDER=openai` and `OPENAI_API_KEY` (optionally `RADAR_OPENAI_MODEL`, default
`gpt-4o`) — the pipeline is provider-agnostic.

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

- `RADAR_INTERESTS` — biases the `personal_interest` score and the brief's framing
- `RADAR_MAX_PER_SOURCE` — posts pulled per source
- `RADAR_GITHUB_QUERIES` — what GitHub issue searches to run (semicolon-separated)
- `RADAR_GITHUB_RECENCY_DAYS` — only pull GitHub issues created in the last N days (default 30)
- `RADAR_DEDUP_DAYS` — don't resurface a problem within N days (default 7)
- `RADAR_TOP_N` — opportunities included in the brief
- `WEIGHTS` — composite-score weighting (edit in `config.py`)

## Email setup (optional)

Get the brief in your inbox after each run, via [Resend](https://resend.com) (a
transactional email service — **not** Google/Gmail, nothing to set up in Google Cloud):

1. Sign up at <https://resend.com> (free — 100 emails/day).
2. **API Keys → Create API Key**, copy the `re_...` value.
3. Add to `.env`:
   ```
   RESEND_API_KEY=re_...
   EMAIL_TO=your-resend-signup-email@example.com
   ```
   On the free tier (no domain) you can only send to your **Resend signup address**,
   from the shared `onboarding@resend.dev` sender. Verify a domain later to send
   anywhere and from your own address.

If `RESEND_API_KEY` is unset, delivery is just skipped.

## Automate (daily, in the cloud)

[`.github/workflows/daily.yml`](.github/workflows/daily.yml) runs the brief on a cron
via GitHub Actions — no laptop required. In your repo: **Settings → Secrets and
variables → Actions** add `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, and `EMAIL_TO`
(`GITHUB_TOKEN` is provided automatically). Adjust the cron time in the workflow (it's
UTC). Use the **Actions** tab → *Run workflow* to test it on demand.

## Roadmap

- **V1.x** — add GitHub Discussions + Product Hunt, persist runs to Supabase.
- **V2** — wrap as an API; deliver the brief to Telegram / email / Notion / Slack on a
  9 AM cron. Add a dashboard with save / dismiss / mark-useful.

## Notes

- A daily run on Opus 4.8 over ~150 posts is a few cents to low dollars depending on
  volume; lower `RADAR_MAX_PER_SOURCE` or batch sizes to trim cost.
