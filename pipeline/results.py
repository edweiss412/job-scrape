"""Results storage & reporting: JSON, CSV, markdown, and Rich console output."""

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rich.table import Table

from pipeline.config import console, log, DATA_DIR, RESULTS_DIR
from pipeline.models import JobListing


# ---------------------------------------------------------------------------
# Results storage & reporting
# ---------------------------------------------------------------------------
def save_results(jobs: list[JobListing], filename: str = None):
    """Save results to JSON and generate reports, organized by date and verdict."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"jobs_{timestamp}"

    # Create date-based run directory
    date_str = datetime.now().strftime("%Y-%m-%d")
    run_dir = RESULTS_DIR / date_str
    run_dir.mkdir(parents=True, exist_ok=True)

    # Save raw JSON
    json_path = DATA_DIR / f"{filename}.json"
    with open(json_path, "w") as f:
        json.dump([asdict(j) for j in jobs], f, indent=2, default=str)
    log.info(f"Saved {len(jobs)} listings to {json_path}")

    # Save CSV for spreadsheet use
    csv_path = run_dir / "summary.csv"
    with open(csv_path, "w") as f:
        headers = [
            "score", "verdict", "title", "company", "location", "tier",
            "salary", "source", "url", "reasoning", "date_posted",
        ]
        f.write(",".join(headers) + "\n")
        for job in sorted(jobs, key=lambda j: j.match_score, reverse=True):
            row = [
                str(job.match_score),
                f'"{job.match_verdict}"',
                f'"{job.title}"',
                f'"{job.company}"',
                f'"{job.location}"',
                f'"{job.tier}"',
                f'"{job.salary}"',
                job.source,
                job.url,
                f'"{job.match_reasoning[:200] if job.match_reasoning else ""}"',
                f'"{job.date_posted}"',
            ]
            f.write(",".join(row) + "\n")
    log.info(f"Saved CSV report to {csv_path}")

    # Save markdown report
    md_path = run_dir / "summary.md"
    generate_markdown_report(jobs, md_path)

    # Save individual evaluation files organized by verdict level
    verdict_dirs = {
        "STRONG": run_dir / "strong",
        "MODERATE": run_dir / "moderate",
        "STRETCH": run_dir / "stretch",
        "WEAK": run_dir / "weak",
    }
    evaluated = [j for j in jobs if j.match_verdict and j.full_evaluation]
    if evaluated:
        for verdict_name, verdict_dir in verdict_dirs.items():
            verdict_jobs = [j for j in evaluated if j.match_verdict == verdict_name]
            if verdict_jobs:
                verdict_dir.mkdir(exist_ok=True)
                for job in verdict_jobs:
                    safe_name = re.sub(r'[^\w\-]', '_', f"{job.company}_{job.title}")[:80]
                    eval_path = verdict_dir / f"{safe_name}.md"
                    with open(eval_path, "w") as f:
                        f.write(f"# {job.title} -- {job.company}\n\n")
                        f.write(f"**Location:** {job.location}\n")
                        f.write(f"**URL:** {job.url}\n")
                        if job.salary:
                            f.write(f"**Salary:** {job.salary}\n")
                        if job.tier:
                            f.write(f"**Tier:** {job.tier}\n")
                        if job.job_summary:
                            f.write(f"**Job Summary:** {job.job_summary}\n")
                        f.write(f"\n---\n\n{job.full_evaluation}\n")
                log.info(f"Saved {len(verdict_jobs)} {verdict_name} evaluations to {verdict_dir}/")

    return json_path, csv_path, md_path


def generate_markdown_report(jobs: list[JobListing], path: Path):
    """Generate a formatted markdown report of results."""
    sorted_jobs = sorted(jobs, key=lambda j: j.match_score, reverse=True)
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    lines = [
        f"# Job Search Results -- {timestamp}",
        f"\n**Total listings found:** {len(jobs)}",
        f"**Sources:** {', '.join(set(j.source for j in jobs))}",
        "",
    ]

    # Group by verdict
    strong = [j for j in sorted_jobs if j.match_verdict == "STRONG"]
    moderate = [j for j in sorted_jobs if j.match_verdict == "MODERATE"]
    stretch = [j for j in sorted_jobs if j.match_verdict == "STRETCH"]
    weak = [j for j in sorted_jobs if j.match_verdict == "WEAK"]
    unscored = [j for j in sorted_jobs if not j.match_verdict]

    # Strong matches -- full evaluations
    if strong:
        lines.append(f"## STRONG MATCHES ({len(strong)})\n")
        for job in strong:
            lines.append(f"### {job.title} -- {job.company}")
            lines.append(f"{job.location} | [Apply]({job.url})")
            if job.tier:
                lines.append(f"*{job.tier}*")
            if job.salary:
                lines.append(f"{job.salary}")
            lines.append("")
            if job.full_evaluation:
                lines.append("<details><summary>Full Evaluation</summary>\n")
                lines.append(job.full_evaluation)
                lines.append("\n</details>")
            lines.append("---")

    # Moderate matches -- full evaluations
    if moderate:
        lines.append(f"\n## MODERATE MATCHES ({len(moderate)})\n")
        for job in moderate:
            lines.append(f"### {job.title} -- {job.company}")
            lines.append(f"{job.location} | [Apply]({job.url})")
            if job.tier:
                lines.append(f"*{job.tier}*")
            if job.salary:
                lines.append(f"{job.salary}")
            lines.append("")
            if job.full_evaluation:
                lines.append("<details><summary>Full Evaluation</summary>\n")
                lines.append(job.full_evaluation)
                lines.append("\n</details>")
            lines.append("---")

    # Stretch -- condensed
    if stretch:
        lines.append(f"\n## STRETCH ({len(stretch)})\n")
        for job in stretch:
            lines.append(f"- **{job.title}** at {job.company} ({job.location})")
            lines.append(f"  [Link]({job.url})")
            # Show just the verdict section
            if job.match_reasoning:
                # Trim to first 200 chars for condensed view
                short = job.match_reasoning[:300].replace("\n", " ")
                lines.append(f"  > {short}")
            if job.full_evaluation:
                lines.append(f"  <details><summary>Full Evaluation</summary>\n")
                lines.append(f"  {job.full_evaluation}")
                lines.append(f"\n  </details>")
            lines.append("")

    # Weak -- just titles
    if weak:
        lines.append(f"\n## WEAK MATCHES ({len(weak)})\n")
        for job in weak:
            lines.append(
                f"- {job.title} at {job.company} ({job.location}) -- "
                f"[Link]({job.url})"
            )

    # Unscored
    if unscored:
        lines.append(f"\n## NOT EVALUATED ({len(unscored)})\n")
        for job in unscored[:20]:
            lines.append(f"- {job.title} at {job.company} -- {job.source}")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    log.info(f"Saved markdown report to {path}")


def load_previous_results() -> list[JobListing]:
    """Load the most recent results file."""
    json_files = sorted(DATA_DIR.glob("jobs_*.json"), reverse=True)
    if not json_files:
        return []
    with open(json_files[0]) as f:
        data = json.load(f)
    return [JobListing(**d) for d in data]


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------
def print_summary(jobs: list[JobListing]):
    """Print a summary table to the console."""
    sorted_jobs = sorted(jobs, key=lambda j: j.match_score, reverse=True)

    table = Table(title="Job Search Results", show_lines=True)
    table.add_column("Verdict", style="bold", width=10)
    table.add_column("Title", width=30)
    table.add_column("Company", width=20)
    table.add_column("Location", width=20)
    table.add_column("Source", width=12)
    table.add_column("Tier", width=18)

    for job in sorted_jobs[:30]:  # Show top 30
        verdict_display = job.match_verdict or "--"
        score_style = {
            "STRONG": "green bold",
            "MODERATE": "yellow",
            "STRETCH": "rgb(255,165,0)",
            "WEAK": "dim",
        }.get(job.match_verdict, "white")
        table.add_row(
            f"[{score_style}]{verdict_display}[/{score_style}]",
            job.title[:30],
            job.company[:20],
            job.location[:20],
            job.source.replace("serpapi_google_jobs", "Google Jobs"),
            job.tier[:18] if job.tier else "",
        )

    console.print(table)

    # Summary stats
    sources = {}
    for job in jobs:
        sources[job.source] = sources.get(job.source, 0) + 1

    console.print(f"\n[bold]Total: {len(jobs)} unique listings[/bold]")
    for source, count in sorted(sources.items(), key=lambda x: -x[1]):
        console.print(f"  {source}: {count}")

    top = sum(1 for j in jobs if j.match_verdict == "STRONG")
    good = sum(1 for j in jobs if j.match_verdict == "MODERATE")
    stretch_count = sum(1 for j in jobs if j.match_verdict == "STRETCH")
    weak_count = sum(1 for j in jobs if j.match_verdict == "WEAK")
    console.print(f"\n  Strong matches:   {top}")
    console.print(f"  Moderate matches: {good}")
    console.print(f"  Stretch:          {stretch_count}")
    console.print(f"  Weak:             {weak_count}")
