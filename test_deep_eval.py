#!/usr/bin/env python3
"""One-off script to test deep eval for a single job with a specific model."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import load_config, load_resume, JobListing, ResumeEvaluator

TARGET_JOB_ID = "e79a5f14ab1a"
TEST_MODEL = "arcee-ai/trinity-large-preview:free"
DATA_FILE = Path(__file__).parent / "data" / "jobs_20260216_202042.json"


def main():
    # Load config and override deep_eval model
    config = load_config()
    config["deep_eval"]["provider"] = "openrouter"
    config["deep_eval"]["model"] = TEST_MODEL

    # Load the job
    raw = json.loads(DATA_FILE.read_text())
    job_data = next(j for j in raw if j["job_id"] == TARGET_JOB_ID)
    job = JobListing(**{k: job_data.get(k) for k in JobListing.__dataclass_fields__})
    job.match_verdict = "STRONG"  # ensure deep eval runs

    # Load resume
    resume_text = load_resume(config)
    if not resume_text:
        print("ERROR: No resume found")
        sys.exit(1)

    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)

    print(f"Running deep eval for: {job.title} @ {job.company}")
    print(f"Model: {TEST_MODEL}\n")
    print("=" * 60)

    result = evaluator.deep_evaluate(job, config)
    if result:
        out_path = Path(__file__).parent / "test_deep_eval_output.md"
        out_path.write_text(result)
        print(result)
        print("\n" + "=" * 60)
        print(f"Saved to: {out_path}")
    else:
        print("ERROR: Deep eval returned empty result")


if __name__ == "__main__":
    main()
