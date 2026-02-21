"""Verify the public API surface of job_scraper and pipeline are preserved after refactor."""
import importlib


# Library API — everything the pipeline package should export
PIPELINE_PUBLIC_API = {
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
}

# CLI entrypoint — job_scraper.py re-exports everything from pipeline plus `main`
JOB_SCRAPER_PUBLIC_API = PIPELINE_PUBLIC_API | {"main"}


def test_job_scraper_exports_public_api():
    """All required names must be importable from job_scraper (library + CLI)."""
    mod = importlib.import_module("job_scraper")
    missing = JOB_SCRAPER_PUBLIC_API - set(dir(mod))
    assert not missing, f"Missing from job_scraper: {missing}"


def test_pipeline_exports_public_api():
    """All library names must be importable from pipeline (no CLI `main`)."""
    mod = importlib.import_module("pipeline")
    missing = PIPELINE_PUBLIC_API - set(dir(mod))
    assert not missing, f"Missing from pipeline: {missing}"


def test_external_script_imports():
    """Verify the specific import patterns used by test_deep_eval.py and test_resume_tailor_shootout.py."""
    from pipeline import load_config, load_resume, JobListing, ResumeEvaluator, resolve_model
    assert all([load_config, load_resume, JobListing, ResumeEvaluator, resolve_model])
