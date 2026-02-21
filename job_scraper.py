#!/usr/bin/env python3
"""
Job Search Automation Pipeline
===============================
Scrapes job listings from multiple sources, deduplicates them,
and scores each against your resume using Claude.

Sources:
  1. SerpAPI or BrightData (Google Jobs) — best aggregator, pulls from LinkedIn/Indeed/etc.
  2. Indeed RSS feeds — free, no API key needed
  3. AVIXA Career Center — AV-industry-specific
  4. Direct career page scraping — for target companies

Usage:
  python job_scraper.py                  # Full scan, all sources
  python job_scraper.py --quick          # Quick scan (SerpAPI + Indeed only)
  python job_scraper.py --evaluate-only  # Re-score existing results with LLM
  python job_scraper.py --no-deep        # Skip deep evaluation of STRONG matches
  python job_scraper.py --schedule       # Run on configured schedule

Requirements:
  pip install requests beautifulsoup4 pyyaml feedparser anthropic rich
"""

import argparse
import json
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode, urlparse

import atexit

import feedparser
import requests
from bs4 import BeautifulSoup
from rich.table import Table

from pipeline.config import (
    console, log, SCRIPT_DIR, CONFIG_PATH, DATA_DIR, RESULTS_DIR,
    load_config, resolve_model, load_resume,
)
from pipeline.models import JobListing, _normalize_date_posted
from pipeline.urls import (
    ATS_DOMAINS, AGGREGATOR_DOMAINS,
    _url_domain_score, _pick_best_apply_url, _is_indirect_url, _resolve_apply_url,
)
from pipeline.dedup import (
    deduplicate_jobs, _url_dedup_key, _normalize_company,
    _normalize_title_words, _location_specificity_str,
)
from pipeline.scrapers import (
    SerpAPIScraper, BrightDataScraper, IndeedRSSScraper,
    AVIXAScraper, CareerPageScraper, JobSpyScraper,
    run_scrape, fetch_job_description, fetch_descriptions_batch,
)
from pipeline.scrapers.descriptions import backfill_missing_descriptions
from pipeline.evaluation import (
    ResumeEvaluator, run_pre_filter, user_prefilter, _keyword_score_job,
    run_benchmark, ROLE_EXPANSIONS, refilter_backfilled_jobs,
    RELEVANT_TITLE_KEYWORDS, IRRELEVANT_TITLE_KEYWORDS,
    AV_DESCRIPTION_TERMS, TARGET_COMPANY_KEYWORDS,
)
from pipeline.sync import (
    _supabase_headers, download_active_resume, download_resume_for_user,
    sync_to_supabase, sync_deep_evals, sync_scrape_results,
    check_expired_listings, _check_expired_before_eval,
    _update_scrape_stage, cleanup_old_results,
    fetch_users_with_profiles,
    _upsert_run_record, _sync_single_job, _update_run_record,
    sync_to_supabase_for_user, sync_deep_evals_for_user,
    _set_eval_status, _is_cancel_requested,
)
from pipeline.results import (
    save_results, generate_markdown_report, load_previous_results, print_summary,
)



# ---------------------------------------------------------------------------
# NOTE: Scraper classes (SerpAPIScraper, BrightDataScraper, IndeedRSSScraper,
# AVIXAScraper, CareerPageScraper, JobSpyScraper), description fetching
# functions, and run_scrape() have been extracted to pipeline/scrapers/.
# ResumeEvaluator, pre-filter functions/constants, and benchmark functions
# have been extracted to pipeline/evaluation/.
# They are imported above for backward compatibility.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# REMOVED: ResumeEvaluator class (~800 lines) — now in pipeline/evaluation/evaluator.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NOTE: Results storage & reporting (save_results, generate_markdown_report,
# load_previous_results, print_summary) have been extracted to pipeline/results.py.
# They are imported above for backward compatibility.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NOTE: Supabase sync functions (_supabase_headers, download_active_resume,
# download_resume_for_user, sync_to_supabase, sync_deep_evals, sync_scrape_results,
# check_expired_listings, _check_expired_before_eval, _update_scrape_stage,
# cleanup_old_results, fetch_users_with_profiles, _upsert_run_record,
# _sync_single_job, _update_run_record, sync_to_supabase_for_user,
# sync_deep_evals_for_user, _set_eval_status, _is_cancel_requested) have been
# extracted to pipeline/sync/. They are imported above for backward compatibility.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Per-user query generation (Fix 1 + Fix 5)
# ---------------------------------------------------------------------------
def generate_user_derived_queries(config: dict, users: list[dict]) -> tuple[dict, list[str], list[str]]:
    """
    Generate extra search queries and locations derived from user profiles.

    Collects the union of all users' target_roles and target_locations, deduplicates
    against existing config queries, expands via ROLE_EXPANSIONS, and batches into
    efficient query groups.

    Returns:
        (extra_query_groups, extra_indeed_queries, extra_locations)
        - extra_query_groups: dict of {"user_derived_0": {"queries": [...], "locations": [...]}, ...}
          These groups are skipped by SerpAPI (budget protection) and only run by BrightData.
        - extra_indeed_queries: list of individual query strings for Indeed RSS (free).
        - extra_locations: list of location strings to inject into free sources.
    """
    if not users:
        return {}, [], []

    # Collect union of all users' target_roles and target_locations
    all_roles = set()
    all_locations = set()
    for user in users:
        for role in (user.get("target_roles") or []):
            all_roles.add(role.strip().lower())
        for loc in (user.get("target_locations") or []):
            all_locations.add(loc.strip())

    if not all_roles and not all_locations:
        return {}, [], []

    # Deduplicate roles against existing config queries
    existing_terms = set()
    for group_data in config.get("queries", {}).values():
        if isinstance(group_data, dict):
            queries = group_data.get("queries", [])
        else:
            queries = group_data
        for q in queries:
            existing_terms.add(q.strip().lower())
    # Also check Indeed queries
    for q in config.get("indeed", {}).get("queries", []):
        existing_terms.add(q.strip().lower())

    # Expand roles via ROLE_EXPANSIONS to build richer terms
    expanded_terms = set()
    for role in all_roles:
        tokens = role.split()
        # Check full role as key
        if role in ROLE_EXPANSIONS:
            expanded_terms.update(ROLE_EXPANSIONS[role])
        # Check individual tokens
        for token in tokens:
            if token in ROLE_EXPANSIONS:
                expanded_terms.update(ROLE_EXPANSIONS[token])
        # Check 2-word phrases
        for i in range(len(tokens) - 1):
            phrase = f"{tokens[i]} {tokens[i+1]}"
            if phrase in ROLE_EXPANSIONS:
                expanded_terms.update(ROLE_EXPANSIONS[phrase])
        # Also add the role itself as a query term
        expanded_terms.add(role)

    # Remove terms already in existing queries
    novel_terms = {t for t in expanded_terms if t.lower() not in existing_terms}

    if not novel_terms and not all_locations:
        return {}, [], []

    # Batch similar terms into OR queries (3 terms per query to stay concise)
    # These use quoted OR syntax for SerpAPI/BrightData
    novel_list = sorted(novel_terms)
    query_groups = {}
    batch_size = 3
    for i in range(0, len(novel_list), batch_size):
        batch = novel_list[i:i + batch_size]
        # Build an OR query: "term1" OR "term2" OR "term3"
        or_query = " OR ".join(f'"{t}"' for t in batch)
        group_name = f"user_derived_{i // batch_size}"
        group_locations = sorted(all_locations) if all_locations else ["United States"]
        query_groups[group_name] = {
            "queries": [or_query],
            "locations": group_locations,
        }

    # Generate Indeed queries (free, one per unique expanded term — no batching needed)
    indeed_queries = sorted(novel_terms)[:30]  # Cap to avoid excessive RSS fetches

    # Extra locations for free sources
    extra_locations = sorted(all_locations)

    log.info(
        f"User-derived queries: {len(query_groups)} groups, "
        f"{len(indeed_queries)} Indeed queries, "
        f"{len(extra_locations)} extra locations "
        f"(from {len(all_roles)} roles, {len(all_locations)} locations across {len(users)} users)"
    )

    return query_groups, indeed_queries, extra_locations


# run_scrape() has been extracted to pipeline/scrapers/__init__.py


def run_evaluate(config: dict, jobs: list[JobListing]) -> list[JobListing]:
    """Run LLM evaluation on jobs."""
    provider = config.get("llm_provider", "openrouter")
    key_map = {
        "openrouter": "openrouter_key",
        "anthropic": "anthropic_key",
        "google_aistudio": "google_aistudio_key",
        "openai_compatible": "openai_compatible_key",
    }
    key_field = key_map.get(provider, "openrouter_key")

    if not config.get(key_field):
        console.print(f"[yellow]⚠ {provider} API key not set — skipping LLM evaluation[/yellow]")
        if provider == "openrouter":
            console.print("  Get a key at https://openrouter.ai/keys")
        elif provider == "anthropic":
            console.print("  Get a key at https://console.anthropic.com")
        elif provider == "google_aistudio":
            console.print("  Get a key at https://aistudio.google.com/apikey")
        return jobs, set()

    # Try to fetch the active resume from Supabase; fall back to local file
    active_path = download_active_resume(config)
    if active_path:
        config = dict(config)
        config["resume_path"] = str(active_path)

    resume_text = load_resume(config)
    if not resume_text:
        console.print("[yellow]⚠ No resume found — skipping LLM evaluation[/yellow]")
        return jobs, set()

    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)
    jobs = evaluator.evaluate_batch(jobs, fetch_descriptions=True)
    return jobs, evaluator.new_job_ids


def run_deep_evaluation(config: dict, jobs: list[JobListing]):
    """
    Run deep second-pass evaluation on STRONG match jobs.
    Saves detailed application prep packages to results/YYYY-MM-DD/strong/deep/.
    """
    deep_cfg = config.get("deep_eval", {})
    if not deep_cfg.get("enabled", False):
        return

    strong_jobs = [j for j in jobs if j.match_verdict == "STRONG"]
    if not strong_jobs:
        console.print("\n[dim]No STRONG matches for deep evaluation.[/dim]")
        return

    deep_provider, deep_model = resolve_model(config, "deep_eval")
    console.print(f"\n[bold]Deep evaluation: {len(strong_jobs)} STRONG match(es)[/bold]")
    console.print(f"[dim]Provider: {deep_provider} | Model: {deep_model}[/dim]")

    resume_text = load_resume(config)
    if not resume_text:
        console.print("[yellow]No resume found — skipping deep evaluation[/yellow]")
        return

    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)

    date_str = datetime.now().strftime("%Y-%m-%d")
    deep_dir = RESULTS_DIR / date_str / "strong" / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)

    def _deep_eval_single(job):
        """Run a single deep evaluation and return (job, result)."""
        first_pass = job.full_evaluation or ""
        result = evaluator.deep_evaluate(job, config, first_pass_eval=first_pass)
        return (job, result)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    saved = 0
    total = len(strong_jobs)
    max_workers = min(4, total)
    console.print(f"[dim]Workers: {max_workers}[/dim]")
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_deep_eval_single, job): job
            for job in strong_jobs
        }
        for future in as_completed(futures):
            completed += 1
            job, result = future.result()
            console.print(f"  [{completed}/{total}] {job.title} @ {job.company}...", end=" ")
            if result:
                safe_name = re.sub(r'[^\w\-]', '_', f"{job.company}_{job.title}")[:80]
                eval_path = deep_dir / f"{safe_name}.md"
                with open(eval_path, "w") as f:
                    f.write(f"# {job.title} — {job.company} (Deep Evaluation)\n\n")
                    f.write(f"**Location:** {job.location}\n")
                    f.write(f"**URL:** {job.url}\n")
                    if job.salary:
                        f.write(f"**Salary:** {job.salary}\n")
                    if job.tier:
                        f.write(f"**Tier:** {job.tier}\n")
                    f.write(f"\n---\n\n{result}\n")
                saved += 1
                console.print("[green]done[/green]")
            else:
                console.print("[red]failed[/red]")

    if saved:
        console.print(f"\n[bold green]Deep evaluations saved: {deep_dir}/ ({saved} files)[/bold green]")


def build_user_context(user: dict, admin_email: str = "edweiss412@gmail.com", config_context: str = "") -> str:
    """
    Build the candidate_context string for a multi-user eval.

    - target_roles and target_locations are always prepended so they
      influence scoring even when the user hasn't written free-form context.
    - The user's own DB context is used exclusively for non-admin users.
      config.yaml context (which is Eric's personal context) only applies
      as a fallback for the admin account, not for other users.
    """
    parts = []

    roles = [r for r in (user.get("target_roles") or []) if r.strip()]
    locs  = [l for l in (user.get("target_locations") or []) if l.strip()]
    if roles:
        parts.append(f"- Target roles: {', '.join(roles)}")
    if locs:
        parts.append(f"- Target locations: {', '.join(locs)}")

    user_context = (user.get("candidate_context") or "").strip()
    if user_context:
        parts.append(user_context)
    elif user.get("email") == admin_email or user.get("notify_email") == admin_email:
        # Admin only: fall back to config.yaml context (Eric's personal details)
        if config_context:
            parts.append(config_context)

    return "\n".join(parts)




def fetch_recent_jobs_for_user(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    days: int = 60,
    target_roles: list[str] | None = None,
) -> list[JobListing]:
    """
    Fetch jobs seen in the last `days` days that have no user_evaluation
    for this user yet. Returns them as JobListing objects ready for evaluation.

    If target_roles is provided, jobs that were globally pre-filtered out
    (pre_filter_passed=False) are "rescued" when they match the user's
    expanded role keywords — because the global filter can't know which
    sub-disciplines each user cares about.
    """
    from datetime import timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    headers = _supabase_headers(supabase_key)

    # 1. Get job_ids already evaluated for this user
    resp = requests.get(
        f"{supabase_url}/rest/v1/user_evaluations?user_id=eq.{user_id}&select=job_id",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    already_evaluated = {row["job_id"] for row in resp.json()}
    log.info(f"On-demand eval: {len(already_evaluated)} jobs already evaluated for user {user_id[:8]}…")

    # 2. Fetch recent jobs in batches (only pre_filter_passed if available, plus active listings)
    BATCH = 500
    offset = 0
    all_rows = []
    while True:
        query_url = (
            f"{supabase_url}/rest/v1/jobs"
            f"?last_seen_date=gte.{cutoff}"
            f"&listing_status=eq.active"
            f"&archived_at=is.null"
            f"&select=job_id,title,company,location,url,source,salary,date_posted,tier,date_scraped,description,pre_filter_passed"
            f"&order=date_posted.desc.nullslast"
            f"&offset={offset}&limit={BATCH}"
        )
        resp = requests.get(query_url, headers=headers, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        all_rows.extend(batch)
        if len(batch) < BATCH:
            break
        offset += BATCH

    # 3. Build rescue keywords from user's target_roles (if provided)
    #    Jobs globally pre-filtered out can be rescued if they match the user's disciplines.
    rescue_keywords = set()
    if target_roles:
        for role in target_roles:
            role_lower = role.lower()
            tokens = role_lower.split()
            rescue_keywords.update(tokens)
            for token in tokens:
                if token in ROLE_EXPANSIONS:
                    rescue_keywords.update(ROLE_EXPANSIONS[token])
            for i in range(len(tokens) - 1):
                phrase = f"{tokens[i]} {tokens[i+1]}"
                if phrase in ROLE_EXPANSIONS:
                    rescue_keywords.update(ROLE_EXPANSIONS[phrase])
            if role_lower in ROLE_EXPANSIONS:
                rescue_keywords.update(ROLE_EXPANSIONS[role_lower])
        # Also include target company keywords — always rescue those
        rescue_keywords.update(TARGET_COMPANY_KEYWORDS)

    # 4. Filter out already-evaluated ones; rescue pre_filter_passed=false if user's roles match
    unevaluated = []
    rescued = 0
    for r in all_rows:
        if r["job_id"] in already_evaluated:
            continue
        # If pre_filter_passed is explicitly False, try rescue before skipping
        if r.get("pre_filter_passed") is False:
            if not rescue_keywords:
                continue
            title_lower = r["title"].lower()
            company_lower = r["company"].lower()
            desc_lower = (r.get("description") or "").lower()
            # Rescue if title or company matches any expanded role keyword
            title_match = any(kw in title_lower for kw in rescue_keywords)
            company_match = any(kw in company_lower for kw in rescue_keywords)
            # Require 2+ description hits (same threshold as user_prefilter)
            desc_hits = sum(1 for kw in rescue_keywords if kw in desc_lower) if desc_lower else 0
            if not (title_match or company_match or desc_hits >= 2):
                continue
            rescued += 1
        unevaluated.append(r)

    if rescued:
        log.info(f"On-demand eval: rescued {rescued} globally-filtered jobs matching user's target_roles")

    # 5a. Cross-run URL dedup — identical URLs (different job_ids due to location variants)
    #     are the same posting. Keep the one with the most specific location.
    if len(unevaluated) > 1:
        url_groups: dict[str, list[dict]] = {}
        for r in unevaluated:
            uk = _url_dedup_key(r["url"])
            if uk:
                url_groups.setdefault(uk, []).append(r)
            else:
                url_groups.setdefault(f"__no_url_{id(r)}", []).append(r)
        url_deduped_rows = []
        url_removed = 0
        for group in url_groups.values():
            if len(group) == 1:
                url_deduped_rows.append(group[0])
                continue
            # Keep the version with the most specific location
            group.sort(key=lambda r: (
                _location_specificity_str(r["location"]),
                len(r.get("description") or ""),
            ), reverse=True)
            url_deduped_rows.append(group[0])
            url_removed += len(group) - 1
        if url_removed:
            log.info(f"On-demand eval: URL dedup removed {url_removed} location-variant duplicates")
        unevaluated = url_deduped_rows

    # 5b. Cross-run fuzzy dedup — same company + location + similar title = likely same opening
    #     Keep only the most recently seen posting to avoid evaluating stale reposts.
    pre_dedup = len(unevaluated)
    if len(unevaluated) > 1:
        groups = {}  # (norm_company, norm_location_city) -> list of rows
        for r in unevaluated:
            norm_loc = JobListing._normalize_location(r["location"]).lower()
            # Extract just the city (before first comma) for grouping — avoids
            # "Chicago, IL" vs "Chicago, Illinois" mismatch
            loc_city = norm_loc.split(",")[0].strip()
            key = (_normalize_company(r["company"]), loc_city)
            groups.setdefault(key, []).append(r)

        deduped = []
        for key, group in groups.items():
            if len(group) == 1 or not key[0]:
                deduped.extend(group)
                continue
            # Within group, find title clusters and keep the most recent
            kept_indices = set(range(len(group)))
            for i in range(len(group)):
                if i not in kept_indices:
                    continue
                words_i = _normalize_title_words(group[i]["title"])
                for j in range(i + 1, len(group)):
                    if j not in kept_indices:
                        continue
                    words_j = _normalize_title_words(group[j]["title"])
                    if words_i and words_j:
                        overlap = len(words_i & words_j)
                        min_words = min(len(words_i), len(words_j))
                        if min_words > 0 and overlap / min_words > 0.5:
                            # Keep the one last seen most recently
                            date_i = group[i].get("date_scraped") or ""
                            date_j = group[j].get("date_scraped") or ""
                            if date_j > date_i:
                                kept_indices.discard(i)
                                break  # i is removed, stop comparing
                            else:
                                kept_indices.discard(j)
            for idx in sorted(kept_indices):
                deduped.append(group[idx])
        unevaluated = deduped

    dedup_removed = pre_dedup - len(unevaluated)
    if dedup_removed:
        log.info(f"On-demand eval: cross-run dedup removed {dedup_removed} likely reposts")
    log.info(f"On-demand eval: {len(unevaluated)} new jobs to evaluate (of {len(all_rows)} recent)")

    jobs = []
    for r in unevaluated:
        j = JobListing(
            title=r["title"],
            company=r["company"],
            location=r["location"],
            url=r["url"],
            source=r["source"],
            description=r.get("description") or "",
            salary=r.get("salary") or "",
            date_posted=r.get("date_posted") or "",
            date_scraped=r.get("date_scraped") or datetime.now().isoformat(),
            tier=r.get("tier") or "",
        )
        j.job_id = r["job_id"]  # preserve original job_id, don't recompute
        jobs.append(j)
    return jobs


def run_evaluate_for_user(config: dict, user_id: str, days: int = 60):
    """
    On-demand evaluation pipeline for a single user.
    Fetches last `days` days of jobs not yet evaluated, scores them, syncs results.
    Updates user_profiles.eval_status throughout.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")

    if not supabase_url or not supabase_key:
        log.error("On-demand eval: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        return

    console.print(f"\n[bold cyan]On-demand evaluation for user {user_id[:8]}…[/bold cyan]")
    eval_started_at = datetime.utcnow().isoformat() + "Z"
    _set_eval_status(supabase_url, supabase_key, user_id, "running")

    try:
        # Fetch user profile
        users = fetch_users_with_profiles(supabase_url, supabase_key)
        user = next((u for u in users if u["user_id"] == user_id), None)
        if not user:
            log.error(f"On-demand eval: user {user_id[:8]}… not found or has no primary resume")
            _set_eval_status(supabase_url, supabase_key, user_id, "error")
            return

        # Build user-specific config — all personal data isolated per user
        user_config = dict(config)
        user_config["candidate_context"] = build_user_context(
            user, config_context=config.get("candidate_context", ""),
        )
        if user.get("home_city"):
            user_config["home_city"] = user["home_city"]
        if user.get("current_income"):
            user_config["current_income"] = user["current_income"]
        if user.get("city_profiles"):
            user_config["city_profiles"] = user["city_profiles"]

        resume_path = download_resume_for_user(
            config, user["user_id"], user["resume_file_path"], user["resume_file_name"],
        )
        if not resume_path:
            log.error(f"On-demand eval: could not download resume for {user_id[:8]}…")
            _set_eval_status(supabase_url, supabase_key, user_id, "error")
            return
        user_config["resume_path"] = str(resume_path)

        resume_text = load_resume(user_config)
        if not resume_text:
            log.error(f"On-demand eval: could not read resume for {user_id[:8]}…")
            _set_eval_status(supabase_url, supabase_key, user_id, "error")
            return

        # Fetch jobs not yet evaluated for this user (pass target_roles for rescue path)
        jobs = fetch_recent_jobs_for_user(
            supabase_url, supabase_key, user_id, days=days,
            target_roles=user.get("target_roles") or [],
        )
        if not jobs:
            console.print("[dim]No new jobs to evaluate — all recent jobs already scored.[/dim]")
            _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=0)
            return

        # Pre-eval expired check: verify URLs are still live before wasting LLM credits
        jobs, expired_count = _check_expired_before_eval(jobs, supabase_url, supabase_key)
        if expired_count:
            console.print(f"[dim]Expired check: removed {expired_count} expired listings before evaluation[/dim]")
        if not jobs:
            console.print("[dim]All candidate jobs have expired — nothing to evaluate.[/dim]")
            _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=0)
            return

        # Per-user pre-filter: skip jobs that don't match target_roles
        relevant_jobs, skipped_jobs = user_prefilter(jobs, user)

        if skipped_jobs:
            console.print(
                f"[dim]Per-user pre-filter: {len(skipped_jobs)} jobs skipped "
                f"(don't match target roles), {len(relevant_jobs)} sent to LLM[/dim]"
            )
            # Batch-write auto-evaluations for skipped jobs
            headers = _supabase_headers(supabase_key)
            skip_rows = [{
                "user_id": user_id,
                "job_id": j.job_id,
                "match_score": 0,
                "match_verdict": "WEAK",
                "match_reasoning": "Auto-filtered: job title/description doesn't match your target roles",
            } for j in skipped_jobs]
            # Upsert in batches of 200
            for i in range(0, len(skip_rows), 200):
                batch = skip_rows[i:i + 200]
                try:
                    requests.post(
                        f"{supabase_url}/rest/v1/user_evaluations?on_conflict=user_id,job_id",
                        headers={**headers, "Prefer": "resolution=merge-duplicates"},
                        json=batch,
                        timeout=30,
                    )
                except Exception as e:
                    log.warning(f"Auto-eval upsert failed for batch {i}: {e}")

        jobs = relevant_jobs
        if not jobs:
            console.print("[dim]All jobs were filtered by per-user pre-filter — nothing to evaluate.[/dim]")
            _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=0)
            return

        _set_eval_status(supabase_url, supabase_key, user_id, "running", job_count=len(jobs))

        # Evaluate — stream each result to Supabase immediately as it completes
        evaluator = ResumeEvaluator(config=user_config, resume_text=resume_text, user_id=user_id)
        evaluator.cache_path = SCRIPT_DIR / f"eval_cache_{user_id[:8]}.json"
        headers = _supabase_headers(supabase_key)

        def _progress(done: int):
            _set_eval_status(supabase_url, supabase_key, user_id, "running", jobs_done=done)

        def _on_job_complete(job: JobListing):
            try:
                requests.post(
                    f"{supabase_url}/rest/v1/user_evaluations?on_conflict=user_id,job_id",
                    headers={**headers, "Prefer": "resolution=merge-duplicates"},
                    json=[{
                        "user_id": user_id,
                        "job_id": job.job_id,
                        "match_score": job.match_score,
                        "match_verdict": job.match_verdict,
                        "match_reasoning": (job.match_reasoning or "")[:500] or None,
                        "job_summary": job.job_summary or None,
                        "full_evaluation": job.full_evaluation or None,
                    }],
                    timeout=15,
                )
            except Exception as e:
                log.warning(f"Streaming upsert failed for {job.job_id}: {e}")

        def _cancel_check() -> bool:
            return _is_cancel_requested(supabase_url, supabase_key, user_id, eval_started_at)

        evaluated_jobs = evaluator.evaluate_batch(
            jobs, fetch_descriptions=True,
            progress_callback=_progress, on_job_complete=_on_job_complete,
            cancel_check=_cancel_check,
        )

        scored = [j for j in evaluated_jobs if j.match_verdict]

        if getattr(evaluator, '_was_cancelled', False):
            console.print(f"\n[bold yellow]Evaluation cancelled: {len(scored)} jobs scored for user {user_id[:8]}…[/bold yellow]")
            _set_eval_status(supabase_url, supabase_key, user_id, "cancelled", job_count=len(scored), jobs_done=len(scored))
        else:
            console.print(f"\n[bold green]On-demand eval complete: {len(scored)} jobs scored for user {user_id[:8]}…[/bold green]")
            _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=len(scored))

    except Exception as e:
        log.error(f"On-demand eval failed for {user_id[:8]}…: {e}")
        _set_eval_status(supabase_url, supabase_key, user_id, "error")


# fetch_descriptions_batch, _fetch_desc_for_job, and backfill_missing_descriptions
# have been extracted to pipeline/scrapers/descriptions.py.
# They are imported above for backward compatibility.





def main():
    parser = argparse.ArgumentParser(description="Job Search Automation Pipeline")
    parser.add_argument("--quick", action="store_true", help="Quick scan (SerpAPI + Indeed only)")
    parser.add_argument("--evaluate-only", action="store_true", help="Re-evaluate existing results")
    parser.add_argument("--no-evaluate", action="store_true", help="Scrape only, skip LLM scoring")
    parser.add_argument("--schedule", action="store_true", help="Run on configured schedule")
    parser.add_argument(
        "--benchmark", action="store_true",
        help="Run multiple models against a sample of jobs to compare quality and cost",
    )
    parser.add_argument("--no-deep", action="store_true", help="Skip deep evaluation of STRONG matches")
    parser.add_argument("--jobspy-only", action="store_true", help="Only scrape via JobSpy (skip SerpAPI/Indeed/AVIXA/career pages)")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape + store descriptions + pre-filter only (no LLM evaluation)")
    parser.add_argument("--evaluate-for-user", metavar="USER_ID", help="On-demand: evaluate last 60 days of jobs for a specific user UUID")
    args = parser.parse_args()

    config = load_config()

    # Auto-cleanup results older than 30 days
    cleanup_old_results(max_age_days=30)

    console.print("[bold blue]═══════════════════════════════════════[/bold blue]")
    console.print("[bold blue]  Job Search Automation Pipeline[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════[/bold blue]\n")

    if args.evaluate_for_user:
        run_evaluate_for_user(config, args.evaluate_for_user)
        return

    if args.scrape_only:
        console.print("[bold]Scrape-only mode: scraping + descriptions + pre-filter (no LLM evaluation)[/bold]\n")
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Inject user-derived queries + locations into config (Fix 1/5)
        supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
        if supabase_url and supabase_key:
            users = fetch_users_with_profiles(supabase_url, supabase_key)
            if users:
                extra_groups, extra_indeed, extra_locations = generate_user_derived_queries(config, users)
                # Merge extra query groups into config (BrightData will run these; SerpAPI skips them)
                if extra_groups:
                    config.setdefault("queries", {}).update(extra_groups)
                # Append extra Indeed queries
                if extra_indeed:
                    config.setdefault("indeed", {}).setdefault("queries", []).extend(extra_indeed)
                # Store extra locations for injection into free sources
                if extra_locations:
                    config["_user_locations"] = extra_locations
                    # Inject into niche query groups that have limited location coverage
                    for group_name in ("lighting_video", "show_control_staging",
                                       "broadcast_studio", "rf_playback_install",
                                       "venue_replay_scenic"):
                        group = config.get("queries", {}).get(group_name)
                        if isinstance(group, dict) and group.get("locations"):
                            existing = set(group["locations"])
                            for loc in extra_locations:
                                if loc not in existing:
                                    group["locations"].append(loc)

        _update_scrape_stage(config, date_str, "scraping")
        jobs = run_scrape(config, quick=args.quick)
        if jobs:
            # Fetch descriptions for new jobs
            _update_scrape_stage(config, date_str, "fetching_descriptions")
            fetch_descriptions_batch(jobs, max_workers=8)
            desc_stats = {
                "with_description": sum(1 for j in jobs if j.description),
                "missing_description": sum(1 for j in jobs if not j.description),
            }
            # Sync raw catalog to Supabase
            _update_scrape_stage(config, date_str, "syncing")
            new_count = sync_scrape_results(config, jobs, date_str)
            # Backfill descriptions for previously failed jobs in DB
            backfilled = backfill_missing_descriptions(config, max_jobs=200)
            # Run pre-filter (keyword + optional cheap LLM)
            _update_scrape_stage(config, date_str, "pre_filtering")
            pf_stats = run_pre_filter(config, jobs)
            # Re-filter previously-killed jobs that now have descriptions (from backfill)
            if backfilled:
                refilter_backfilled_jobs(config)
            # Check for expired listings
            _update_scrape_stage(config, date_str, "checking_expired")
            checked, expired = check_expired_listings(config, sample_size=100)
            # Update scrape_run with pre-filter stats + expired counts + mark complete
            supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
            supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
            if supabase_url and supabase_key:
                try:
                    requests.patch(
                        f"{supabase_url}/rest/v1/scrape_runs?run_date=eq.{date_str}",
                        headers={**_supabase_headers(supabase_key), "Prefer": "return=minimal"},
                        json={
                            "expired_checked": checked,
                            "expired_found": expired,
                            "pre_filter_stats": {**(pf_stats or {}), "desc_stats": desc_stats},
                            "current_stage": "complete",
                        },
                        timeout=30,
                    )
                except Exception as e:
                    log.warning(f"Could not update scrape_run with stats: {e}")

            # Save results locally too
            json_path, csv_path, md_path = save_results(jobs)
            console.print(f"\n[bold green]Scrape-only complete:[/bold green]")
            console.print(f"  Total scraped: {len(jobs)} ({new_count} new)")
            console.print(f"  Descriptions: {desc_stats['with_description']}/{len(jobs)} populated, {desc_stats['missing_description']} missing")
            if pf_stats:
                console.print(f"  Pre-filter: {pf_stats.get('passed', 0)} passed, {pf_stats.get('failed', 0)} filtered")
            console.print(f"  Expired: {expired}/{checked} checked")
            # Write run_metadata.json for downstream scripts
            metadata = {
                "date": date_str,
                "results_dir": str(RESULTS_DIR / date_str),
                "total_jobs": len(jobs),
                "new_jobs": new_count,
                "mode": "scrape_only",
                "pre_filter_stats": pf_stats or {},
                "desc_stats": desc_stats,
                "expired_checked": checked,
                "expired_found": expired,
            }
            metadata_path = SCRIPT_DIR / "run_metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        else:
            _update_scrape_stage(config, date_str, "complete")
            console.print("[yellow]No job listings found. Check your config and API keys.[/yellow]")
        return

    if args.schedule:
        run_scheduled(config)
        return

    if args.benchmark:
        run_benchmark(config)
        return

    if args.evaluate_only:
        jobs = load_previous_results()
        if not jobs:
            console.print("[red]No previous results found in data/ directory[/red]")
            return
        console.print(f"Loaded {len(jobs)} listings from previous scan")
    elif args.jobspy_only:
        console.print("[bold]Running JobSpy only (skipping SerpAPI/Indeed/AVIXA/career pages)...[/bold]\n")
        jobspy_scraper = JobSpyScraper()
        jobs = deduplicate_jobs(jobspy_scraper.run_all_queries(config))
    else:
        jobs = run_scrape(config, quick=args.quick)

    new_job_ids = set()
    if not args.no_evaluate and jobs:
        jobs, new_job_ids = run_evaluate(config, jobs)

    if jobs:
        json_path, csv_path, md_path = save_results(jobs)
        print_summary(jobs)
        console.print(f"\n[bold green]Results saved:[/bold green]")
        console.print(f"  📊 CSV:      {csv_path}")
        console.print(f"  📝 Markdown: {md_path}")
        console.print(f"  💾 Raw JSON: {json_path}")

        # Write run metadata for downstream scripts (email_sender, build_site)
        date_str = datetime.now().strftime("%Y-%m-%d")
        verdict_counts = {}
        for j in jobs:
            v = j.match_verdict or "UNSCORED"
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
        metadata = {
            "date": date_str,
            "results_dir": str(RESULTS_DIR / date_str),
            "total_jobs": len(jobs),
            "evaluated": len([j for j in jobs if j.match_verdict]),
            "verdicts": verdict_counts,
            "new_job_ids": sorted(new_job_ids),
        }
        metadata_path = SCRIPT_DIR / "run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        log.info(f"Run metadata saved to {metadata_path}")

        # Sync to Supabase — multi-user or single-user path
        supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
        users = fetch_users_with_profiles(supabase_url, supabase_key) if supabase_url else []

        if users:
            # Multi-user: evaluate + sync per user against their own resume
            # Uses incremental sync — each job is pushed to Supabase as it completes
            from copy import deepcopy
            for user in users:
                uid = user["user_id"]
                console.print(f"\n[bold cyan]── User {uid[:8]}… ──[/bold cyan]")

                user_config = dict(config)
                # Build user-specific config — all personal data isolated per user
                user_config["candidate_context"] = build_user_context(
                    user, config_context=config.get("candidate_context", ""),
                )
                if user.get("home_city"):
                    user_config["home_city"] = user["home_city"]
                if user.get("current_income"):
                    user_config["current_income"] = user["current_income"]
                if user.get("city_profiles"):
                    user_config["city_profiles"] = user["city_profiles"]

                resume_path = download_resume_for_user(
                    config, uid,
                    user["resume_file_path"], user["resume_file_name"],
                )
                if not resume_path:
                    log.warning(f"Multi-user: skipping user {uid[:8]}… — resume download failed")
                    continue
                user_config["resume_path"] = str(resume_path)

                resume_text = load_resume(user_config)
                if not resume_text:
                    log.warning(f"Multi-user: skipping user {uid[:8]}… — could not read resume")
                    continue

                # Create run record upfront so incremental syncs can reference it
                sources = sorted(set(j.source for j in jobs))
                run_id = _upsert_run_record(supabase_url, supabase_key, uid, date_str, len(jobs), sources)

                # Set eval status to running
                _set_eval_status(supabase_url, supabase_key, uid, "running", job_count=len(jobs))

                evaluator = ResumeEvaluator(config=user_config, resume_text=resume_text)
                evaluator.cache_path = SCRIPT_DIR / f"eval_cache_{uid[:8]}.json"

                # Track which jobs were synced via callback to avoid double-syncing
                synced_job_ids: set[str] = set()

                def _on_job_complete(job: JobListing, _uid=uid, _run_id=run_id):
                    if _run_id and job.match_verdict:
                        _sync_single_job(supabase_url, supabase_key, _uid, _run_id, date_str, job)
                        synced_job_ids.add(job.job_id)

                jobs_done_counter = [0]
                def _progress(done: int, _uid=uid):
                    jobs_done_counter[0] = done
                    if done % 5 == 0 or done == len(jobs):
                        _set_eval_status(supabase_url, supabase_key, _uid, "running", jobs_done=done)

                user_jobs = evaluator.evaluate_batch(
                    deepcopy(jobs), fetch_descriptions=True,
                    on_job_complete=_on_job_complete, progress_callback=_progress,
                )
                user_new_ids = evaluator.new_job_ids

                # Batch-sync any evaluated jobs that weren't sent via callback (e.g. from cache)
                if run_id:
                    missed = [j for j in user_jobs if j.match_verdict and j.job_id not in synced_job_ids]
                    for j in missed:
                        _sync_single_job(supabase_url, supabase_key, uid, run_id, date_str, j)

                    # Update run record with final verdict counts + new_job_ids
                    _update_run_record(supabase_url, supabase_key, run_id, user_jobs, user_new_ids)

                _set_eval_status(supabase_url, supabase_key, uid, "completed", job_count=len([j for j in user_jobs if j.match_verdict]))

                if not args.no_deep and not args.no_evaluate:
                    run_deep_evaluation(user_config, user_jobs)
                    sync_deep_evals_for_user(config, user_jobs, uid)
        else:
            # Single-user backward-compat path
            sync_to_supabase(config, jobs, new_job_ids, metadata)

            if not args.no_deep and not args.no_evaluate:
                run_deep_evaluation(config, jobs)
                sync_deep_evals(config, jobs)
    else:
        console.print("[yellow]No job listings found. Check your config and API keys.[/yellow]")



def run_scheduled(config: dict):
    """Run on a schedule defined in config."""
    import sched
    import threading

    schedule_config = config.get("schedule", {})
    console.print("[bold]Running in scheduled mode. Press Ctrl+C to stop.[/bold]")
    console.print(f"  Full scan: {schedule_config.get('full_scan', 'weekly')}")
    console.print(f"  Quick scan: {schedule_config.get('quick_scan', 'daily')}")

    while True:
        try:
            console.print(f"\n[dim]Running quick scan at {datetime.now()}...[/dim]")
            jobs = run_scrape(config, quick=True)
            if jobs:
                jobs = run_evaluate(config, jobs)
                save_results(jobs)
                print_summary(jobs)

            # Sleep until next run (24h for daily quick scan)
            next_run = 24 * 60 * 60
            console.print(f"[dim]Next scan in {next_run // 3600} hours[/dim]")
            time.sleep(next_run)
        except KeyboardInterrupt:
            console.print("\n[bold]Scheduler stopped.[/bold]")
            break


if __name__ == "__main__":
    main()
