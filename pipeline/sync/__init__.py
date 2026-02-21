"""Supabase sync layer: client, job catalog, user evaluations, resumes."""

from pipeline.sync.client import _supabase_headers
from pipeline.sync.resumes import download_active_resume, download_resume_for_user
from pipeline.sync.jobs import (
    sync_to_supabase,
    sync_deep_evals,
    sync_scrape_results,
    check_expired_listings,
    _check_expired_before_eval,
    _update_scrape_stage,
    cleanup_old_results,
)
from pipeline.sync.users import (
    fetch_users_with_profiles,
    _upsert_run_record,
    _sync_single_job,
    _update_run_record,
    sync_to_supabase_for_user,
    sync_deep_evals_for_user,
    _set_eval_status,
    _is_cancel_requested,
)
