"""Multi-user Supabase sync: profiles, per-user eval sync, status tracking."""

import os
from datetime import datetime
from typing import Optional

import requests

from pipeline.config import log, RESULTS_DIR
from pipeline.models import JobListing
from pipeline.sync.client import _supabase_headers


def fetch_users_with_profiles(supabase_url: str, supabase_key: str) -> list[dict]:
    """
    Return a list of active users who have a primary resume set.
    Each dict: {user_id, notify_email, candidate_context, target_roles,
                target_locations, home_city, current_income, city_profiles,
                resume_file_path, resume_file_name}
    Users without a primary resume are skipped.
    """
    if not supabase_url or not supabase_key:
        return []
    headers = _supabase_headers(supabase_key)
    try:
        # Fetch all user profiles
        resp = requests.get(
            f"{supabase_url}/rest/v1/user_profiles?select=*",
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        profiles = resp.json()

        # Fetch primary resumes
        resp2 = requests.get(
            f"{supabase_url}/rest/v1/resumes?is_primary=eq.true&select=user_id,file_path,file_name",
            headers=headers, timeout=15,
        )
        resp2.raise_for_status()
        resumes_by_user = {r["user_id"]: r for r in resp2.json()}

        # Find the admin's city_profiles to use as a global fallback for users
        # who haven't set their own. City cost data is objective and shared.
        global_city_profiles = {}
        for profile in profiles:
            cp = profile.get("city_profiles") or {}
            if cp:
                global_city_profiles = cp
                break  # Use first non-empty set found (admin is first in practice)

        users = []
        for profile in profiles:
            uid = profile["user_id"]
            resume = resumes_by_user.get(uid)
            if not resume:
                log.info(f"Multi-user: skipping user {uid[:8]}... -- no primary resume")
                continue
            city_profiles = profile.get("city_profiles") or {}
            users.append({
                "user_id": uid,
                "notify_email": profile.get("notify_email"),
                "candidate_context": profile.get("candidate_context"),
                "target_roles": profile.get("target_roles", []),
                "target_locations": profile.get("target_locations", []),
                "home_city": profile.get("home_city") or "",
                "current_income": profile.get("current_income") or 0,
                # Fall back to global dataset if user has no city profiles
                "city_profiles": city_profiles or global_city_profiles,
                "resume_file_path": resume["file_path"],
                "resume_file_name": resume["file_name"],
            })
        log.info(f"Multi-user: found {len(users)} user(s) with primary resume")
        return users
    except Exception as e:
        log.warning(f"Multi-user: could not fetch user profiles ({e}) -- falling back to single-user mode")
        return []


def _upsert_run_record(
    supabase_url: str,
    key: str,
    user_id: str,
    date_str: str,
    total_jobs: int,
    sources: list[str],
) -> Optional[str]:
    """Create/upsert a run record upfront and return its run_id."""
    headers = _supabase_headers(key)
    run_payload = {
        "run_date": date_str,
        "user_id": user_id,
        "total_jobs": total_jobs,
        "evaluated": 0,
        "strong_count": 0,
        "moderate_count": 0,
        "stretch_count": 0,
        "weak_count": 0,
        "new_job_ids": [],
        "sources": sources,
    }
    try:
        resp = requests.post(
            f"{supabase_url}/rest/v1/runs?on_conflict=user_id,run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=run_payload, timeout=30,
        )
        resp.raise_for_status()
        run_id = resp.json()[0]["id"]
        log.info(f"Incremental sync: upserted run {date_str} for user {user_id[:8]}... -> {run_id}")
        return run_id
    except Exception as e:
        log.error(f"Incremental sync: failed to upsert run record for {user_id[:8]}...: {e}")
        return None


def _sync_single_job(
    supabase_url: str,
    key: str,
    user_id: str,
    run_id: str,
    date_str: str,
    job: "JobListing",
):
    """Upsert one job across jobs + user_evaluations + run_jobs. Thread-safe."""
    headers = _supabase_headers(key)
    try:
        # 1. Upsert catalog job record
        job_record = {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "location": job.location or "Unknown",
            "url": job.url or "",
            "source": job.source,
            "salary": job.salary or None,
            "date_posted": job.date_posted or None,
            "tier": job.tier or None,
            "first_seen_run": run_id,
            "last_seen_run": run_id,
            "first_seen_date": date_str,
            "last_seen_date": date_str,
            "date_scraped": job.date_scraped,
        }
        if job.description:
            job_record["description"] = job.description[:50000]
            job_record["description_length"] = len(job.description)
        requests.post(
            f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
            headers={**headers, "Prefer": "resolution=merge-duplicates"},
            json=[job_record],
            timeout=15,
        ).raise_for_status()

        # 2. Upsert user_evaluation
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
        ).raise_for_status()

        # 3. Insert run_jobs junction (is_new_this_run set to False initially)
        requests.post(
            f"{supabase_url}/rest/v1/run_jobs?on_conflict=run_id,job_id_ref",
            headers={**headers, "Prefer": "resolution=ignore-duplicates"},
            json=[{
                "run_id": run_id,
                "job_id_ref": job.job_id,
                "is_new_this_run": False,
            }],
            timeout=15,
        ).raise_for_status()

    except Exception as e:
        log.warning(f"Incremental sync: failed for job {job.job_id}: {e}")


def _update_run_record(
    supabase_url: str,
    key: str,
    run_id: str,
    user_jobs: list["JobListing"],
    new_job_ids: set,
):
    """PATCH run with final verdict counts + new_job_ids after batch completes."""
    headers = _supabase_headers(key)
    verdict_counts: dict[str, int] = {}
    for j in user_jobs:
        v = j.match_verdict or "UNSCORED"
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    evaluated = [j for j in user_jobs if j.match_verdict]
    try:
        requests.patch(
            f"{supabase_url}/rest/v1/runs?id=eq.{run_id}",
            headers={**headers, "Prefer": "return=minimal"},
            json={
                "evaluated": len(evaluated),
                "strong_count": verdict_counts.get("STRONG", 0),
                "moderate_count": verdict_counts.get("MODERATE", 0),
                "stretch_count": verdict_counts.get("STRETCH", 0),
                "weak_count": verdict_counts.get("WEAK", 0),
                "new_job_ids": sorted(new_job_ids),
            },
            timeout=30,
        ).raise_for_status()
        log.info(f"Incremental sync: updated run {run_id} with final counts")

        # Batch-update is_new_this_run for new jobs
        if new_job_ids:
            BATCH = 100
            sorted_ids = sorted(new_job_ids)
            for i in range(0, len(sorted_ids), BATCH):
                batch_ids = sorted_ids[i:i + BATCH]
                id_filter = ",".join(batch_ids)
                requests.patch(
                    f"{supabase_url}/rest/v1/run_jobs?run_id=eq.{run_id}&job_id_ref=in.({id_filter})",
                    headers={**headers, "Prefer": "return=minimal"},
                    json={"is_new_this_run": True},
                    timeout=30,
                ).raise_for_status()
            log.info(f"Incremental sync: marked {len(new_job_ids)} jobs as new_this_run")

    except Exception as e:
        log.error(f"Incremental sync: failed to update run {run_id}: {e}")


def sync_to_supabase_for_user(
    config: dict,
    jobs: list[JobListing],
    user_id: str,
    new_job_ids: set,
    metadata: dict,
):
    """
    Upsert run + catalog jobs + user_evaluations for a single user.
    Evaluation fields go into user_evaluations, not jobs.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)
    date_str = metadata["date"]
    verdict_counts = metadata.get("verdicts", {})
    BATCH = 100

    try:
        # 1. Upsert run (scoped to this user)
        run_payload = {
            "run_date": date_str,
            "user_id": user_id,
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
        log.info(f"Multi-user: upserted run {date_str} for user {user_id[:8]}... -> {run_id}")

        # 2. Upsert catalog-only job records (no eval fields)
        evaluated = [j for j in jobs if j.match_verdict]
        for i in range(0, len(evaluated), BATCH):
            batch = evaluated[i:i + BATCH]
            catalog_records = [{
                "job_id": j.job_id,
                "title": j.title,
                "company": j.company,
                "location": j.location or "Unknown",
                "url": j.url or "",
                "source": j.source,
                "salary": j.salary or None,
                "date_posted": j.date_posted or None,
                "tier": j.tier or None,
                "first_seen_run": run_id,
                "last_seen_run": run_id,
                "first_seen_date": date_str,
                "last_seen_date": date_str,
                "date_scraped": j.date_scraped,
            } for j in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=catalog_records, timeout=60,
            )
            resp.raise_for_status()

        # 3. Upsert user_evaluations
        for i in range(0, len(evaluated), BATCH):
            batch = evaluated[i:i + BATCH]
            eval_records = [{
                "user_id": user_id,
                "job_id": j.job_id,
                "match_score": j.match_score,
                "match_verdict": j.match_verdict,
                "match_reasoning": (j.match_reasoning or "")[:500] or None,
                "job_summary": j.job_summary or None,
                "full_evaluation": j.full_evaluation or None,
            } for j in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/user_evaluations?on_conflict=user_id,job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=eval_records, timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Multi-user: upserted {len(evaluated)} jobs + evals for user {user_id[:8]}...")

        # 4. Insert run_jobs junction rows
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

        log.info(f"Multi-user: sync complete for user {user_id[:8]}... (run {run_id})")

    except Exception as e:
        log.error(f"Multi-user: Supabase sync failed for user {user_id[:8]}...: {e}")


def sync_deep_evals_for_user(config: dict, jobs: list[JobListing], user_id: str):
    """Patch deep_evaluation in user_evaluations for STRONG jobs after deep eval pass."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)
    strong_with_deep = [j for j in jobs if j.match_verdict == "STRONG" and j.full_evaluation]

    date_str = datetime.now().strftime("%Y-%m-%d")
    deep_dir = RESULTS_DIR / date_str / "strong" / "deep"
    if not deep_dir.exists():
        return

    updated = 0
    for md_path in deep_dir.glob("*.md"):
        try:
            deep_text = md_path.read_text()
            stem = md_path.stem.lower()
            matched = next(
                (j for j in strong_with_deep if stem.startswith(j.company.lower()[:10].replace(" ", "_"))),
                None,
            )
            if not matched:
                continue
            resp = requests.patch(
                f"{supabase_url}/rest/v1/user_evaluations"
                f"?user_id=eq.{user_id}&job_id=eq.{matched.job_id}",
                headers={**headers, "Prefer": "return=minimal"},
                json={"deep_evaluation": deep_text}, timeout=30,
            )
            resp.raise_for_status()
            updated += 1
        except Exception as e:
            log.warning(f"Multi-user: could not sync deep eval for {md_path.name}: {e}")

    if updated:
        log.info(f"Multi-user: synced {updated} deep evals for user {user_id[:8]}...")


def _set_eval_status(supabase_url: str, supabase_key: str, user_id: str, status: str, job_count: int = None, jobs_done: int = None):
    """Update user_profiles.eval_status for a given user."""
    if not supabase_url or not supabase_key:
        return
    headers = _supabase_headers(supabase_key)
    payload = {"eval_status": status}
    if status == "running" and job_count is None and jobs_done is None:
        # Initial "running" call: reset everything for a fresh eval
        payload["eval_started_at"] = datetime.utcnow().isoformat() + "Z"
        payload["eval_completed_at"] = None
        payload["eval_job_count"] = None
        payload["eval_jobs_done"] = 0
    elif status in ("completed", "error", "cancelled"):
        payload["eval_completed_at"] = datetime.utcnow().isoformat() + "Z"
    if job_count is not None:
        payload["eval_job_count"] = job_count
    if jobs_done is not None:
        payload["eval_jobs_done"] = jobs_done
    try:
        requests.patch(
            f"{supabase_url}/rest/v1/user_profiles?user_id=eq.{user_id}",
            headers={**headers, "Prefer": "return=minimal"},
            json=payload, timeout=15,
        ).raise_for_status()
    except Exception as e:
        log.warning(f"Could not update eval_status for {user_id[:8]}...: {e}")


def _is_cancel_requested(supabase_url: str, supabase_key: str, user_id: str, eval_started_at: str) -> bool:
    """Check if a cancellation has been requested for this evaluation run."""
    if not supabase_url or not supabase_key:
        return False
    try:
        headers = _supabase_headers(supabase_key)
        resp = requests.get(
            f"{supabase_url}/rest/v1/user_profiles?user_id=eq.{user_id}&select=eval_cancel_requested_at",
            headers=headers, timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return False
        cancel_at = rows[0].get("eval_cancel_requested_at")
        if not cancel_at:
            return False
        # Cancel is valid if it was requested after the current eval started
        # Simple string comparison works for ISO 8601 timestamps in UTC
        return cancel_at > eval_started_at
    except Exception as e:
        log.debug(f"Cancel check failed for {user_id[:8]}...: {e}")
        return False
