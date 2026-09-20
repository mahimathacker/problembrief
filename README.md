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
- `RADAR_BRIEF_MODE` — `issues` for cheap daily new-issue radar, `deep` for full
  market/pricing theses.
- `RADAR_ISSUE_TOP_N` — max new issues in the daily issue radar.
- `RADAR_EXTRACT_BATCH_SIZE` — source items per extraction call.
- `RADAR_SOURCE_TEXT_CHARS` — max text characters per source item sent to the model.
- `RADAR_ENABLE_OPPORTUNITY_CRITIC` — source-grounded final quality pass (`1` by default).
- `RADAR_CRITIC_MAX_CANDIDATES` — max shortlisted leads checked against original sources.
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

## Project Context For Agents

Use this section when handing the repo to another AI agent.

### Product Direction

ProblemBrief is a source-backed research agent for finding real problems, not a random
startup idea generator. It should surface **new issues** from messy public signals and
help a builder decide what is worth validating.

The product is intentionally broader than dev tools. Current research categories are:

- DevTools
- AI agents
- Small business
- Real estate
- Fitness
- General health
- Fashion/beauty
- Accounting/CA
- Marketing/creator/agencies

Do not position it as only an AI tooling radar.

### Important Decisions

- Daily runs should default to `RADAR_BRIEF_MODE=issues` to control cost.
- `issues` mode extracts, dedupes, filters, and sends new issues directly.
- `deep` mode is for manual or weekly richer research with market/pricing theses.
- Do not use the Reddit API right now. Reddit discovery is through public web search
  only.
- Ideas must be new compared with existing `briefs/*.md`.
- The agent should find problems and workflow breakdowns, not phrase output as finished
  app ideas.
- Accounting/CA should stay in scope, but generic document collection, client portals,
  and practice-management ideas should be avoided unless the evidence is unusually
  specific and costly.
- PCOS/PCOD should not be its own category because it kept repeating; use general
  health instead.

### Quality Rules

The extraction prompt should prefer:

- real workflows breaking down
- repeated manual jobs
- current workarounds
- clear user/buyer roles
- evidence from source text or comments
- boring, operational problems
- narrow reachable users

The extraction prompt should reject:

- generic productivity/self-improvement posts
- tool-overload/documentation journey posts
- one-feature requests
- vendor bugs where the vendor should fix it
- wrapper/list/guide/browser-extension ideas
- stale themes already covered in previous briefs

### Cost Notes

Deep mode can get expensive because it adds:

- Tavily market research
- pricing lookups
- one thesis LLM call per selected lead
- a final LLM writing call

Daily issue mode avoids those calls. Current cost-control defaults:

```env
RADAR_BRIEF_MODE=issues
RADAR_ISSUE_TOP_N=10
RADAR_EXTRACT_BATCH_SIZE=25
RADAR_SOURCE_TEXT_CHARS=2200
```

Switch to deep mode only when richer validation is needed:

```env
RADAR_BRIEF_MODE=deep
```

### Known Provider Notes

- OpenAI is the default quality path.
- Gemini can be used as fallback, but may rate limit and may feel weaker for this use
  case.
- GitHub Models may return `410 Gone` during retirement/brownout windows.
- Anthropic requires enough API credits.

### Main Files To Edit

- `config.py` — categories, queries, provider settings, budget knobs.
- `src/llm.py` — extraction/dedupe prompts, filters, issue/deep brief writers.
- `src/graph.py` — LangGraph pipeline and `issues` vs `deep` routing.
- `src/sources.py` — source fetching and search query behavior.
- `src/enrich.py` — Tavily market and pricing research for deep mode.
- `.github/workflows/daily.yml` — scheduled run settings.

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
