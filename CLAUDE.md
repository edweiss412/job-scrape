# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A job search automation pipeline for AV/audio engineering roles. It scrapes listings from multiple sources, deduplicates them, scores each against a resume using an LLM, then publishes results as a static site with email notifications. Runs on GitHub Actions (Mon/Thu 8am CT) or locally.

## Commands

```bash
# Install
pip install -r requirements.txt

# Full scrape + evaluate
python job_scraper.py

# Quick scan (SerpAPI + Indeed only, skip career pages/AVIXA/JobSpy)
python job_scraper.py --quick

# Scrape only, no LLM scoring
python job_scraper.py --no-evaluate

# Re-score last results without re-scraping
python job_scraper.py --evaluate-only

# Skip deep evaluation pass on STRONG matches
python job_scraper.py --no-deep

# Build static HTML dashboard from results/
python build_site.py

# Send email digest (requires RESEND_API_KEY, NOTIFY_EMAIL env vars)
python email_sender.py
```

## Architecture

### Three-file pipeline

1. **`job_scraper.py`** — Single-file scraper + evaluator (~1900 lines). Contains all scraper classes, LLM evaluation, deduplication, and result output. This is the core of the project.
2. **`build_site.py`** — Generates a static HTML dashboard (output: `docs/`) from the markdown evaluation files in `results/`. CSS and JS are inlined — zero external dependencies.
3. **`email_sender.py`** — Sends HTML email digest via Resend API. Reads `run_metadata.json` (written by job_scraper.py) to find the latest results.

### job_scraper.py class structure

- **`JobListing`** — Dataclass for all job data. Uses MD5 hash of `title|company|normalized_location` as `job_id` for deduplication.
- **`SerpAPIScraper`** — Google Jobs via SerpAPI (best source, aggregates many sites). Free tier: 100 searches/mo.
- **`IndeedRSSScraper`** — Indeed RSS feeds, builds URLs dynamically from config queries.
- **`AVIXAScraper`** — Scrapes AVIXA Career Center (AV industry niche board).
- **`CareerPageScraper`** — Direct scraping of target company career pages. Uses `JOB_SELECTORS` dict for company-specific CSS selectors. Fragile — selectors break when sites redesign.
- **`JobSpyScraper`** — Uses python-jobspy library for Indeed/Glassdoor/Google/ZipRecruiter.
- **`ResumeEvaluator`** — LLM evaluation engine. Supports OpenRouter, Anthropic, Google AI Studio, and OpenAI-compatible endpoints. Two-pass evaluation: first pass scores all jobs, second "deep eval" pass generates application prep packages for STRONG matches.

### Key functions in job_scraper.py

- `deduplicate_jobs()` — Multi-strategy dedup: exact job_id, URL normalization, fuzzy title+company matching.
- `fetch_job_description()` — Fetches full job description HTML from listing URL for evaluation.
- `save_results()` — Writes CSV, JSON, and per-verdict markdown files to `results/<date>/`.
- `run_scrape()` → `run_evaluate()` → `run_deep_evaluation()` — The main pipeline stages called by `main()`.
- `evaluate_batch()` — Parallel LLM evaluation with `ThreadPoolExecutor`. Uses `eval_cache.json` to skip previously evaluated jobs.

### Data flow

```
config.yaml + resume.txt
    → job_scraper.py scrapes from 5 sources
    → deduplicates (~40-60% overlap typical)
    → LLM evaluates each job (cached in eval_cache.json)
    → saves to results/<date>/{strong,moderate,stretch,weak}/*.md + CSV + JSON
    → writes run_metadata.json
    → build_site.py reads results/ → generates docs/ (GitHub Pages)
    → email_sender.py reads run_metadata.json → sends digest via Resend
```

### Directory layout

- `config.yaml` — All configuration: API keys, search queries, locations, candidate context, city relocation profiles, career page URLs.
- `resume.txt` — Plain-text resume (also supports .pdf/.docx).
- `data/` — Raw JSON snapshots per scrape run.
- `results/<date>/` — Organized by verdict: `strong/`, `moderate/`, `stretch/`, `weak/` containing individual `.md` evaluation files.
- `docs/` — Generated static site for GitHub Pages. Do not edit manually.
- `eval_cache.json` — Persistent cache of LLM evaluations keyed by job_id. Prevents re-evaluating known jobs.
- `.github/workflows/scrape.yml` — CI pipeline: scrape → build site → email → commit & push results.

### Configuration

- API keys can be set in `config.yaml` or via env vars (`SERPAPI_KEY`, `OPENROUTER_KEY`, `GOOGLE_AISTUDIO_KEY`). CI uses env vars from GitHub secrets.
- `llm_provider` in config.yaml selects the LLM backend: `"openrouter"`, `"anthropic"`, `"google_aistudio"`, or `"openai_compatible"`.
- `candidate_context` in config.yaml supplements the resume with situation-specific info the evaluator should know.
- `city_profiles` in config.yaml provides cost-of-living and QOL data for relocation analysis.

### GitHub Actions CI

Workflow runs scraper → build_site → email_sender → commits results + docs back to main. Resume is stored as a base64-encoded secret (`RESUME_B64`). On failure, sends an alert email.
