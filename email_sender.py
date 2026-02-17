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

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import resend

SCRIPT_DIR = Path(__file__).parent


def make_job_id(title: str, company: str, location: str) -> str:
    """Reconstruct job_id hash matching JobListing.__post_init__."""
    loc = re.sub(
        r',?\s*(United States|USA|US|Estados Unidos)$', '', location,
        flags=re.IGNORECASE,
    ).strip().rstrip(',').strip()
    loc = re.sub(r'\s+', ' ', loc)
    raw = f"{title}|{company}|{loc}".lower().strip()
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def strip_md(text: str) -> str:
    """Strip markdown formatting to plain text."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*([^*]+)\*', r'\1', text)        # *italic*
    text = re.sub(r'[🟢🟡🟠🔴⚪]', '', text)            # emoji badges
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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

    # Header: "# Title — Company"
    for line in lines:
        if line.startswith("# "):
            parts = line[2:].split(" — ", 1)
            info["title"] = parts[0].strip()
            if len(parts) > 1:
                info["company"] = parts[1].strip()
            break

    # Metadata fields
    for line in lines:
        if line.startswith("**Location:**"):
            info["location"] = line.split("**Location:**")[1].strip()
        elif line.startswith("**Salary:**"):
            info["salary"] = line.split("**Salary:**")[1].strip()

    # Extract "why this is a good pick" from the match score section (### 2. to ### 3.)
    # Strip verdict labels and focus on the reasoning
    in_section = False
    summary_lines = []
    for line in lines:
        if re.match(r"###\s*2\.", line):
            in_section = True
            continue
        if re.match(r"###\s*3\.", line):
            break
        if in_section:
            clean = strip_md(line)
            if not clean:
                continue
            # Strip leading verdict prefixes: "Rating:", "Match Score:", "RATE:", etc.
            clean = re.sub(
                r'^(Match\s*Score|Rating|RATE|MATCH\s*SCORE)\s*:\s*',
                '', clean, flags=re.IGNORECASE,
            ).strip()
            # Strip verdict labels: "STRONG MATCH (with caveats...)", "MODERATE MATCH", etc.
            clean = re.sub(
                r'^(STRONG|MODERATE|STRETCH|WEAK)\s*(MATCH)?(\s*\([^)]*\))?\s*',
                '', clean, flags=re.IGNORECASE,
            ).strip()
            # Strip "Technical Match: ... | Career/Financial Match: ..." prefix lines
            clean = re.sub(
                r'^(Technical|Career|Financial)\s*(/\w+)?\s*Match\s*:\s*\w+\s*\|?\s*',
                '', clean, flags=re.IGNORECASE,
            ).strip()
            # Strip "Reasoning:" or "Why:" prefix
            clean = re.sub(r'^(Reasoning|Why)\s*:\s*', '', clean, flags=re.IGNORECASE).strip()
            if clean:
                summary_lines.append(clean)

    info["summary"] = " ".join(summary_lines)[:300]

    # Try to get location from Role Summary if header is empty
    if not info["location"]:
        for line in lines:
            m = re.search(r'\*\*Location:\*\*\s*(.+)', line)
            if m:
                info["location"] = m.group(1).strip()
                break

    # Clean location for display: strip country suffixes
    if info["location"]:
        info["location"] = re.sub(
            r',?\s*(United States|USA|US|Estados Unidos)$', '',
            info["location"], flags=re.IGNORECASE,
        ).strip().rstrip(',').strip()

    # Clean salary: normalize Spanish formatting
    if info["salary"]:
        info["salary"] = (info["salary"]
            .replace("De USD ", "$").replace(" por año", "/yr")
            .replace(" k a USD ", "K–$").replace(" k", "K"))

    # Generate job_id for NEW badge matching
    info["job_id"] = make_job_id(info["title"], info["company"], info["location"])

    return info


def build_job_row(job: dict, link: str, accent: str, is_new: bool = False) -> str:
    """Build one job entry for the email."""
    salary_html = f'<span style="color:{accent};font-weight:600;">{job["salary"]}</span>' if job["salary"] else ""
    loc_html = job["location"] if job["location"] else "Location not listed"
    link_html = f'<a href="{link}" style="color:{accent};font-size:13px;font-weight:500;text-decoration:none;">View Full Evaluation →</a>' if link else ""

    new_badge = '<span style="display:inline-block;background:#3b82f6;color:#fff;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700;margin-left:6px;vertical-align:middle;">NEW</span>' if is_new else ""

    return f"""
    <tr><td style="padding:14px 16px;border-bottom:1px solid #f0f0f0;">
      <div style="margin-bottom:4px;">
        <span style="font-weight:700;font-size:15px;color:#1a1a2e;">{job['title']}</span>{new_badge}
      </div>
      <div style="margin-bottom:6px;font-size:13px;color:#6b7280;">
        {job['company']} · {loc_html}{(' · ' + salary_html) if salary_html else ''}
      </div>
      <div style="font-size:13px;color:#4b5563;line-height:1.5;margin-bottom:8px;">
        {job['summary']}
      </div>
      {link_html}
    </td></tr>"""


def build_email_html(
    date_str: str,
    strong: list[dict],
    moderate: list[dict],
    site_base_url: str,
    new_job_ids: set[str] | None = None,
) -> str:
    """Build a clean, modern HTML email."""
    new_ids = new_job_ids or set()
    strong_count = len(strong)
    moderate_count = len(moderate)

    # Header
    html = f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;background:#ffffff;">

  <!-- Header -->
  <div style="background:#1a1a2e;padding:24px;border-radius:8px 8px 0 0;">
    <div style="font-size:20px;font-weight:700;color:#ffffff;margin-bottom:4px;">Job Scan Results</div>
    <div style="font-size:14px;color:#94a3b8;">{date_str}</div>
    <div style="margin-top:12px;display:flex;gap:8px;">
      <span style="display:inline-block;background:#059669;color:#fff;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;">{strong_count} Strong</span>
      <span style="display:inline-block;background:#d97706;color:#fff;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;">{moderate_count} Moderate</span>
    </div>
  </div>
"""

    # Strong matches
    if strong:
        html += """
  <div style="padding:16px;background:#ecfdf5;border-left:4px solid #059669;">
    <div style="font-size:14px;font-weight:700;color:#059669;text-transform:uppercase;letter-spacing:0.05em;">
      Strong Matches
    </div>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
"""
        for job in strong:
            link = f"{site_base_url}/{date_str}/strong/{job['filename']}.html" if site_base_url else ""
            html += build_job_row(job, link, "#059669", is_new=job.get("job_id") in new_ids)
        html += "  </table>\n"

    # Top moderate matches
    if moderate:
        shown = moderate[:10]
        html += f"""
  <div style="padding:16px;background:#fffbeb;border-left:4px solid #d97706;margin-top:2px;">
    <div style="font-size:14px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:0.05em;">
      Top Moderate Picks{f' ({len(shown)} of {moderate_count})' if moderate_count > 10 else ''}
    </div>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
"""
        for job in shown:
            link = f"{site_base_url}/{date_str}/moderate/{job['filename']}.html" if site_base_url else ""
            html += build_job_row(job, link, "#d97706", is_new=job.get("job_id") in new_ids)
        html += "  </table>\n"

        if moderate_count > 10 and site_base_url:
            html += f"""
  <div style="padding:12px 16px;text-align:center;">
    <a href="{site_base_url}/{date_str}/moderate/" style="color:#d97706;font-size:14px;font-weight:600;text-decoration:none;">
      View all {moderate_count} moderate matches →
    </a>
  </div>
"""

    # Footer
    footer_link = f'<a href="{site_base_url}/{date_str}/" style="color:#60a5fa;text-decoration:none;">View full dashboard →</a>' if site_base_url else ""
    html += f"""
  <div style="padding:20px;background:#f8fafc;border-radius:0 0 8px 8px;border-top:1px solid #e5e7eb;text-align:center;">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:4px;">{footer_link}</div>
    <div style="font-size:11px;color:#cbd5e1;">Automated scan · Sent via Resend</div>
  </div>

</div>"""

    return html


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

    # Parse moderate matches
    moderate = []
    moderate_dir = results_dir / "moderate"
    if moderate_dir.is_dir():
        for md_path in sorted(moderate_dir.glob("*.md")):
            moderate.append(parse_eval_file(md_path))

    if not strong and not moderate:
        print("No strong or moderate matches found. Skipping email.")
        return

    new_job_ids = set(metadata.get("new_job_ids", []))

    strong_count = len(strong)
    moderate_count = len(moderate)
    new_count = sum(1 for j in strong + moderate if j.get("job_id") in new_job_ids)
    new_label = f", {new_count} NEW" if new_count else ""
    subject = f"Job Scan — {date_str}: {strong_count} STRONG, {moderate_count} MODERATE{new_label}"

    html = build_email_html(date_str, strong, moderate, site_base_url, new_job_ids)

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
