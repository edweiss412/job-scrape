"""LLM benchmark: compare models on a standardised set of job evaluations."""

import json
import time
from datetime import datetime

from pipeline.config import console, log, SCRIPT_DIR, DATA_DIR, RESULTS_DIR, load_resume
from pipeline.models import JobListing
from pipeline.evaluation.evaluator import ResumeEvaluator


def run_benchmark(config: dict):
    """
    Run multiple OpenRouter models against the same sample jobs
    to compare evaluation quality, format compliance, and cost.

    Usage: python job_scraper.py --benchmark

    This will:
    1. Take a stratified sample of jobs across all verdict categories
    2. Run each model against all samples
    3. Save side-by-side comparisons with actual costs
    4. Print a summary scorecard
    """
    # Models to benchmark -- edit this list to test others.
    # Format: (model_id, display_name, approx_cost_per_1M_output_tokens, provider_override)
    # provider_override: None = use OpenRouter, "google_aistudio" = use Google AI Studio direct
    BENCHMARK_MODELS = [
        # --- 7/8 calibration leaders ---
        ("google/gemini-3-flash-preview", "Gemini 3 Flash", 0.40, "google_aistudio"),       # production model
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", 0.38, None),
        # --- 6/8 ---
        ("qwen/qwen3.5-plus-02-15", "Qwen 3.5 Plus", 1.0, None),
        ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6", 15.0, None),
    ]

    openrouter_key = config.get("openrouter_key", "")
    if not openrouter_key:
        console.print("[red]Benchmark requires an OpenRouter API key.[/red]")
        console.print("Set openrouter_key in config.yaml (https://openrouter.ai/keys)")
        return

    resume_text = load_resume(config)
    if not resume_text:
        console.print("[red]Benchmark requires a resume. Place resume.txt in the project directory.[/red]")
        return

    # Get sample jobs: use existing results or create synthetic test cases
    sample_jobs = _get_benchmark_samples(config)
    if not sample_jobs:
        console.print("[red]No sample jobs available for benchmarking.[/red]")
        return

    console.print("[bold blue]\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550[/bold blue]")
    console.print("[bold blue]  LLM Benchmark \u2014 Model Comparison[/bold blue]")
    console.print("[bold blue]\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550[/bold blue]\n")
    console.print(f"Testing {len(BENCHMARK_MODELS)} models \u00d7 {len(sample_jobs)} jobs [bold green](parallel)[/bold green]\n")

    # --- Run all models in parallel ---
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    results = {}  # model_id -> (model_name, cost_per_m, model_results)
    print_lock = threading.Lock()

    def _run_model(model_id, model_name, cost_per_m, provider_override):
        """Evaluate all sample jobs for a single model (runs in its own thread)."""
        import copy
        bench_config = copy.deepcopy(config)
        # Override the centralized models.job_eval entry so resolve_model() picks it up
        if "models" not in bench_config:
            bench_config["models"] = {}
        if provider_override == "google_aistudio":
            bench_config["models"]["job_eval"] = {"provider": "google_aistudio", "model": model_id}
            bench_config["llm_provider"] = "google_aistudio"
            bench_config["google_aistudio_model"] = model_id
        else:
            bench_config["models"]["job_eval"] = {"provider": "openrouter", "model": model_id}
            bench_config["llm_provider"] = "openrouter"
            bench_config["openrouter_model"] = model_id
        evaluator = ResumeEvaluator(config=bench_config, resume_text=resume_text)

        if not evaluator.client:
            with print_lock:
                console.print(f"  [red]{model_name}: Failed to initialize \u2014 skipping[/red]")
            return model_id, model_name, cost_per_m, []

        # Verify the evaluator is actually using the intended model
        if evaluator.model != model_id:
            with print_lock:
                console.print(f"  [red]{model_name}: WARNING model mismatch! Expected {model_id}, got {evaluator.model}[/red]")
            return model_id, model_name, cost_per_m, []

        model_results = []
        for i, job in enumerate(sample_jobs):
            start = time.time()
            try:
                result = evaluator.evaluate(job)
                elapsed = time.time() - start
                usage = evaluator._last_usage or {}
                result["_usage"] = usage
                prompt_tok = usage.get("prompt_tokens", 0)
                comp_tok = usage.get("completion_tokens", 0)
                model_results.append((job, result, elapsed))
                with print_lock:
                    console.print(
                        f"  {model_name} [{i+1}/{len(sample_jobs)}] "
                        f"{job.title[:30]}\u2026 "
                        f"{result['verdict'] or '???'} \u2014 {elapsed:.1f}s "
                        f"({prompt_tok:,}+{comp_tok:,} tok)"
                    )
            except Exception as e:
                elapsed = time.time() - start
                with print_lock:
                    console.print(f"  {model_name} [{i+1}/{len(sample_jobs)}] [red]ERROR: {e}[/red]")
                model_results.append((job, {
                    "score": 0, "verdict": "ERROR", "reasoning": str(e),
                    "full_evaluation": "", "_usage": {},
                }, elapsed))
            time.sleep(1)  # Rate limiting between calls within a model
        return model_id, model_name, cost_per_m, model_results

    with ThreadPoolExecutor(max_workers=len(BENCHMARK_MODELS)) as pool:
        futures = {
            pool.submit(_run_model, mid, mname, cost, prov): mname
            for mid, mname, cost, prov in BENCHMARK_MODELS
        }
        for future in as_completed(futures):
            model_id, model_name, cost_per_m, model_results = future.result()
            if model_results:
                results[model_id] = (model_name, cost_per_m, model_results)
                with print_lock:
                    console.print(f"\n[bold green]\u2713 {model_name} complete[/bold green]")

    # --- Generate comparison report ---
    _save_benchmark_report(results, sample_jobs)


def _get_benchmark_samples(config: dict) -> list[JobListing]:
    """
    Get benchmark samples combining:
    1. Synthetic test cases with human-verified expected verdicts (ground truth)
    2. Real jobs from previous runs for real-world variety (1 per verdict category)

    The synthetic cases are the calibration benchmark -- models that get these
    wrong are poorly calibrated. Real jobs provide variety but their previous
    verdicts are used only for diverse selection, not as ground truth.
    """
    TARGET_VERDICTS = ["STRONG", "MODERATE", "STRETCH", "WEAK"]
    MIN_DESC_LEN = 200

    # --- Part 1: Real jobs (1 per verdict for variety) ---
    real_samples = []
    json_files = sorted(DATA_DIR.glob("jobs_*.json"), reverse=True)
    all_jobs: dict[str, JobListing] = {}

    for jf in json_files:
        try:
            with open(jf) as f:
                data = json.load(f)
            for d in data:
                jl = JobListing(**d)
                if (jl.job_id not in all_jobs
                        and len(jl.description) > MIN_DESC_LEN
                        and jl.match_verdict in TARGET_VERDICTS):
                    all_jobs[jl.job_id] = jl
        except Exception:
            continue

    if all_jobs:
        by_verdict: dict[str, list[JobListing]] = {v: [] for v in TARGET_VERDICTS}
        for jl in all_jobs.values():
            by_verdict[jl.match_verdict].append(jl)
        for v in TARGET_VERDICTS:
            by_verdict[v].sort(key=lambda j: len(j.description), reverse=True)

        # With weighted composite scoring, old WEAK verdicts are often STRETCH
        # (skills match but bad economics -- e.g. part-time venue gig).
        soft_remap = {"WEAK": "STRETCH"}
        for v in TARGET_VERDICTS:
            if by_verdict[v]:
                job = by_verdict[v][0]
                mapped = soft_remap.get(v, v)
                job._benchmark_expected = f"~{mapped}"  # prefix ~ = soft expectation
                real_samples.append(job)

        if real_samples:
            dist = ", ".join(f"{s.match_verdict}" for s in real_samples)
            console.print(f"Real jobs: {len(real_samples)} ({dist})")

    # --- Part 2: Synthetic test cases (hard ground truth) ---
    console.print("No previous results found \u2014 using built-in test postings")
    synthetic = [
        JobListing(
            title="AV Engineer",
            company="Goldman Sachs",
            location="New York, NY",
            url="",
            source="benchmark",
            tier="Tier 2 \u2014 Finance",
            description="""AV Engineer \u2014 Goldman Sachs \u2014 New York, NY

We are seeking an experienced AV Engineer to join our Corporate Services Technology team.

Responsibilities:
- Provide technical support for executive-level meetings, town halls, and broadcast events
- Operate and maintain Crestron, Extron, and Biamp audio/video systems
- Manage Dante audio networking across conference rooms and event spaces
- Coordinate with vendors for large-scale corporate events
- Troubleshoot AV issues in real-time during live events
- Support hybrid meeting environments using Zoom Rooms and Microsoft Teams Rooms

Requirements:
- 5+ years of experience in corporate AV or live event production
- Strong knowledge of audio mixing, signal flow, and DSP
- Experience with Dante audio networking
- Proficiency with Crestron or Extron control systems
- CTS certification preferred
- Ability to work flexible hours including evenings for events
- Experience in financial services environment preferred
- Bachelor's degree or equivalent experience

Salary: $95,000 - $125,000 + bonus""",
        ),
        JobListing(
            title="Technology Delivery Analyst, VP",
            company="BlackRock",
            location="New York, NY",
            url="",
            source="benchmark",
            tier="Tier 2 \u2014 Finance",
            description="""Technology Delivery Analyst, VP \u2014 BlackRock \u2014 New York

About this role:
BlackRock's Global Event Technology team is looking for a Technology Delivery Analyst
to manage audiovisual technology for corporate events and broadcasts from our
Hudson Yards headquarters.

Key Responsibilities:
- Lead audio engineering for corporate broadcasts, town halls, and client events
- Manage RF coordination for wireless microphone systems across multiple venues
- Operate Yamaha digital consoles and Shure wireless systems
- Create broadcast mixes for live webcasts and recordings
- Coordinate with production crews, ensuring seamless event execution
- Maintain inventory of AV equipment and manage vendor relationships
- Support the buildout of new broadcast studio facilities

Qualifications:
- 7+ years of audio engineering experience, preferably in corporate or broadcast
- Expert-level knowledge of Yamaha digital mixing consoles
- Experience with Shure wireless systems and RF coordination
- Knowledge of Dante audio networking
- Experience creating broadcast/webcast audio mixes
- Strong project management skills
- Experience with Dugan automixing preferred
- Financial services experience preferred
- CTS certification a plus but not required

Compensation: $130,000 - $160,000 base + annual bonus""",
        ),
        JobListing(
            title="Broadcast Systems Engineer",
            company="Netflix",
            location="Los Angeles, CA",
            url="",
            source="benchmark",
            tier="Tier 3 \u2014 Big Tech",
            description="""Broadcast Systems Engineer \u2014 Netflix \u2014 Los Angeles, CA

Netflix is looking for a Broadcast Systems Engineer to support our in-house
production and post-production audio infrastructure.

What you'll do:
- Design and maintain broadcast audio systems for Netflix studio facilities
- Manage Pro Tools and Avid S6 console workflows for mix stages
- Implement and maintain AES67/SMPTE ST 2110 audio-over-IP infrastructure
- Develop automation scripts for audio routing and monitoring
- Support Dolby Atmos mixing environments
- Collaborate with video engineering on synchronized A/V workflows

Requirements:
- 8+ years in broadcast audio engineering or studio systems engineering
- Deep expertise with Pro Tools HDX and Avid control surfaces
- Experience designing AES67 and SMPTE ST 2110 audio networks
- Strong scripting skills (Python, Bash) for system automation
- Experience with Dolby Atmos and immersive audio formats
- Knowledge of broadcast standards (SMPTE, AES)
- Experience with Calrec or Lawo broadcast consoles
- Degree in audio engineering, electrical engineering, or related field

Preferred:
- SBE certification
- Experience in a major streaming or broadcast facility
- Knowledge of NDI and video-over-IP

Salary: $140,000 - $180,000""",
        ),
        JobListing(
            title="Production Technician - 2nd Shift",
            company="Dynamic Manufacturing",
            location="Hillside, IL",
            url="",
            source="benchmark",
            tier="N/A",
            description="""Production Technician - 2nd Shift \u2014 Dynamic Manufacturing \u2014 Hillside, IL

We are looking for Production Technicians to join our automotive parts
manufacturing team on 2nd shift (3:00 PM - 11:30 PM).

Responsibilities:
- Operate stamping presses, injection molding machines, and assembly fixtures
- Perform quality checks using calipers, micrometers, and go/no-go gauges
- Load raw materials and unload finished parts from production lines
- Complete production logs and maintain 5S workplace standards
- Assist with changeovers and minor machine maintenance
- Follow all safety protocols including LOTO procedures

Requirements:
- High school diploma or GED
- 1-2 years manufacturing or factory experience preferred
- Ability to stand for 8+ hours and lift up to 50 lbs
- Basic math skills and ability to read blueprints
- Forklift certification a plus
- Must pass drug screen and background check

Salary: $18.50 - $22.00/hr + shift differential""",
        ),
    ]
    # Set expected verdicts for synthetic cases
    for job, expected in zip(synthetic, ["MODERATE", "STRONG", "STRETCH", "WEAK"]):
        job._benchmark_expected = expected

    console.print(f"Synthetic jobs: 4 (MODERATE, STRONG, STRETCH, WEAK)")
    all_samples = synthetic + real_samples
    console.print(f"Total benchmark samples: {len(all_samples)}")
    return all_samples


def _save_benchmark_report(results: dict, sample_jobs: list[JobListing]):
    """Generate and save the benchmark comparison report."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    benchmark_dir = RESULTS_DIR / "benchmarks"
    benchmark_dir.mkdir(exist_ok=True)
    report_path = benchmark_dir / f"benchmark_{timestamp}.md"

    # Build expected verdicts list
    expected_verdicts = []
    for job in sample_jobs:
        expected_verdicts.append(getattr(job, "_benchmark_expected", "?"))

    lines = [
        "# LLM Benchmark \u2014 Model Comparison",
        f"\n*Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}*\n",
    ]

    # Job legend
    lines.append("## Benchmark Jobs\n")
    lines.append("| # | Job | Expected | Source |")
    lines.append("|---|---|---|---|")
    for i, job in enumerate(sample_jobs):
        exp = expected_verdicts[i]
        src = "synthetic (ground truth)" if not exp.startswith("~") else "real (soft expectation)"
        lines.append(f"| {i+1} | {job.title} @ {job.company} ({job.location}) | {exp} | {src} |")

    # Summary scorecard
    lines.append("\n## Summary Scorecard\n")
    header_jobs = " | ".join(f"J{i+1}" for i in range(len(sample_jobs)))
    lines.append(f"| Model | Avg Time | Format | {header_jobs} | Calibration | Avg Tokens (in/out) | Cost/Eval | Est. Cost/100 |")
    lines.append(f"|---|---|---|{'---|' * len(sample_jobs)}---|---|---|---|")

    for model_id, (model_name, cost_per_m, model_results) in results.items():
        if not model_results:
            continue

        avg_time = sum(r[2] for r in model_results) / len(model_results)

        # Check format compliance: did it produce all 8 sections?
        format_scores = []
        for _, result, _ in model_results:
            text = result.get("full_evaluation", "")
            sections_found = sum(1 for marker in [
                "ROLE SUMMARY", "MATCH SCORE", "REQUIREMENTS",
                "NOT HIGHLIGHTED", "TRUE GAPS", "RED FLAGS", "LOGISTICS", "VERDICT"
            ] if marker.upper() in text.upper())
            format_scores.append(sections_found)
        avg_format = sum(format_scores) / len(format_scores)
        format_pct = f"{avg_format:.1f}/8"

        # Per-job verdicts with match indicator
        verdict_cells = []
        calibration_hits = 0
        calibration_total = 0
        for idx, (_, result, _) in enumerate(model_results):
            actual = result.get("verdict", "???")
            expected = expected_verdicts[idx] if idx < len(expected_verdicts) else "?"
            # Calibration: check if actual matches expected
            exp_clean = expected.lstrip("~")
            is_soft = expected.startswith("~")
            if exp_clean in ("STRONG", "MODERATE", "STRETCH", "WEAK"):
                calibration_total += 1
                if actual == exp_clean:
                    verdict_cells.append(f"**{actual}** \u2713")
                    calibration_hits += 1
                else:
                    verdict_cells.append(f"{actual} \u2717")
            else:
                verdict_cells.append(actual)
        verdict_cols = " | ".join(verdict_cells)
        cal_str = f"{calibration_hits}/{calibration_total}" if calibration_total else "n/a"

        # Actual token usage from API responses
        total_prompt = sum(r.get("_usage", {}).get("prompt_tokens", 0) for _, r, _ in model_results)
        total_comp = sum(r.get("_usage", {}).get("completion_tokens", 0) for _, r, _ in model_results)
        n_evals = len(model_results)
        avg_prompt = total_prompt // n_evals if n_evals else 0
        avg_comp = total_comp // n_evals if n_evals else 0
        token_str = f"{avg_prompt:,} / {avg_comp:,}"

        # Cost: prefer actual OpenRouter cost (non-zero), fall back to rate-card estimate
        actual_costs = [r.get("_usage", {}).get("cost") for _, r, _ in model_results]
        actual_costs = [c for c in actual_costs if c is not None and c > 0]
        if actual_costs:
            avg_cost_per_eval = sum(actual_costs) / len(actual_costs)
            actual_cost_str = f"${avg_cost_per_eval:.6f}"
            est_cost_100 = avg_cost_per_eval * 100
        elif avg_comp:
            # Rate-card estimate from token counts
            avg_cost_per_eval = (cost_per_m / 1_000_000) * avg_comp
            actual_cost_str = f"~${avg_cost_per_eval:.6f}"
            est_cost_100 = avg_cost_per_eval * 100
        else:
            actual_cost_str = "free" if cost_per_m == 0 else "n/a"
            est_cost_100 = 0
        cost_str = f"${est_cost_100:.4f}" if est_cost_100 > 0 else "free"

        lines.append(
            f"| {model_name} | {avg_time:.1f}s | {format_pct} | {verdict_cols} | {cal_str} | {token_str} | {actual_cost_str} | {cost_str} |"
        )

    # Detailed side-by-side for each sample job
    for i, job in enumerate(sample_jobs):
        expected = expected_verdicts[i] if i < len(expected_verdicts) else "?"
        lines.append(f"\n---\n## Job {i+1}: {job.title} @ {job.company}")
        lines.append(f"**Location:** {job.location} | **Salary:** {job.salary or 'Not listed'} | **Expected:** {expected}\n")

        for model_id, (model_name, _, model_results) in results.items():
            if i >= len(model_results):
                continue
            _, result, elapsed = model_results[i]

            lines.append(f"### {model_name}")
            usage = result.get("_usage", {})
            ptok = usage.get("prompt_tokens", 0)
            ctok = usage.get("completion_tokens", 0)
            rcost = usage.get("cost")
            cost_part = f" | Cost: ${rcost:.6f}" if rcost is not None and rcost > 0 else ""
            actual_v = result.get("verdict", "???")
            match_icon = "\u2713" if actual_v == expected.lstrip("~") else "\u2717"
            lines.append(f"*Verdict: {actual_v} {match_icon} | Time: {elapsed:.1f}s | Tokens: {ptok:,}+{ctok:,}{cost_part}*\n")

            eval_text = result.get("full_evaluation", "(no output)")
            if len(eval_text) > 3000:
                eval_text = eval_text[:3000] + "\n\n*[truncated for benchmark report]*"

            lines.append("<details><summary>Full evaluation</summary>\n")
            lines.append(eval_text)
            lines.append("\n</details>\n")

    # Evaluation criteria guide
    lines.append("\n---\n## How to Read This\n")
    lines.append("""**Calibration score** is the key metric. It measures how many jobs the model rated correctly
compared to expected verdicts. Synthetic jobs have hard ground truth (designed with specific
expected outcomes). Real jobs have soft expectations (based on a previous model's rating, marked with ~).

For synthetic jobs:
- **Goldman Sachs AV Engineer \u2192 MODERATE** \u2014 Skills transfer well but Crestron/Extron gap and relocation cost.
- **BlackRock Tech Delivery Analyst \u2192 STRONG** \u2014 Disguised AV/audio role, excellent skills match, strong comp.
- **Netflix Broadcast Systems Engineer \u2192 WEAK** \u2014 Studio/post-production engineering is a different discipline (Pro Tools/Avid S6/Atmos/AES67 are genuine gaps).

When comparing models, also look for:
1. **Verdict honesty** \u2014 Does the model correctly downgrade when pay/seniority don't match, even if skills overlap?
2. **Citation quality** \u2014 Does it cite specific resume lines or hand-wave?
3. **Gap honesty** \u2014 Does it distinguish dealbreakers from nice-to-haves?
4. **Title translation** \u2014 Does it catch disguised titles (e.g., "Technology Delivery Analyst, VP" = Lead Audio Engineer)?""")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    console.print(f"\n[bold green]Benchmark report saved: {report_path}[/bold green]")
    console.print("\nOpen it and compare:")
    console.print("  \u2022 Did each model produce all 7 sections?")
    console.print("  \u2022 Is the Netflix role rated STRETCH/WEAK? (it should be)")
    console.print("  \u2022 Does the model cite specific resume lines or hand-wave?")
    console.print("  \u2022 Is the BlackRock title correctly translated?")
