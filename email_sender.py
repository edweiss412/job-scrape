#!/usr/bin/env python3
"""
Send an email digest of job scan results via Resend.

Reads run_metadata.json (written by job_scraper.py) and the markdown
evaluation files to build an HTML email with strong + top moderate matches.

Required env vars:
    RESEND_API_KEY   — Resend API key
    NOTIFY_EMAIL     — Recipient email address

Optional env vars:
    SITE_BASE_URL    — GitHub Pages base URL (e.g. https://user.github.io/job-scrape)
    EMAIL_FROM       — Sender address (default: onboarding@resend.dev)

Usage:
    python email_sender.py
"""

import json
import os
import re
import sys
from pathlib import Path

import resend

SCRIPT_DIR = Path(__file__).parent


def parse_eval_file(md_path: Path) -> dict:
    """Extract structured info from a markdown evaluation file."""
    text = md_path.read_text()
    lines = text.split("\n")

    info = {
        "filename": md_path.stem,
        "title": "",
        "company": "",
        "location": "",
        "salary": "",
        "summary": "",
    }

    # Parse header: "# Title — Company"
    for line in lines:
        if line.startswith("# "):
            parts = line[2:].split(" — ", 1)
            info["title"] = parts[0].strip()
            if len(parts) > 1:
                info["company"] = parts[1].strip()
            break

    # Parse metadata fields
    for line in lines:
        if line.startswith("**Location:**"):
            info["location"] = line.split("**Location:**")[1].strip()
        elif line.startswith("**Salary:**"):
            info["salary"] = line.split("**Salary:**")[1].strip()

    # Extract match summary: text between "### 2." and "### 3."
    in_section = False
    summary_lines = []
    for line in lines:
        if re.match(r"###\s*2\.", line):
            in_section = True
            continue
        if re.match(r"###\s*3\.", line):
            break
        if in_section and line.strip():
            summary_lines.append(line.strip())

    info["summary"] = " ".join(summary_lines)[:300]

    return info


def build_email_html(
    date_str: str,
    strong: list[dict],
    moderate: list[dict],
    site_base_url: str,
) -> str:
    """Build the HTML email body."""
    strong_count = len(strong)
    moderate_count = len(moderate)

    html_parts = []
    html_parts.append(f"""
<div style="font-family: -apple-system, system-ui, sans-serif; max-width: 640px; margin: 0 auto; color: #222;">
<h1 style="font-size: 18px; border-bottom: 2px solid #333; padding-bottom: 8px;">
  Job Scan &mdash; {date_str}: {strong_count} STRONG, {moderate_count} MODERATE
</h1>
""")

    # Strong matches (all)
    if strong:
        html_parts.append("""
<h2 style="font-size: 15px; color: #155724; background: #d4edda; padding: 6px 10px; border-radius: 4px;">
  STRONG MATCHES ({count})
</h2>
""".format(count=strong_count))

        for job in strong:
            link = f"{site_base_url}/{date_str}/strong/{job['filename']}.html" if site_base_url else ""
            salary_str = f" &mdash; {job['salary']}" if job['salary'] else ""
            html_parts.append(f"""
<div style="margin: 12px 0; padding: 10px; border-left: 3px solid #28a745;">
  <strong>[{job['company']}]</strong> {job['title']} &mdash; {job['location']}{salary_str}<br>
  <span style="color: #555; font-size: 14px;">{job['summary']}</span><br>
  {"<a href='" + link + "' style='font-size: 13px;'>&rarr; View Full Evaluation</a>" if link else ""}
</div>
""")

    # Top moderate matches (up to 10)
    if moderate:
        shown = moderate[:10]
        html_parts.append("""
<h2 style="font-size: 15px; color: #856404; background: #fff3cd; padding: 6px 10px; border-radius: 4px;">
  TOP MODERATE PICKS (showing {shown} of {total})
</h2>
""".format(shown=len(shown), total=moderate_count))

        for job in shown:
            link = f"{site_base_url}/{date_str}/moderate/{job['filename']}.html" if site_base_url else ""
            salary_str = f" &mdash; {job['salary']}" if job['salary'] else ""
            html_parts.append(f"""
<div style="margin: 12px 0; padding: 10px; border-left: 3px solid #ffc107;">
  <strong>[{job['company']}]</strong> {job['title']} &mdash; {job['location']}{salary_str}<br>
  <span style="color: #555; font-size: 14px;">{job['summary']}</span><br>
  {"<a href='" + link + "' style='font-size: 13px;'>&rarr; View Full Evaluation</a>" if link else ""}
</div>
""")

        if moderate_count > 10 and site_base_url:
            all_link = f"{site_base_url}/{date_str}/moderate/"
            html_parts.append(f"""
<p><a href="{all_link}">&rarr; View all {moderate_count} moderate matches</a></p>
""")

    # Footer
    if site_base_url:
        html_parts.append(f"""
<hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
<p style="font-size: 13px; color: #888;">
  <a href="{site_base_url}/{date_str}/">View full results on web</a>
</p>
""")

    html_parts.append("</div>")
    return "\n".join(html_parts)


def main():
    api_key = os.environ.get("RESEND_API_KEY")
    notify_email = os.environ.get("NOTIFY_EMAIL")

    if not api_key:
        print("ERROR: RESEND_API_KEY env var not set")
        sys.exit(1)
    if not notify_email:
        print("ERROR: NOTIFY_EMAIL env var not set")
        sys.exit(1)

    resend.api_key = api_key

    site_base_url = os.environ.get("SITE_BASE_URL", "").rstrip("/")
    email_from = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    # Load run metadata
    metadata_path = SCRIPT_DIR / "run_metadata.json"
    if not metadata_path.exists():
        print("ERROR: run_metadata.json not found. Run job_scraper.py first.")
        sys.exit(1)

    with open(metadata_path) as f:
        metadata = json.load(f)

    date_str = metadata["date"]
    results_dir = Path(metadata["results_dir"])

    # Parse strong matches
    strong = []
    strong_dir = results_dir / "strong"
    if strong_dir.is_dir():
        for md_path in sorted(strong_dir.glob("*.md")):
            strong.append(parse_eval_file(md_path))

    # Parse moderate matches and sort by filename (match_score is baked into save order)
    moderate = []
    moderate_dir = results_dir / "moderate"
    if moderate_dir.is_dir():
        for md_path in sorted(moderate_dir.glob("*.md")):
            moderate.append(parse_eval_file(md_path))

    if not strong and not moderate:
        print("No strong or moderate matches found. Skipping email.")
        return

    strong_count = len(strong)
    moderate_count = len(moderate)
    subject = f"Job Scan — {date_str}: {strong_count} STRONG, {moderate_count} MODERATE"

    html = build_email_html(date_str, strong, moderate, site_base_url)

    params = {
        "from": email_from,
        "to": [notify_email],
        "subject": subject,
        "html": html,
    }

    result = resend.Emails.send(params)
    print(f"Email sent to {notify_email}: {result}")


if __name__ == "__main__":
    main()
