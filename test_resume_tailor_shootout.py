#!/usr/bin/env python3
"""
Resume Tailoring Model Shootout
================================
Tests the new streamlined deep_evaluate prompt (Resume Tailoring, Cover Letter,
Interview Prep) across 4 models on real STRONG jobs. Outputs each result to a
separate file for manual quality comparison.

Usage:
    export OPENROUTER_KEY=sk-or-v1-...
    python test_resume_tailor_shootout.py
"""

import json
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline import (
    JobListing, ResumeEvaluator, load_config, load_resume, resolve_model,
)

# --- Configuration ---

# Models to test (all via OpenRouter)
SHOOTOUT_MODELS = [
    ("google/gemini-3-flash-preview", "Gemini 3 Flash"),
    ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6"),
    ("google/gemini-3-pro-preview", "Gemini 3 Pro"),
    ("deepseek/deepseek-v3.2", "DeepSeek V3.2"),
]

# Jobs to test: (data_file, job_id, first_pass_eval_file)
TEST_JOBS = [
    {
        "data_file": "data/jobs_20260216_203446.json",
        "job_id": "2709b31fba1a",  # Shure Senior Pre-sales Solutions Engineer
        "eval_file": "results/2026-02-16/strong/Shure_Senior_Pre-sales_Solutions_Engineer__AV_IT__-_New_York__NY.md",
    },
    {
        "data_file": "data/jobs_20260216_202042.json",
        "job_id": "50a7a7b0a8c5",  # Voya Financial Audio Visual Engineer
        "eval_file": "results/2026-02-16/strong/Voya_Financial_Audio_Visual_Engineer.md",
    },
]

OUTPUT_DIR = Path("results/shootout_resume_tailor")


def load_job(data_file: str, job_id: str) -> JobListing:
    """Load a JobListing from a data file by job_id."""
    with open(data_file) as f:
        jobs = json.load(f)
    for j in jobs:
        if j["job_id"] == job_id:
            return JobListing(**{k: v for k, v in j.items() if k in JobListing.__dataclass_fields__})
    raise ValueError(f"Job {job_id} not found in {data_file}")


def load_first_pass_eval(eval_file: str) -> str:
    """Load first-pass evaluation markdown."""
    return Path(eval_file).read_text()


def run_single(model_id: str, model_name: str, job: JobListing,
               first_pass_eval: str, config: dict) -> dict:
    """Run the deep_evaluate prompt for one model + one job. Returns result dict."""
    # Override config to use the specific model for deep_eval
    test_config = dict(config)
    test_config["models"] = dict(config.get("models", {}))
    test_config["models"]["deep_eval"] = {
        "provider": "openrouter",
        "model": model_id,
    }

    # Create a base evaluator (just needs resume_text; deep_evaluate creates its own client)
    resume_text = load_resume(config)
    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)

    start = time.time()
    result = evaluator.deep_evaluate(job, test_config, first_pass_eval=first_pass_eval)
    elapsed = time.time() - start

    return {
        "model_name": model_name,
        "model_id": model_id,
        "job_title": job.title,
        "job_company": job.company,
        "elapsed_seconds": round(elapsed, 1),
        "output": result,
        "output_length": len(result),
    }


def main():
    # Ensure OPENROUTER_KEY is set
    if not os.environ.get("OPENROUTER_KEY"):
        # Try loading from web/.env.local
        env_file = Path(__file__).parent / "web" / ".env.local"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OPENROUTER_KEY="):
                    os.environ["OPENROUTER_KEY"] = line.split("=", 1)[1].strip()
                    break
    if not os.environ.get("OPENROUTER_KEY"):
        print("ERROR: OPENROUTER_KEY not set")
        sys.exit(1)

    # Load config (includes env var overrides for API keys)
    config = load_config()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Resume Tailoring Model Shootout")
    print("=" * 60)
    print(f"\nModels: {len(SHOOTOUT_MODELS)}")
    print(f"Jobs: {len(TEST_JOBS)}")
    print(f"Total calls: {len(SHOOTOUT_MODELS) * len(TEST_JOBS)}")
    print()

    # Load all jobs and first-pass evals
    test_data = []
    for tj in TEST_JOBS:
        job = load_job(tj["data_file"], tj["job_id"])
        first_pass = load_first_pass_eval(tj["eval_file"])
        test_data.append((job, first_pass))
        print(f"  Job: {job.title} @ {job.company}")
    print()

    # Run all combinations in parallel (1 worker per model to avoid rate limits)
    tasks = []
    for model_id, model_name in SHOOTOUT_MODELS:
        for job, first_pass in test_data:
            tasks.append((model_id, model_name, job, first_pass))

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_single, mid, mname, job, fp, config): (mname, job.company)
            for mid, mname, job, fp in tasks
        }
        for future in as_completed(futures):
            mname, company = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"  ✓ {result['model_name']:20s} | {result['job_company']:20s} | "
                      f"{result['elapsed_seconds']:6.1f}s | {result['output_length']:,} chars")
            except Exception as e:
                print(f"  ✗ {mname:20s} | {company:20s} | ERROR: {e}")

    # Save each result to a separate file
    print(f"\nSaving results to {OUTPUT_DIR}/")
    for r in sorted(results, key=lambda x: (x["job_company"], x["model_name"])):
        safe_company = r["job_company"].replace(" ", "_").replace("/", "_")[:30]
        safe_model = r["model_name"].replace(" ", "_").replace(".", "")
        filename = f"{safe_company}__{safe_model}.md"
        filepath = OUTPUT_DIR / filename

        with open(filepath, "w") as f:
            f.write(f"# Resume Tailoring: {r['job_title']} — {r['job_company']}\n")
            f.write(f"**Model:** {r['model_name']} (`{r['model_id']}`)\n")
            f.write(f"**Time:** {r['elapsed_seconds']}s | **Length:** {r['output_length']:,} chars\n\n")
            f.write("---\n\n")
            f.write(r["output"])
            f.write("\n")

        print(f"  → {filename}")

    # Summary table
    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    print(f"{'Model':<22s} {'Job':<22s} {'Time':>7s} {'Length':>8s}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: (x["job_company"], x["model_name"])):
        print(f"{r['model_name']:<22s} {r['job_company']:<22s} "
              f"{r['elapsed_seconds']:6.1f}s {r['output_length']:>7,}")

    print(f"\nFiles saved to: {OUTPUT_DIR.resolve()}")
    print("Open each file and compare quality — pick the model with the best:")
    print("  • Resume rewrite specificity (exact before/after with real resume text)")
    print("  • Cover letter talking points (compelling, not generic)")
    print("  • Interview prep (role-specific questions, not boilerplate)")


if __name__ == "__main__":
    main()
