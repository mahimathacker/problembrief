# Problembrief

Find real problems worth solving, every morning.

Problembrief is a private research agent for builders. It scans public discussion
sources, extracts repeated **pain points**, checks whether they look like buildable
opportunities, and writes a structured founder/builder brief in Markdown.

The goal is simple: help a builder find real problems from public signals instead of
starting from random ideas.

This is **V1 — the thinnest useful slice**: fetch → extract → dedupe → score → brief
to a file. No database, no dashboard yet. Get a brief you'd actually read first; widen
from there.

## Responsible Data Use

Problembrief is designed for low-volume research summaries, not bulk collection or
republication.

- It reads selected public sources only.
- It keeps brief metadata such as title, URL, source, score/comment counts, and short
  excerpts or summaries when needed for evidence.
- It links back to original sources instead of copying full posts or comments.
- It does not post, comment, vote, message users, or automate actions on community
  platforms.
- It does not collect private user data.
- It does not build user profiles.
- It does not store full community datasets.
- It does not use source content to train or fine-tune AI models.

The output is a private research brief for product discovery. A typical result might
summarize a repeated pain such as "small businesses manually chase unpaid invoices" or
"developers struggle to test webhook traffic before launch," then include affected
users, possible existing tools, a first-build idea, confidence, and source links.

## Reddit API Use

Problembrief may use Reddit's Data API only for selected public subreddits and only at
low volume. Reddit data would be one source among others, not the whole product.

When Reddit is enabled, the app reads public posts and public comments from a small set
of chosen communities such as SaaS, startups, small business, developer tools, AI, or
operations communities. It collects limited public metadata:

- post title
- post URL
- subreddit name
- score and comment count
- short excerpts or summaries from relevant public comments

It then groups recurring problems into private research briefs. For example:

- If several posts in `r/SaaS` or `r/startups` discuss failed onboarding, confusing
  pricing, or poor trial conversion, Problembrief may summarize that as a go-to-market
  or product problem.
- If posts in `r/smallbusiness` mention chasing unpaid invoices, manual bookings, or
  missed customer follow-ups, it may summarize that as a small-business workflow pain.
- If posts in `r/webdev`, `r/devops`, or `r/programming` mention webhook testing,
  flaky tests, deployment errors, or API integration issues, it may classify that as a
  developer workflow problem.

Problembrief does not interact with Reddit users. It does not create Reddit posts,
leave comments, vote, send messages, moderate communities, or mirror Reddit content.

## Pipeline (LangGraph)

```
fetch_sources → extract_pain_points → dedupe_similar → generate_daily_brief → save_results
```

- **fetch_sources** — all no-auth and on by default:
  - **Hacker News** — searched for recent pain/complaint phrases ("is there a way to…",
    "alternative to…", "frustrated with…"), not the front page, so it surfaces real
    gripes about *existing products*, not launch headlines.
  - **Lobsters** (`hottest.json`) and **Dev.to** (`/api/articles`).
  - **GitHub Issues** (Search API) — recent issues (last ~30 days) matching pain queries.
  - **Web discovery** — optional search-backed discovery across small business,
    vertical SaaS, ecommerce, security, AI, developer tools, and other categories.
  - **Reddit web discovery** — optional Tavily searches for narrow public Reddit pain
    signals, such as `site:reddit.com/r/smallbusiness frustrated software`,
    `site:reddit.com/r/SaaS "is there a tool"`, and
    `site:reddit.com/r/webdev "I hate"`. This is public web search, not Reddit API
    access, and is used only for low-volume research summaries.
  - **Reddit** — planned optional source, subject to Reddit API approval and platform
    terms. It will be low-volume and limited to public posts/comments from selected
    subreddits.
  - The HN phrases and GitHub queries are **rotated daily** from a larger pool, so the
    brief stops circling the same topics. The busiest HN + GitHub threads are enriched
    with their **top comments**, where the real pain shows. A **cross-run dedup** then
    drops anything already surfaced within `RADAR_DEDUP_DAYS` (default 7). A free
    `GITHUB_TOKEN` just raises GitHub's rate limit; one failing source won't kill the run.
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
`gpt-5.5`) — the pipeline is provider-agnostic.

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
- `RADAR_ENRICH_TOP_N` — max leads to research and include (default 8; fewer when the day is thin)
- `RADAR_REDDIT_WEB_QUERIES` — semicolon-separated public Reddit web-search queries
- `RADAR_REDDIT_WEB_PER_DAY` — how many Reddit web queries to run daily
- `RADAR_REDDIT_WEB_RESULTS_PER_QUERY` — max Tavily results per Reddit web query
- `RADAR_REDDIT_WEB_RECENCY_MONTHS` — skip old Reddit web results beyond this window
  (default 18)
- `RADAR_TOP_N` — legacy top-opportunity limit
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
