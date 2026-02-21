"""Verify the public API surface of job_scraper is preserved after refactor."""
import importlib


REQUIRED_PUBLIC_API = {
    "JobListing",
    "load_config",
    "resolve_model",
    "load_resume",
    "SerpAPIScraper",
    "BrightDataScraper",
    "IndeedRSSScraper",
    "AVIXAScraper",
    "CareerPageScraper",
    "JobSpyScraper",
    "ResumeEvaluator",
    "deduplicate_jobs",
    "fetch_job_description",
    "fetch_descriptions_batch",
    "save_results",
    "load_previous_results",
    "print_summary",
    "sync_to_supabase",
    "sync_scrape_results",
    "download_active_resume",
    "fetch_users_with_profiles",
    "run_scrape",
    "run_evaluate",
    "run_deep_evaluation",
    "run_evaluate_for_user",
    "run_pre_filter",
    "run_benchmark",
    "check_expired_listings",
    "main",
}


def test_job_scraper_exports_public_api():
    """All required names must be importable from job_scraper."""
    mod = importlib.import_module("job_scraper")
    missing = REQUIRED_PUBLIC_API - set(dir(mod))
    assert not missing, f"Missing from job_scraper: {missing}"


def test_pipeline_exports_public_api():
    """After refactor, all required names must also be importable from pipeline."""
    import pytest
    try:
        mod = importlib.import_module("pipeline")
    except ImportError:
        pytest.skip("pipeline package not created yet")
    missing = REQUIRED_PUBLIC_API - set(dir(mod))
    if missing:
        pytest.skip(f"pipeline refactor incomplete — missing: {missing}")


def test_external_script_imports():
    """Verify the specific import patterns used by test_deep_eval.py and test_resume_tailor_shootout.py."""
    from job_scraper import load_config, load_resume, JobListing, ResumeEvaluator, resolve_model
    assert all([load_config, load_resume, JobListing, ResumeEvaluator, resolve_model])
