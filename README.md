# ProblemBrief

An AI research agent that scans public signals, finds repeated customer pain points,
researches the market, and writes structured product opportunity briefs.

ProblemBrief helps builders move from random ideas to source-backed problems. It is built
for daily research across focused categories: DevTools, AI agents, small businesses,
real estate, fitness, general health, fashion/beauty, accounting/CA, and
marketing/creator/agencies.

## What It Does

- Collects recent public signals from developer communities, GitHub Issues, web search,
  and public web results.
- Extracts concrete pain points with evidence, category, and 1-5 scores.
- Deduplicates similar problems into clearer product leads.
- Enriches top leads with live market research, competitor context, and targeted pricing
  lookups.
- Generates a Markdown brief with problem, buyer, existing tools, first build,
  confidence, risks, and source links.
- Saves each daily brief and records seen URLs so the same problems do not repeat every
  day.

## Example Output

Each brief includes:

- **Problem:** the pain people are describing.
- **What people do today:** the current workaround or manual workflow.
- **Job software could take over:** the broader operational job, not just an app idea.
- **What still needs a human:** judgment, exceptions, trust, or relationship work.
- **What's already out there:** competitors and pricing when found.
- **Who'd pay:** the likely user or buyer.
- **How you'd win:** a focused way a small product could compete.
- **First build:** the smallest useful version to test.
- **Why now:** what changed that makes the pain more urgent or more buildable.
- **Confidence:** what could make the idea fail.
- **Sources:** links back to the original public signals.

## Pipeline

```text
fetch_sources
  -> extract_pain_points
  -> dedupe_similar
  -> enrich_leads
  -> generate_daily_brief
  -> save_results
```

## Sources

ProblemBrief currently uses low-volume public/source-backed discovery:

- **Hacker News** pain and complaint searches.
- **Lobsters** recent technical discussions.
- **Dev.to** recent articles.
- **GitHub Issues** matching pain phrases such as feature requests, workarounds, and
  "is there a way to..." discussions.
- **Web discovery** through Tavily for focused business and product categories.
- **Public Reddit web results** through search queries such as
  `site:reddit.com/r/smallbusiness frustrated software`. This is public web search, not
  direct platform access.

## Responsible Data Use

ProblemBrief is designed for research summaries, not bulk collection or republication.

- Reads selected public sources only.
- Stores brief metadata such as title, URL, source, scores, and short evidence snippets.
- Links back to original sources instead of copying full posts or comments.
- Does not post, comment, vote, message users, or automate actions on community platforms.
- Does not collect private user data.
- Does not build user profiles.
- Does not store full community datasets.
- Does not use source content to train or fine-tune models.

## LLM Providers

The pipeline is provider-agnostic:

- **Anthropic:** `RADAR_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`
- **OpenAI:** `RADAR_PROVIDER=openai`, `OPENAI_API_KEY`
- **Gemini:** `RADAR_PROVIDER=gemini`, `GEMINI_API_KEY`
- **GitHub Models:** `RADAR_PROVIDER=github_models`, `GITHUB_TOKEN` or
  `GITHUB_MODELS_TOKEN`

Fallbacks are supported:

```env
RADAR_PROVIDER=openai
RADAR_FALLBACK_PROVIDERS=gemini,github_models
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add at least one provider key to `.env`:

```env
RADAR_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Optional but recommended for web market research:

```env
TAVILY_API_KEY=tvly-...
```

## Run Locally

```bash
python -m src.main
```

The brief prints to the terminal and saves to `briefs/YYYY-MM-DD.md`.

## Configuration

Common settings:

- `RADAR_PROVIDER` — primary LLM provider.
- `RADAR_FALLBACK_PROVIDERS` — comma-separated fallback providers.
- `RADAR_INTERESTS` — interests used to bias the personal-interest score.
- `RADAR_MAX_PER_SOURCE` — max items fetched per source.
- `RADAR_GITHUB_RECENCY_DAYS` — only pull recent GitHub issues.
- `RADAR_DEDUP_DAYS` — avoid resurfacing the same URL for N days.
- `RADAR_ENRICH_TOP_N` — number of leads to research.
- `RADAR_PRICING_LOOKUPS_PER_LEAD` — targeted pricing searches per lead.
- `RADAR_REDDIT_WEB_QUERIES` — public Reddit web-search queries.
- `RADAR_REDDIT_WEB_PER_DAY` — number of Reddit web-search queries to run daily.
- `RADAR_TOP_N` — legacy output limit.

Most defaults live in `config.py`.

## Email Delivery

ProblemBrief can email each brief through Resend.

```env
RESEND_API_KEY=re_...
EMAIL_TO=you@example.com
EMAIL_FROM=ProblemBrief <onboarding@resend.dev>
```

If `RESEND_API_KEY` is not set, email delivery is skipped.

## GitHub Actions

The workflow at `.github/workflows/daily.yml` runs the brief every day and commits:

- the generated brief in `briefs/`
- dedup state in `state/`

Add these in GitHub repo settings:

- `OPENAI_API_KEY`, `GEMINI_API_KEY`, or another provider key
- `TAVILY_API_KEY` for market research
- `RESEND_API_KEY` and `EMAIL_TO` for email delivery

Then run it manually from the Actions tab or wait for the scheduled cron.

## Project Structure

```text
src/
  main.py       CLI entrypoint
  graph.py      LangGraph pipeline
  sources.py    source fetching
  llm.py        extraction, dedupe, thesis, and brief generation
  enrich.py     market and pricing research
  schema.py     Pydantic models
  store.py      cross-run dedup state
  deliver.py    email delivery

briefs/         generated daily briefs
state/          seen URL state
```

## Roadmap

- Better source quality scoring.
- Dashboard for save, dismiss, and mark-useful.
- Notion, Slack, Telegram, or email delivery options.
- User-specific research preferences.
- Stronger evals for lead quality and pricing accuracy.
