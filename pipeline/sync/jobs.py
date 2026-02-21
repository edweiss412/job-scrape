"""Supabase sync for job catalog, scrape runs, expired listings, and cleanup."""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

from pipeline.config import console, log, SCRIPT_DIR, DATA_DIR, RESULTS_DIR
from pipeline.models import JobListing
from pipeline.sync.client import _supabase_headers


def sync_to_supabase(config: dict, jobs: list[JobListing], new_job_ids: set, metadata: dict):
    """
    Upsert this run's evaluated jobs into Supabase via REST API.
    No-op if SUPABASE_URL is not set.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        log.info("Supabase: not configured -- skipping sync")
        return

    headers = _supabase_headers(supabase_key)
    date_str = metadata["date"]
    verdict_counts = metadata.get("verdicts", {})

    try:
        # 1. Upsert run record
        run_payload = {
            "run_date": date_str,
            "total_jobs": metadata["total_jobs"],
            "evaluated": metadata["evaluated"],
            "strong_count": verdict_counts.get("STRONG", 0),
            "moderate_count": verdict_counts.get("MODERATE", 0),
            "stretch_count": verdict_counts.get("STRETCH", 0),
            "weak_count": verdict_counts.get("WEAK", 0),
            "new_job_ids": sorted(new_job_ids),
            "sources": sorted(set(j.source for j in jobs)),
        }
        run_resp = requests.post(
            f"{supabase_url}/rest/v1/runs?on_conflict=user_id,run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=run_payload, timeout=30,
        )
        run_resp.raise_for_status()
        run_id = run_resp.json()[0]["id"]
        log.info(f"Supabase: upserted run {date_str} -> {run_id}")

        # 2. Upsert evaluated jobs in batches
        evaluated = [j for j in jobs if j.match_verdict]
        BATCH = 100
        for i in range(0, len(evaluated), BATCH):
            batch = evaluated[i:i + BATCH]
            records = []
            for j in batch:
                rec = {
                    "job_id": j.job_id,
                    "title": j.title,
                    "company": j.company,
                    "location": j.location or "Unknown",
                    "url": j.url or "",
                    "source": j.source,
                    "salary": j.salary or None,
                    "date_posted": j.date_posted or None,
                    "tier": j.tier or None,
                    "match_score": j.match_score,
                    "match_verdict": j.match_verdict,
                    "match_reasoning": (j.match_reasoning or "")[:500] or None,
                    "job_summary": j.job_summary or None,
                    "full_evaluation": j.full_evaluation or None,
                    "first_seen_run": run_id,
                    "last_seen_run": run_id,
                    "first_seen_date": date_str,
                    "last_seen_date": date_str,
                    "date_scraped": j.date_scraped,
                }
                if j.description:
                    rec["description"] = j.description[:50000]
                    rec["description_length"] = len(j.description)
                records.append(rec)
            resp = requests.post(
                f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=records, timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Supabase: upserted {len(evaluated)} jobs")

        # 3. Insert run_jobs junction rows
        rj_records = [{
            "run_id": run_id,
            "job_id_ref": j.job_id,
            "is_new_this_run": j.job_id in new_job_ids,
        } for j in evaluated]
        for i in range(0, len(rj_records), BATCH):
            resp = requests.post(
                f"{supabase_url}/rest/v1/run_jobs?on_conflict=run_id,job_id_ref",
                headers={**headers, "Prefer": "resolution=ignore-duplicates"},
                json=rj_records[i:i + BATCH], timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Supabase: sync complete (run {run_id})")

    except Exception as e:
        log.error(f"Supabase sync failed: {e}")
        # Non-fatal -- file-based results are already saved


def sync_deep_evals(config: dict, jobs: list[JobListing]):
    """Update deep_evaluation field for STRONG jobs after deep eval pass."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)
    strong_with_deep = [j for j in jobs if j.match_verdict == "STRONG" and j.full_evaluation]

    # Read deep eval files written to disk and patch the DB
    date_str = datetime.now().strftime("%Y-%m-%d")
    deep_dir = RESULTS_DIR / date_str / "strong" / "deep"
    if not deep_dir.exists():
        return

    updated = 0
    for md_path in deep_dir.glob("*.md"):
        try:
            deep_text = md_path.read_text()
            # Match to a job by filename heuristic (company_title pattern)
            stem = md_path.stem.lower()
            matched = next(
                (j for j in strong_with_deep if stem.startswith(j.company.lower()[:10].replace(" ", "_"))),
                None,
            )
            if not matched:
                continue
            resp = requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=eq.{matched.job_id}",
                headers={**headers, "Prefer": "return=minimal"},
                json={"deep_evaluation": deep_text}, timeout=30,
            )
            resp.raise_for_status()
            updated += 1
        except Exception as e:
            log.warning(f"Supabase: could not sync deep eval for {md_path.name}: {e}")

    if updated:
        log.info(f"Supabase: synced {updated} deep evaluations")


def sync_scrape_results(config: dict, jobs: list[JobListing], date_str: str):
    """
    Sync scrape-only results to Supabase: upsert scrape_runs + batch upsert jobs catalog.
    No evaluation data, no runs/user_evaluations writes.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        log.info("Supabase: not configured -- skipping scrape sync")
        return 0

    headers = _supabase_headers(supabase_key)
    sources = sorted(set(j.source for j in jobs))

    # 1. Count how many are truly new (not yet in DB)
    existing_ids = set()
    BATCH = 500
    offset = 0
    while True:
        resp = requests.get(
            f"{supabase_url}/rest/v1/jobs?select=job_id&offset={offset}&limit={BATCH}",
            headers=headers, timeout=30,
        )
        if not resp.ok:
            break
        batch = resp.json()
        existing_ids.update(r["job_id"] for r in batch)
        if len(batch) < BATCH:
            break
        offset += BATCH

    new_count = sum(1 for j in jobs if j.job_id not in existing_ids)

    # 2. Batch upsert job catalog records (no eval data)
    BATCH = 100
    for i in range(0, len(jobs), BATCH):
        batch = jobs[i:i + BATCH]
        records = []
        for j in batch:
            rec = {
                "job_id": j.job_id,
                "title": j.title,
                "company": j.company,
                "location": j.location or "Unknown",
                "url": j.url or "",
                "source": j.source,
                "salary": j.salary or None,
                "date_posted": j.date_posted or None,
                "tier": j.tier or None,
                "first_seen_date": date_str,
                "last_seen_date": date_str,
                "date_scraped": j.date_scraped,
                "listing_status": "active",
            }
            if j.description:
                rec["description"] = j.description[:50000]
                rec["description_length"] = len(j.description)
            else:
                # No description after initial fetch -- record first attempt
                rec["description_fetch_attempts"] = 1
            if j.source_query:
                rec["source_query"] = j.source_query
            records.append(rec)
        try:
            requests.post(
                f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=records, timeout=60,
            ).raise_for_status()
        except Exception as e:
            log.warning(f"Scrape sync: batch upsert failed: {e}")

    log.info(f"Scrape sync: upserted {len(jobs)} jobs ({new_count} new)")

    # 3. Upsert scrape_runs record
    try:
        requests.post(
            f"{supabase_url}/rest/v1/scrape_runs?on_conflict=run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates"},
            json=[{
                "run_date": date_str,
                "total_scraped": len(jobs),
                "new_jobs": new_count,
                "sources": sources,
            }],
            timeout=30,
        ).raise_for_status()
        log.info(f"Scrape sync: upserted scrape_run for {date_str}")
    except Exception as e:
        log.warning(f"Scrape sync: failed to upsert scrape_run: {e}")

    return new_count


def check_expired_listings(config: dict, sample_size: int = 100):
    """
    Check a sample of active job URLs for expiry. Mark expired ones in Supabase.
    Run as part of --scrape-only after syncing new jobs.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return 0, 0

    headers = _supabase_headers(supabase_key)

    # Fetch a sample of active jobs not verified recently (oldest first)
    resp = requests.get(
        f"{supabase_url}/rest/v1/jobs"
        f"?listing_status=eq.active"
        f"&url=neq."
        f"&select=job_id,url"
        f"&order=last_verified_at.asc.nullsfirst"
        f"&limit={sample_size}",
        headers=headers, timeout=30,
    )
    if not resp.ok:
        log.warning(f"Expired check: failed to fetch jobs: {resp.status_code}")
        return 0, 0

    jobs_to_check = resp.json()
    if not jobs_to_check:
        return 0, 0

    console.print(f"[bold]Checking {len(jobs_to_check)} listings for expiry...[/bold]")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    expired_ids = []
    checked = 0

    def _check_url(job_row):
        url = job_row["url"]
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            # 404, 410 = definitely expired
            if resp.status_code in (404, 410):
                return True
            # Redirected to a generic careers/search page = likely expired
            if resp.status_code == 200 and resp.url:
                final = resp.url.lower()
                if any(p in final for p in ["/search", "/jobs?", "/careers?", "/results", "/job-not-found"]):
                    if job_row["url"].lower() not in final:
                        return True
            return False
        except Exception:
            return False  # Network errors = assume still active

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(_check_url, row): row for row in jobs_to_check}
        for future in as_completed(future_map):
            checked += 1
            row = future_map[future]
            try:
                if future.result():
                    expired_ids.append(row["job_id"])
            except Exception:
                pass

    # Batch-update verified timestamps
    all_ids = [r["job_id"] for r in jobs_to_check]
    BATCH = 50
    for i in range(0, len(all_ids), BATCH):
        batch_ids = all_ids[i:i + BATCH]
        requests.patch(
            f"{supabase_url}/rest/v1/jobs?job_id=in.({','.join(batch_ids)})",
            headers={**headers, "Prefer": "return=minimal"},
            json={"last_verified_at": now_iso},
            timeout=30,
        )

    # Mark expired
    if expired_ids:
        for i in range(0, len(expired_ids), BATCH):
            batch_ids = expired_ids[i:i + BATCH]
            requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=in.({','.join(batch_ids)})",
                headers={**headers, "Prefer": "return=minimal"},
                json={"listing_status": "expired", "listing_expired_at": now_iso},
                timeout=30,
            )
        console.print(f"  Marked {len(expired_ids)} listings as expired")

    log.info(f"Expired check: {checked} checked, {len(expired_ids)} expired")
    return checked, len(expired_ids)


def _check_expired_before_eval(jobs: list[JobListing], supabase_url: str, supabase_key: str) -> tuple[list[JobListing], int]:
    """
    Quick URL check on jobs before sending to LLM eval.
    Returns (live_jobs, expired_count). Marks expired ones in Supabase.
    """
    if not jobs:
        return jobs, 0

    console.print(f"[bold]Checking {len(jobs)} job URLs for expiry before evaluation...[/bold]")

    expired_ids = set()

    def _check(job):
        if not job.url:
            return job.job_id, False
        try:
            resp = requests.head(job.url, timeout=8, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if resp.status_code in (404, 410):
                return job.job_id, True
            if resp.status_code == 200 and resp.url:
                final = resp.url.lower()
                if any(p in final for p in ["/search", "/jobs?", "/careers?", "/results", "/job-not-found"]):
                    if job.url.lower() not in final:
                        return job.job_id, True
            return job.job_id, False
        except Exception:
            return job.job_id, False  # Network error = assume still active

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_check, j): j for j in jobs}
        for future in as_completed(futures):
            try:
                job_id, is_expired = future.result()
                if is_expired:
                    expired_ids.add(job_id)
            except Exception:
                pass

    # Mark expired in Supabase
    if expired_ids and supabase_url and supabase_key:
        headers = _supabase_headers(supabase_key)
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        BATCH = 50
        id_list = list(expired_ids)
        for i in range(0, len(id_list), BATCH):
            batch = id_list[i:i + BATCH]
            try:
                requests.patch(
                    f"{supabase_url}/rest/v1/jobs?job_id=in.({','.join(batch)})",
                    headers={**headers, "Prefer": "return=minimal"},
                    json={"listing_status": "expired", "listing_expired_at": now_iso},
                    timeout=30,
                )
            except Exception:
                pass

    live_jobs = [j for j in jobs if j.job_id not in expired_ids]
    return live_jobs, len(expired_ids)


def _update_scrape_stage(config: dict, date_str: str, stage: str):
    """Update scrape_runs.current_stage. Creates row if needed via upsert."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return
    try:
        requests.post(
            f"{supabase_url}/rest/v1/scrape_runs?on_conflict=run_date",
            headers={**_supabase_headers(supabase_key), "Prefer": "resolution=merge-duplicates"},
            json=[{"run_date": date_str, "current_stage": stage}],
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        log.warning(f"Could not update scrape stage to '{stage}': {e}")


def cleanup_old_results(max_age_days: int = 30):
    """Remove results and data older than max_age_days."""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    removed = 0

    # Clean date-based run directories (results/2026-02-16/)
    for item in RESULTS_DIR.iterdir():
        if item.is_dir() and item.name != "benchmarks":
            try:
                dir_date = datetime.strptime(item.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    shutil.rmtree(item)
                    removed += 1
                    log.info(f"Cleaned up old results: {item.name}")
            except ValueError:
                # Not a date-named directory (legacy format), check modification time
                if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                    shutil.rmtree(item)
                    removed += 1
                    log.info(f"Cleaned up old results: {item.name}")

    # Clean legacy flat files in results/ (jobs_*.csv, jobs_*.md)
    for item in RESULTS_DIR.iterdir():
        if item.is_file() and item.name.startswith("jobs_"):
            if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                item.unlink()
                removed += 1
                log.info(f"Cleaned up old file: {item.name}")

    # Clean old JSON data files
    for item in DATA_DIR.iterdir():
        if item.is_file() and item.name.startswith("jobs_"):
            if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                item.unlink()
                removed += 1
                log.info(f"Cleaned up old data: {item.name}")

    if removed:
        log.info(f"Cleanup complete: removed {removed} items older than {max_age_days} days")
