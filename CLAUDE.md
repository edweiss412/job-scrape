# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A multi-user job search automation pipeline for AV/audio engineering roles. It scrapes listings from multiple sources, deduplicates them, scores each against a resume using an LLM, then syncs results to Supabase and sends email notifications. Results are browsable via a Next.js webapp deployed to **jobs.avprobms.app**, with per-user evaluations, resume management, and admin features. Also includes a freelance prospect finder for cold outreach. Runs on GitHub Actions (Mon/Thu 8am CT) or locally.

## Commands

```bash
# Install Python deps
pip install -r requirements.txt

# Full scrape + evaluate
python job_scraper.py

# Quick scan (SerpAPI + Indeed only, skip career pages/AVIXA/JobSpy)
python job_scraper.py --quick

# JobSpy only
python job_scraper.py --jobspy-only

# Scrape only, no LLM scoring (legacy — use --scrape-only for the new pipeline)
python job_scraper.py --no-evaluate

# Scrape-only pipeline: scrape → fetch descriptions → pre-filter → sync to Supabase (no LLM eval)
python job_scraper.py --scrape-only

# Re-score last results without re-scraping
python job_scraper.py --evaluate-only

# Skip deep evaluation pass on STRONG matches
python job_scraper.py --no-deep

# Benchmark multiple LLM models against a sample of jobs
python job_scraper.py --benchmark

# Send email digest (requires RESEND_API_KEY, NOTIFY_EMAIL, SITE_BASE_URL env vars)
python email_sender.py

# Freelance prospect finder
python freelance_finder.py                         # Full run: discover + verify + evaluate
python freelance_finder.py --discover-only         # Skip verification and LLM
python freelance_finder.py --evaluate-only         # Re-run LLM on cached companies
python freelance_finder.py --no-outreach           # Evaluate but skip email drafts
python freelance_finder.py --category av_rental    # One category only
python freelance_finder.py --min-tier hot          # Only draft outreach for HOT companies
python freelance_finder.py --max-companies 50      # Cap discovery volume
python freelance_finder.py --benchmark             # Benchmark LLM models on synthetic test companies

# Facebook group monitor (freelance gigs)
python facebook_monitor.py                    # Full run: fetch + filter + score + digest
python facebook_monitor.py --fetch-only       # Fetch and cache, no scoring
python facebook_monitor.py --score-only       # Re-score last fetch
python facebook_monitor.py --immediate        # Immediate alerts for HOT only
python facebook_monitor.py --digest           # Daily digest email
python facebook_monitor.py --no-email         # Score but skip email
python facebook_monitor.py --dry-run          # Keyword matches only, no LLM
python facebook_monitor.py --group GROUP_KEY  # Single group (name substring match)
python facebook_monitor.py --days-back N      # Override lookback window
python facebook_monitor.py --tier high        # Filter by priority tier (high/medium/low/all)
python facebook_monitor.py --login            # Save Facebook session for private groups

# One-time migration of historical results into Supabase
python migrate_to_supabase.py           # Full migration
python migrate_to_supabase.py --dry-run # Print counts only

# One-time migration to multi-user schema (assign legacy single-user data to admin)
python migrate_to_multiuser.py
python migrate_to_multiuser.py --dry-run

# Test deep eval on a single job with a specific model (edit TARGET_JOB_ID/TEST_MODEL inline)
python test_deep_eval.py

# Next.js web app
cd web && npm run dev    # Dev server at localhost:3000
cd web && npm run build  # Production build check
vercel --prod --yes      # Deploy to jobs.avprobms.app (run from web/)
```

> **No lint or test tooling is configured.** The web app has no ESLint, Prettier, or test runner. Use `npm run build` in `web/` as the primary correctness check for TypeScript/Next.js changes.

## Architecture

### Pipeline files

1. **`job_scraper.py`** (~2500 lines) — Core scraper + evaluator. All scraper classes, LLM evaluation, deduplication, Supabase sync, benchmarking, and result output.
2. **`freelance_finder.py`** — Discovers AV/audio companies for freelance cold outreach. Outputs to `freelance/` dir and updates `freelance_cache.json`.
3. **`email_sender.py`** — Sends HTML email digest via Resend API. Reads `run_metadata.json` written by job_scraper.py. Links point to jobs.avprobms.app.
4. **`migrate_to_supabase.py`** — One-time script to bulk-load historical results into Supabase.
5. **`migrate_to_multiuser.py`** — One-time migration to assign legacy single-user data to the admin user and update the `runs` unique constraint to `(user_id, run_date)`.
6. **`test_deep_eval.py`** — Dev utility to test deep eval on a specific job ID with a chosen model. Edit `TARGET_JOB_ID`, `TEST_MODEL`, and `DATA_FILE` inline; output goes to `test_deep_eval_output.md`.
7. **`facebook_monitor.py`** — Hybrid Facebook group monitor: public groups via BrightData Dataset API, private groups via Playwright with a saved session (`fb_session.json`). Groups organized by priority tier (high/medium/low). Fetches posts, filters by keywords, scores with LLM, sends email alerts. Outputs to `fb_monitor/` dir and updates `fb_posts_cache.json`.
8. **`web/`** — Next.js 16 app (App Router, TypeScript, Tailwind v4). The primary job dashboard. Deployed to Vercel at jobs.avprobms.app.

> **`build_site.py`** is kept for reference but is no longer used. The static GitHub Pages site (docs/) has been removed. The Next.js webapp replaces it entirely.

### web/ app structure

- `web/src/app/` — Next.js App Router pages: `/opportunities/fulltime`, `/opportunities/fulltime/[jobId]`, `/opportunities/freelance`, `/opportunities/freelance/[runDate]`, `/opportunities/freelance/[runDate]/[companyId]`, `/profile`, `/login`, `/admin`, `/admin/users`, `/admin/feedback`, `/admin/scans`. Legacy routes (`/runs`, `/jobs`, `/freelance` and sub-paths) redirect to their `/opportunities/*` equivalents for backward compat.
- `web/src/app/api/` — API routes: `/api/auth/callback`, `/api/resumes`, `/api/resumes/[id]`, `/api/resumes/[id]/download`, `/api/resumes/[id]/evaluate`, `/api/interview-qa`, `/api/interview-qa/[id]`, `/api/interview-qa/generate`, `/api/resume-tailor/suggestions` (generate tailoring suggestions for a job), `/api/resume-tailor/generate` (apply suggestions and return .docx), `/api/user-profile`, `/api/feedback`, `/api/feedback/[id]`, `/api/feedback/suggest`, `/api/admin/users`, `/api/admin/users/[userId]`, `/api/admin/scans` (workflow run history), `/api/admin/scans/cancel`, `/api/admin/scans/evaluations`, `/api/scan/trigger` (admin dispatch), `/api/scan/status`, `/api/scan/evaluate` (per-user on-demand eval dispatch + status poll), `/api/jobs/unevaluated` (count of pre-filtered jobs not yet evaluated for current user)
- `web/src/components/` — UI components: `jobs/`, `freelance/`, `profile/`, `layout/`, `ui/`, `admin/`
- `web/src/lib/types.ts` — All shared TypeScript types (`Job`, `Run`, `UserProfile`, `Resume`, `InterviewQA`, `Feedback`, `FreelanceCompany`, `FacebookPost`, etc.)
- `web/src/lib/admin.ts` — `isAdmin()`, `isBetaTester()`, `canSubmitFeedback()` role helpers. Admin = `edweiss412@gmail.com`; beta testers have `app_metadata.role === 'beta_tester'`.
- `web/src/lib/resume-extract.ts` — `extractResumeText()` helper; downloads from Supabase Storage and extracts text from PDF (`pdf-parse`) or DOCX (`mammoth`).
- `web/src/proxy.ts` — Next.js route protection middleware (redirects unauthenticated users to /login, blocks non-admins from `/admin`). Set `NEXT_PUBLIC_SKIP_AUTH=true` in `.env.local` to bypass auth for local testing.
- `web/.env.local` — Local env vars (NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME)

### Supabase client patterns

`web/src/lib/supabase/server.ts` exports two clients — choose the right one:

- `createClient()` — Cookie-based server client using the anon key. Respects Row Level Security. Use in Server Components and API routes that operate in the authenticated user's context.
- `createServiceClient()` — Uses the service role key, bypasses RLS entirely. Use only in admin API routes or server-side operations that need to act on behalf of any user (e.g., reading/writing another user's data).

Client-side components use `swr` for data fetching and the browser client from `web/src/lib/supabase/client.ts`.

### job_scraper.py class structure

- **`JobListing`** — Dataclass for all job data. `job_id` is MD5 of `title|company|normalized_location`.
- **`SerpAPIScraper`** — Google Jobs via SerpAPI (best source). Free tier: 100 searches/mo.
- **`BrightDataScraper`** — Drop-in alternative to SerpAPI. Falls back automatically when SerpAPI is rate-limited.
- **`IndeedRSSScraper`** — Indeed RSS feeds, free, no API key needed.
- **`AVIXAScraper`** — Scrapes AVIXA Career Center (AV-industry niche board).
- **`CareerPageScraper`** — Direct scraping of target company career pages. Uses `JOB_SELECTORS` dict. Fragile — selectors break when sites redesign.
- **`JobSpyScraper`** — Uses python-jobspy for Indeed/Glassdoor/Google/ZipRecruiter.
- **`ResumeEvaluator`** — LLM evaluation engine. Supports OpenRouter, Anthropic, Google AI Studio, and OpenAI-compatible endpoints. Two-pass: first scores all jobs; second "deep eval" generates full application prep packages for STRONG matches.

### Key functions in job_scraper.py

- `deduplicate_jobs()` — Multi-strategy dedup: exact job_id, URL normalization, fuzzy title+company matching.
- `fetch_job_description()` — Fetches full job description HTML for evaluation context.
- `fetch_descriptions_batch()` — Parallel description fetching for all new jobs at scrape time.
- `save_results()` — Writes CSV, JSON, and per-verdict markdown files to `results/<date>/`.
- `sync_to_supabase()` — Syncs run metadata and evaluated jobs to Supabase REST API (runs, jobs, run_jobs tables).
- `sync_scrape_results()` — Scrape-only sync: upserts `scrape_runs` + batch upserts job catalog (no eval data).
- `sync_deep_evals()` — Patches deep_evaluation column for STRONG jobs after the deep eval pass.
- `download_active_resume()` — Downloads the primary resume from Supabase Storage before evaluation.
- `run_benchmark()` — Evaluates a sample of past jobs across multiple models to compare quality/cost.
- `run_scrape()` → `run_evaluate()` → `run_deep_evaluation()` — Main pipeline stages (full mode).
- `run_scrape()` → `fetch_descriptions_batch()` → `sync_scrape_results()` → `run_pre_filter()` → `check_expired_listings()` — Scrape-only pipeline (`--scrape-only`).
- `run_pre_filter()` — Two-layer pre-filter: keyword scoring + cheap LLM for ambiguous jobs. Updates `pre_filter_passed` in Supabase.
- `check_expired_listings()` — HEAD-checks a sample of active job URLs and marks expired ones.
- `evaluate_batch()` — Parallel LLM evaluation via `ThreadPoolExecutor`. Uses `eval_cache.json` to skip re-evaluation.
- `fetch_recent_jobs_for_user()` — Fetches unevaluated jobs from Supabase (with stored descriptions, pre-filter filtering).

### freelance_finder.py class structure

- **`CompanyProfile`** — Dataclass for discovered companies (tier: HOT/WARM/COLD/SKIP, dimensional scores).
- **`SerpAPIWebSearcher`** / **`BrightDataWebSearcher`** — Search backends (same pattern as job_scraper).
- **`ActivityVerifier`** — Checks company websites for recent hiring activity.
- **`CompanyEvaluator`** — LLM evaluates companies using 5 weighted dimensions (Geographic Fit 2x, Scale & Gear 2x, Work-Type 1x, Relationship Potential 1x, Credibility 1x). Server-side composite recalculation and gating rules override LLM tier. Pre-LLM blocked operator detection saves cost. Drafts personalized cold outreach emails for qualifying companies.
- `deduplicate_companies()` — Three-pass dedup: exact company_id, fuzzy name+state, URL root domain.
- `run_freelance_benchmark()` — Benchmark runner: evaluates 8 synthetic companies across multiple models, scores tier accuracy.
- `sync_freelance_to_supabase()` — Dual-write: catalog data to `freelance_companies`, per-user evaluations to `user_freelance_evaluations`.

### facebook_monitor.py class structure

- **`FacebookPost`** — Dataclass for FB group posts (post_id, content, relevance_tier HOT/WARM/COLD, gig_summary, etc.).
- **`BrightDataFacebookScraper`** — Async trigger/poll/download for BrightData Facebook Groups Dataset API (dataset `gd_lz11l67o2cb3r0lkj3`). Used for public groups only.
- **`PlaywrightFacebookScraper`** — Scrapes private groups using Playwright with a saved Facebook session (`fb_session.json`). Scrolls feed, extracts posts from `div[role="article"]` elements. Session saved via `--login` flag; for CI, restored from `FB_SESSION_B64` env var.
- **`KeywordMatcher`** — Fast pre-filter with built-in AV gig keywords and configurable extras.
- **`PostScorer`** — LLM relevance scoring (same multi-provider pattern as freelance_finder).
- `_resolve_groups()` — Flattens tiered group config (high/medium/low) into a flat list, applies tier and group name filters. Backward-compatible with legacy flat group format.
- `_parse_brightdata_posts()` — Converts raw BrightData dicts to FacebookPost objects.
- `save_login_session()` — Opens headed Chromium for manual Facebook login, saves storage state to `fb_session.json`.
- `send_immediate_alert()` / `send_digest_email()` — Email via Resend (dark-themed HTML matching email_sender.py).
- `sync_fb_posts_to_supabase()` — Upserts scored posts to `facebook_posts` table.

### Data flow

```
# Job search pipeline (scrape-only mode — default for scheduled runs)
config.yaml
    → job_scraper.py --scrape-only: scrapes from 5 sources (SerpAPI/BrightData, Indeed RSS, AVIXA, career pages, JobSpy)
    → deduplicates (~40-60% overlap typical)
    → fetch_descriptions_batch(): fetches full descriptions in parallel
    → sync_scrape_results(): upserts scrape_runs + jobs catalog (with descriptions) to Supabase
    → run_pre_filter(): keyword scoring + optional cheap LLM → marks pre_filter_passed on each job
    → check_expired_listings(): HEAD-checks URLs, marks expired jobs
    → NO LLM evaluation, NO per-user scoring

# Per-user evaluation (on-demand via web UI or evaluate_for_user.yml)
    → fetch_recent_jobs_for_user(): reads jobs from Supabase (with stored descriptions, pre_filter_passed filtering)
    → evaluator.evaluate_batch(): LLM scores jobs against user's resume (skips web re-fetching for jobs with stored descriptions)
    → streams results to user_evaluations table in real-time

# Legacy full pipeline (still works with: python job_scraper.py)
config.yaml + resume from Supabase Storage (or local fallback)
    → job_scraper.py scrapes + evaluates + syncs all in one run
    → saves to results/<date>/{strong,moderate,stretch,weak}/*.md + CSV + JSON
    → email_sender.py → sends digest via Resend (links to jobs.avprobms.app)

# Freelance pipeline (manual trigger)
config.yaml + clients.yaml
    → freelance_finder.py discovers companies via search APIs
    → verifies activity, deduplicates against clients.yaml
    → LLM evaluates and drafts cold outreach emails
    → saves to freelance/{date}/ + updates freelance_cache.json
    → sync to Supabase freelance_companies table (via job_scraper sync functions)

# Facebook group monitor (daily cron or manual trigger)
config.yaml (facebook_monitor section: tiered groups, keywords)
    → facebook_monitor.py hybrid fetch:
        - Public groups → BrightData Facebook Groups Dataset API
        - Private groups → Playwright with saved fb_session.json
    → keyword pre-filter (AV gig terms, negatives)
    → LLM scores remaining posts (HOT/WARM/COLD)
    → saves to fb_monitor/{date}/ + updates fb_posts_cache.json
    → sync to Supabase facebook_posts table
    → sends email digest (HOT + WARM) or immediate alerts (HOT only)

# Webapp
Supabase (Postgres + Storage + Auth)
    → Next.js app at jobs.avprobms.app
    → Google OAuth (restricted to edweiss412@gmail.com)
    → Deployed to Vercel; redeploy with: cd web && vercel --prod --yes
```

### Directory layout

- `config.yaml` — All config: API keys, search queries, locations, candidate context, city relocation profiles, career page URLs. The `models` section centralizes every LLM model assignment (see below).
- `clients.yaml` — Known freelance partners. Companies here are auto-tagged SKIP in freelance evaluation.
- `relocation_profiles.yaml` — City cost-of-living and QOL data.
- `resume.txt` — Plain-text resume fallback. CI also uses base64-encoded `RESUME_B64` secret; active resume is fetched from Supabase Storage.
- `data/` — Raw JSON snapshots per scrape run.
- `results/<date>/` — Organized by verdict: `strong/`, `moderate/`, `stretch/`, `weak/` containing individual `.md` evaluation files.
- `freelance/` — Freelance prospect results mirroring `results/` structure.
- `eval_cache.json` — Persistent LLM evaluation cache keyed by job_id.
- `freelance_cache.json` — Persistent cache of discovered freelance companies.
- `fb_monitor/` — Facebook group monitor results organized by date, with per-tier markdown files.
- `fb_posts_cache.json` — Persistent cache of seen Facebook posts (keyed by `fb_post_hash`).
- `fb_session.json` — Playwright storage state (Facebook login cookies) for private groups. Never committed (gitignored). Generate with `--login`; for CI, restore from `FB_SESSION_B64` secret.
- `web/` — Next.js app source. See `web/.env.local` for local env vars.
- `.github/workflows/scrape.yml` — Scheduled CI: scrape-only → sync to Supabase → commit & push results. No LLM evaluation; users trigger evaluation on-demand via the web app.
- `.github/workflows/freelance.yml` — Manual-trigger CI for freelance finder.
- `.github/workflows/facebook_monitor.yml` — Daily cron (7am CT) + manual dispatch for Facebook group monitoring.
- `.github/workflows/evaluate_for_user.yml` — Per-user evaluation workflow dispatched from the web app.

### Supabase schema

- **`runs`** — One row per evaluation run (run_date, verdict counts, new_job_ids). UNIQUE on `(user_id, run_date)` after multi-user migration.
- **`scrape_runs`** — One row per scrape-only run (run_date, total_scraped, new_jobs, sources, expired stats, pre_filter_stats). UNIQUE on `run_date`.
- **`jobs`** — All scraped jobs, unique by `job_id` (MD5 hash). Contains `description` (stored at scrape time), `listing_status` (active/expired/removed), `pre_filter_score`, `pre_filter_passed`, `title_keywords`. Evaluation data is in `user_evaluations`.
- **`run_jobs`** — Junction: which jobs appeared in which run, with `is_new_this_run` flag.
- **`user_evaluations`** — Per-user LLM evaluations of jobs (match_score, match_verdict, full_evaluation, deep_evaluation). Separate from the global `jobs` table so each user can have their own scores.
- **`user_profiles`** — Per-user settings and on-demand eval status (`target_roles`, `target_locations`, `candidate_context`, `notify_email`, `home_city`, `current_income`, `full_name`, `phone`, `linkedin_url`, `professional_title`, `eval_status` [idle/pending/running/completed/error], `eval_job_count`).
- **`freelance_companies`** — Freelance prospects (catalog data: name, city, website, gear, activity). Legacy eval fields retained during transition.
- **`user_freelance_evaluations`** — Per-user freelance evaluations (fit_tier, fit_score, dimensional scores, outreach drafts). Keyed on `(user_id, company_id)`. Mirrors the `user_evaluations` pattern.
- **`resumes`** — User-uploaded resumes with Storage path. `is_primary=true` row is downloaded by scraper. `resume_evaluation` + `resume_evaluated_at` columns store LLM evaluation (run from /profile page).
- **`interview_qa`** — Interview Q&A pairs with `question`, `answer`, `category` (technical/behavioral/situational/general), `source` (manual/ai_generated).
- **`facebook_posts`** — Facebook group posts scored for freelance AV gig relevance (fb_post_hash unique key, relevance_tier HOT/WARM/COLD, gig_summary, matched_keywords JSONB).
- **`feedback`** — User-submitted feedback (type: bug/feature, status, priority, screenshot_url, steps_to_reproduce, etc.). Writable by admin and beta testers.

### Configuration

- API keys in `config.yaml` or env vars: `SERPAPI_KEY`, `BRIGHTDATA_API_TOKEN`, `OPENROUTER_KEY`, `GOOGLE_AISTUDIO_KEY`.
- Supabase: `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` env vars (GitHub secrets for CI, `.env.local` for web app).
- GitHub dispatch (for admin scan trigger and per-user on-demand evaluation): `GITHUB_TOKEN`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME` — set in Vercel env vars and in `.env.local`.
- `llm_provider` in config.yaml: `"openrouter"`, `"anthropic"`, `"google_aistudio"`, or `"openai_compatible"`.
- `candidate_context` supplements the resume with situation-specific info for the LLM evaluator.

#### Centralized model assignments (`config.yaml` → `models` section)

Every LLM model used across the pipeline and web app is declared in the `models` section of `config.yaml`. Roles: `job_eval`, `deep_eval`, `freelance_eval`, `fb_monitor`, `utility`, `web_resume_eval`, `web_interview_qa`, `web_feedback_text`, `web_feedback_vision`. Each entry has `provider` (optional, defaults to top-level `llm_provider`) and `model`. Old per-provider keys (`openrouter_model`, etc.) and per-section keys (`deep_eval.model`, `freelance_search.llm_model`) still work as fallbacks.

- **Python:** `resolve_model(config, role)` (in `job_scraper.py`, `freelance_finder.py`, and `facebook_monitor.py`) returns `(provider, model_id)` for any role. `ResumeEvaluator` accepts a `role` kwarg (default `"job_eval"`); deep eval passes `role="deep_eval"`. Pre-filter uses `role="pre_filter"`.
- **Web app:** `web/src/lib/models.ts` exports `MODEL_RESUME_EVAL`, `MODEL_INTERVIEW_QA`, `MODEL_FEEDBACK_TEXT`, `MODEL_FEEDBACK_VISION`, `MODEL_RESUME_TAILOR` — all overridable via same-named env vars.

### GitHub Actions CI

- **`scrape.yml`** — Scheduled Mon/Thu 8am CT: `--scrape-only` → fetch descriptions → pre-filter → sync to Supabase → commit results. No LLM evaluation (no `OPENROUTER_KEY` needed). Uses `git pull --rebase -X ours` to avoid conflicts.
- **`freelance.yml`** — Manual dispatch only. Supports `category`, `max_companies`, `no_verify` inputs.
- **`facebook_monitor.yml`** — Daily cron 7am CT (all tiers) + manual dispatch. Supports `mode`, `days_back`, `group`, `tier` inputs. Restores `FB_SESSION_B64` for private groups and installs Playwright. Commits `fb_posts_cache.json` and `fb_monitor/` after each run. High-priority tier every-4h cron commented out (uncomment to enable).
- **`evaluate_for_user.yml`** — Manually dispatched from the web app (`/api/scan/evaluate`). Accepts `user_id` input; runs the evaluation pipeline scoped to that user, reads stored descriptions from DB (skips web re-fetching), filters by `pre_filter_passed`, and updates `user_evaluations` + `user_profiles.eval_status`.
- Both scheduled workflows restore the resume from base64-encoded `RESUME_B64` secret as a local fallback.
- GitHub secrets needed: `SERPAPI_KEY`, `OPENROUTER_KEY`, `GOOGLE_AISTUDIO_KEY`, `RESEND_API_KEY`, `NOTIFY_EMAIL`, `RESUME_B64`, `FB_SESSION_B64`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- GitHub variable: `SITE_BASE_URL=https://jobs.avprobms.app`
