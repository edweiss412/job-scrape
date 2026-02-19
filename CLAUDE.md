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

# Scrape only, no LLM scoring
python job_scraper.py --no-evaluate

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
7. **`web/`** — Next.js 16 app (App Router, TypeScript, Tailwind v4). The primary job dashboard. Deployed to Vercel at jobs.avprobms.app.

> **`build_site.py`** is kept for reference but is no longer used. The static GitHub Pages site (docs/) has been removed. The Next.js webapp replaces it entirely.

### web/ app structure

- `web/src/app/` — Next.js App Router pages: `/opportunities/fulltime`, `/opportunities/fulltime/[jobId]`, `/opportunities/freelance`, `/opportunities/freelance/[runDate]`, `/opportunities/freelance/[runDate]/[companyId]`, `/profile`, `/login`, `/admin`, `/admin/users`, `/admin/feedback`, `/admin/scans`. Legacy routes (`/runs`, `/jobs`, `/freelance` and sub-paths) redirect to their `/opportunities/*` equivalents for backward compat.
- `web/src/app/api/` — API routes: `/api/auth/callback`, `/api/resumes`, `/api/resumes/[id]`, `/api/resumes/[id]/download`, `/api/resumes/[id]/evaluate`, `/api/interview-qa`, `/api/interview-qa/[id]`, `/api/interview-qa/generate`, `/api/user-profile`, `/api/feedback`, `/api/feedback/[id]`, `/api/feedback/suggest`, `/api/admin/users`, `/api/admin/users/[userId]`, `/api/admin/scans` (workflow run history), `/api/admin/scans/cancel`, `/api/admin/scans/evaluations`, `/api/scan/trigger` (admin dispatch), `/api/scan/status`, `/api/scan/evaluate` (per-user on-demand eval dispatch + status poll)
- `web/src/components/` — UI components: `jobs/`, `freelance/`, `profile/`, `layout/`, `ui/`, `admin/`
- `web/src/lib/types.ts` — All shared TypeScript types (`Job`, `Run`, `UserProfile`, `Resume`, `InterviewQA`, `Feedback`, `FreelanceCompany`, etc.)
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
- `save_results()` — Writes CSV, JSON, and per-verdict markdown files to `results/<date>/`.
- `sync_to_supabase()` — Syncs run metadata and evaluated jobs to Supabase REST API (runs, jobs, run_jobs tables).
- `sync_deep_evals()` — Patches deep_evaluation column for STRONG jobs after the deep eval pass.
- `download_active_resume()` — Downloads the primary resume from Supabase Storage before evaluation.
- `run_benchmark()` — Evaluates a sample of past jobs across multiple models to compare quality/cost.
- `run_scrape()` → `run_evaluate()` → `run_deep_evaluation()` — Main pipeline stages.
- `evaluate_batch()` — Parallel LLM evaluation via `ThreadPoolExecutor`. Uses `eval_cache.json` to skip re-evaluation.

### freelance_finder.py class structure

- **`CompanyProfile`** — Dataclass for discovered companies (tier: HOT/WARM/COLD/SKIP).
- **`SerpAPIWebSearcher`** / **`BrightDataWebSearcher`** — Search backends (same pattern as job_scraper).
- **`ActivityVerifier`** — Checks company websites for recent hiring activity.
- **`CompanyEvaluator`** — LLM evaluates companies and drafts personalized cold outreach emails.
- `deduplicate_companies()` — Fuzzy dedup against previous run cache and `clients.yaml` known partners.

### Data flow

```
# Job search pipeline
config.yaml + resume from Supabase Storage (or local fallback)
    → job_scraper.py scrapes from 5 sources (SerpAPI/BrightData, Indeed RSS, AVIXA, career pages, JobSpy)
    → deduplicates (~40-60% overlap typical)
    → LLM evaluates each job (cached in eval_cache.json)
    → saves to results/<date>/{strong,moderate,stretch,weak}/*.md + CSV + JSON
    → writes run_metadata.json
    → sync_to_supabase() → upserts runs, jobs, run_jobs tables in Supabase
    → email_sender.py → sends digest via Resend (links to jobs.avprobms.app)

# Freelance pipeline (manual trigger)
config.yaml + clients.yaml
    → freelance_finder.py discovers companies via search APIs
    → verifies activity, deduplicates against clients.yaml
    → LLM evaluates and drafts cold outreach emails
    → saves to freelance/{date}/ + updates freelance_cache.json
    → sync to Supabase freelance_companies table (via job_scraper sync functions)

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
- `web/` — Next.js app source. See `web/.env.local` for local env vars.
- `.github/workflows/scrape.yml` — Scheduled CI: scrape → sync to Supabase → email → commit & push results.
- `.github/workflows/freelance.yml` — Manual-trigger CI for freelance finder.
- `.github/workflows/evaluate_for_user.yml` — Per-user evaluation workflow dispatched from the web app.

### Supabase schema

- **`runs`** — One row per scrape run (run_date, verdict counts, new_job_ids). UNIQUE on `(user_id, run_date)` after multi-user migration.
- **`jobs`** — All evaluated jobs, unique by `job_id` (MD5 hash). Contains full evaluation markdown.
- **`run_jobs`** — Junction: which jobs appeared in which run, with `is_new_this_run` flag.
- **`user_evaluations`** — Per-user LLM evaluations of jobs (match_score, match_verdict, full_evaluation, deep_evaluation). Separate from the global `jobs` table so each user can have their own scores.
- **`user_profiles`** — Per-user settings and on-demand eval status (`target_roles`, `target_locations`, `candidate_context`, `notify_email`, `home_city`, `current_income`, `full_name`, `phone`, `linkedin_url`, `professional_title`, `eval_status` [idle/pending/running/completed/error], `eval_job_count`).
- **`freelance_companies`** — Freelance prospects with fit_tier (HOT/WARM/COLD), evaluation, outreach draft.
- **`resumes`** — User-uploaded resumes with Storage path. `is_primary=true` row is downloaded by scraper. `resume_evaluation` + `resume_evaluated_at` columns store LLM evaluation (run from /profile page).
- **`interview_qa`** — Interview Q&A pairs with `question`, `answer`, `category` (technical/behavioral/situational/general), `source` (manual/ai_generated).
- **`feedback`** — User-submitted feedback (type: bug/feature, status, priority, screenshot_url, steps_to_reproduce, etc.). Writable by admin and beta testers.

### Configuration

- API keys in `config.yaml` or env vars: `SERPAPI_KEY`, `BRIGHTDATA_API_TOKEN`, `OPENROUTER_KEY`, `GOOGLE_AISTUDIO_KEY`.
- Supabase: `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` env vars (GitHub secrets for CI, `.env.local` for web app).
- GitHub dispatch (for admin scan trigger and per-user on-demand evaluation): `GITHUB_TOKEN`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME` — set in Vercel env vars and in `.env.local`.
- `llm_provider` in config.yaml: `"openrouter"`, `"anthropic"`, `"google_aistudio"`, or `"openai_compatible"`.
- `candidate_context` supplements the resume with situation-specific info for the LLM evaluator.

#### Centralized model assignments (`config.yaml` → `models` section)

Every LLM model used across the pipeline and web app is declared in the `models` section of `config.yaml`. Roles: `job_eval`, `deep_eval`, `freelance_eval`, `utility`, `web_resume_eval`, `web_interview_qa`, `web_feedback_text`, `web_feedback_vision`. Each entry has `provider` (optional, defaults to top-level `llm_provider`) and `model`. Old per-provider keys (`openrouter_model`, etc.) and per-section keys (`deep_eval.model`, `freelance_search.llm_model`) still work as fallbacks.

- **Python:** `resolve_model(config, role)` (in both `job_scraper.py` and `freelance_finder.py`) returns `(provider, model_id)` for any role. `ResumeEvaluator` accepts a `role` kwarg (default `"job_eval"`); deep eval passes `role="deep_eval"`.
- **Web app:** `web/src/lib/models.ts` exports `MODEL_RESUME_EVAL`, `MODEL_INTERVIEW_QA`, `MODEL_FEEDBACK_TEXT`, `MODEL_FEEDBACK_VISION` — all overridable via same-named env vars.

### GitHub Actions CI

- **`scrape.yml`** — Scheduled Mon/Thu 8am CT: scrape → sync to Supabase → email → commit results. No static site build. Uses `git pull --rebase -X ours` to avoid conflicts.
- **`freelance.yml`** — Manual dispatch only. Supports `category`, `max_companies`, `no_verify` inputs.
- **`evaluate_for_user.yml`** — Manually dispatched from the web app (`/api/scan/evaluate`). Accepts `user_id` input; runs the evaluation pipeline scoped to that user and updates `user_evaluations` + `user_profiles.eval_status`.
- Both scheduled workflows restore the resume from base64-encoded `RESUME_B64` secret as a local fallback.
- GitHub secrets needed: `SERPAPI_KEY`, `OPENROUTER_KEY`, `GOOGLE_AISTUDIO_KEY`, `RESEND_API_KEY`, `NOTIFY_EMAIL`, `RESUME_B64`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- GitHub variable: `SITE_BASE_URL=https://jobs.avprobms.app`
