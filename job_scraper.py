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
from pipeline.orchestrator import (
    generate_user_derived_queries, run_evaluate, run_deep_evaluation,
    build_user_context, fetch_recent_jobs_for_user, run_evaluate_for_user,
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
# NOTE: Pipeline orchestration functions (generate_user_derived_queries,
# run_evaluate, run_deep_evaluation, build_user_context,
# fetch_recent_jobs_for_user, run_evaluate_for_user) have been extracted
# to pipeline/orchestrator.py.
# They are imported above for backward compatibility.
# ---------------------------------------------------------------------------





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
