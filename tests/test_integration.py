"""Final integration checks after refactor is complete."""
import subprocess
import sys


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "job_scraper.py", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Job Search Automation Pipeline" in result.stdout


def test_pipeline_package_importable():
    result = subprocess.run(
        [sys.executable, "-c",
         "from pipeline import JobListing, load_config, ResumeEvaluator, "
         "resolve_model, deduplicate_jobs, run_scrape, run_evaluate, "
         "run_benchmark; print('OK')"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_job_scraper_backward_compat():
    result = subprocess.run(
        [sys.executable, "-c",
         "from job_scraper import JobListing, load_config, ResumeEvaluator; print('OK')"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0


def test_test_deep_eval_imports():
    result = subprocess.run(
        [sys.executable, "-c", "import test_deep_eval; print('OK')"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0


def test_test_resume_tailor_imports():
    result = subprocess.run(
        [sys.executable, "-c", "import test_resume_tailor_shootout; print('OK')"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
