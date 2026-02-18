#!/usr/bin/env python3
"""
migrate_to_supabase.py

One-time migration: reads all existing results/ and freelance/ markdown files
and loads them into Supabase.

Usage:
    python migrate_to_supabase.py           # Full migration
    python migrate_to_supabase.py --dry-run # Print counts only, no writes

Required env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
FREELANCE_DIR = SCRIPT_DIR / "freelance"
VERDICT_DIRS = ["strong", "moderate", "stretch", "weak"]


# ---------------------------------------------------------------------------
# Supabase REST helpers
# ---------------------------------------------------------------------------
def get_supabase_headers():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def supabase_post(url_path: str, payload, prefer: str = "resolution=merge-duplicates", on_conflict: str = None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    headers = {**get_supabase_headers(), "Prefer": prefer}
    params = {}
    if on_conflict:
        params["on_conflict"] = on_conflict
    resp = requests.post(f"{base}/rest/v1/{url_path}", headers=headers, json=payload, params=params, timeout=60)
    if not resp.ok:
        print(f"  ERROR {resp.status_code} on {url_path}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json() if resp.text else []


def supabase_get(url_path: str, params: dict = None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    resp = requests.get(
        f"{base}/rest/v1/{url_path}",
        headers=get_supabase_headers(),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_location(loc: str) -> str:
    loc = re.sub(
        r',?\s*(United States|USA|US|Estados Unidos|Est\w+\s+Uni\w+)$',
        '', loc, flags=re.IGNORECASE,
    ).strip().rstrip(',').strip()
    loc = re.sub(r'\s+', ' ', loc)
    return loc


def make_job_id(title: str, company: str, location: str) -> str:
    loc = normalize_location(location)
    raw = f"{title}|{company}|{loc}".lower().strip()
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def parse_eval_md(md_path: Path, verdict: str) -> dict:
    """Extract structured fields from a job evaluation markdown file."""
    text = md_path.read_text(errors="replace")
    lines = text.split("\n")

    info = {
        "title": "", "company": "", "location": "", "url": "",
        "salary": "", "tier": "", "job_summary": "",
        "match_verdict": verdict.upper(),
        "full_evaluation": "",
    }

    # "# Title — Company"
    for line in lines:
        if line.startswith("# "):
            parts = line[2:].split(" — ", 1)
            info["title"] = parts[0].strip()
            if len(parts) > 1:
                info["company"] = parts[1].strip()
            break

    for line in lines:
        if line.startswith("**Location:**"):
            info["location"] = line.split("**Location:**")[1].strip()
        elif line.startswith("**URL:**"):
            info["url"] = line.split("**URL:**")[1].strip()
        elif line.startswith("**Salary:**"):
            info["salary"] = line.split("**Salary:**")[1].strip()
        elif line.startswith("**Tier:**"):
            info["tier"] = line.split("**Tier:**")[1].strip()
        elif line.startswith("**Job Summary:**"):
            info["job_summary"] = line.split("**Job Summary:**")[1].strip()

    # full_evaluation = everything after the first "---" separator
    try:
        sep_idx = next(i for i, l in enumerate(lines) if l.strip() == "---")
        info["full_evaluation"] = "\n".join(lines[sep_idx + 1:]).strip()
    except StopIteration:
        info["full_evaluation"] = text

    return info


def load_csv_index(csv_path: Path) -> dict:
    """Build a dict keyed by normalized (title, company) from summary.csv."""
    if not csv_path.exists():
        return {}
    index = {}
    try:
        with open(csv_path, newline="", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (
                    row.get("title", "").strip().lower()[:60],
                    row.get("company", "").strip().lower()[:40],
                )
                index[key] = row
    except Exception as e:
        print(f"  Warning: could not read {csv_path}: {e}")
    return index


# ---------------------------------------------------------------------------
# Job migration
# ---------------------------------------------------------------------------
def migrate_jobs(dry_run: bool):
    date_dirs = sorted([d for d in RESULTS_DIR.iterdir() if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', d.name)])
    print(f"\n=== Migrating {len(date_dirs)} job run(s) ===")

    total_runs = 0
    total_jobs = 0

    for date_dir in date_dirs:
        date_str = date_dir.name
        csv_index = load_csv_index(date_dir / "summary.csv")

        # Collect jobs, deduplicating by job_id (same job can appear in multiple verdict dirs)
        run_jobs_by_id = {}
        for verdict in VERDICT_DIRS:
            verdict_dir = date_dir / verdict
            if not verdict_dir.is_dir():
                continue
            for md_file in sorted(verdict_dir.glob("*.md")):
                if md_file.parent.name == "deep":
                    continue
                info = parse_eval_md(md_file, verdict)
                if not info["title"] or not info["company"]:
                    continue

                # Cross-reference CSV for score, source, reasoning, date_posted
                csv_key = (info["title"].lower()[:60], info["company"].lower()[:40])
                csv_row = csv_index.get(csv_key, {})

                job_id = make_job_id(info["title"], info["company"], info["location"])

                job_record = {
                    "job_id": job_id,
                    "title": info["title"],
                    "company": info["company"],
                    "location": info["location"] or "Unknown",
                    "url": info["url"] or "",
                    "source": csv_row.get("source", "unknown"),
                    "salary": info["salary"] or csv_row.get("salary") or None,
                    "date_posted": csv_row.get("date_posted") or None,
                    "tier": info["tier"] or csv_row.get("tier") or None,
                    "match_score": int(csv_row.get("score", 0)) if csv_row.get("score") else None,
                    "match_verdict": info["match_verdict"],
                    "match_reasoning": csv_row.get("reasoning", "")[:500] if csv_row.get("reasoning") else None,
                    "job_summary": info["job_summary"] or None,
                    "full_evaluation": info["full_evaluation"] or None,
                    "deep_evaluation": None,
                    "first_seen_date": date_str,
                    "last_seen_date": date_str,
                    "date_scraped": f"{date_str}T00:00:00Z",
                }

                # Check for deep eval
                deep_path = md_file.parent / "deep" / md_file.name
                if deep_path.exists():
                    deep_text = deep_path.read_text(errors="replace")
                    job_record["deep_evaluation"] = deep_text

                # Dedup: keep first-seen verdict for a given job_id within this run
                if job_id not in run_jobs_by_id:
                    run_jobs_by_id[job_id] = job_record

        run_jobs = list(run_jobs_by_id.values())

        if not run_jobs:
            print(f"  {date_str}: 0 jobs (skipping)")
            continue

        verdict_counts = {}
        for j in run_jobs:
            v = j["match_verdict"]
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

        print(f"  {date_str}: {len(run_jobs)} jobs — {verdict_counts}")

        if dry_run:
            total_runs += 1
            total_jobs += len(run_jobs)
            continue

        # Upsert run record
        run_payload = {
            "run_date": date_str,
            "total_jobs": len(run_jobs),
            "evaluated": len(run_jobs),
            "strong_count": verdict_counts.get("STRONG", 0),
            "moderate_count": verdict_counts.get("MODERATE", 0),
            "stretch_count": verdict_counts.get("STRETCH", 0),
            "weak_count": verdict_counts.get("WEAK", 0),
            "new_job_ids": [],
            "sources": [],
        }
        run_resp = supabase_post(
            "runs",
            run_payload,
            prefer="resolution=merge-duplicates,return=representation",
            on_conflict="run_date",
        )
        run_id = run_resp[0]["id"] if run_resp else None

        # Upsert jobs in batches
        BATCH = 100
        for i in range(0, len(run_jobs), BATCH):
            batch = run_jobs[i:i + BATCH]
            # Set first_seen_run on insert only — workaround: use a separate update for last_seen
            for job in batch:
                job["first_seen_run"] = run_id
                job["last_seen_run"] = run_id
            supabase_post("jobs", batch, on_conflict="job_id")

        # Insert run_jobs junction
        if run_id:
            rj_records = [{"run_id": run_id, "job_id_ref": j["job_id"], "is_new_this_run": False} for j in run_jobs]
            for i in range(0, len(rj_records), BATCH):
                supabase_post("run_jobs", rj_records[i:i + BATCH], prefer="resolution=ignore-duplicates")

        total_runs += 1
        total_jobs += len(run_jobs)
        print(f"    ✓ Upserted run {date_str} ({run_id})")

    print(f"\nJobs migration: {total_runs} runs, {total_jobs} jobs")


# ---------------------------------------------------------------------------
# Freelance migration
# ---------------------------------------------------------------------------
def normalize_company(name: str) -> str:
    name = name.lower().strip()
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc", ", ltd", " ltd"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def make_company_id(name: str, city: str) -> str:
    raw = f"{normalize_company(name)}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def parse_company_md(md_path: Path, tier: str) -> dict:
    """Parse a freelance company markdown file."""
    text = md_path.read_text(errors="replace")
    lines = text.split("\n")

    info = {
        "name": "", "city": "", "state": "", "website": "",
        "category": "", "fit_tier": tier.upper(),
        "fit_score": None, "fit_reasoning": "",
        "full_evaluation": "", "outreach_draft": "", "outreach_subject": "",
        "relationship": "new_prospect", "relationship_notes": "",
    }

    for line in lines:
        if line.startswith("# "):
            header = line[2:].strip()
            # Parse "Name — City, State" from header
            if " — " in header:
                name_part, loc_part = header.split(" — ", 1)
                info["name"] = name_part.strip()
                loc_part = loc_part.strip().rstrip(",").strip()
                if "," in loc_part:
                    city, state = loc_part.rsplit(",", 1)
                    info["city"] = city.strip()
                    info["state"] = state.strip()
                elif loc_part:
                    info["city"] = loc_part
            else:
                info["name"] = header
        elif line.startswith("**Category:**"):
            cat_raw = line.split("**Category:**")[1].strip()
            # Format: "Av Rental | **Website:** https://..."
            if " | " in cat_raw:
                parts = cat_raw.split(" | ", 1)
                info["category"] = parts[0].strip()
                # Extract website from the remainder
                remainder = parts[1]
                if "**Website:**" in remainder:
                    info["website"] = remainder.split("**Website:**")[1].strip()
            else:
                info["category"] = cat_raw
        elif line.startswith("**Website:**"):
            info["website"] = line.split("**Website:**")[1].strip()
        elif line.startswith("**City:**"):
            info["city"] = line.split("**City:**")[1].strip()
        elif line.startswith("**State:**"):
            info["state"] = line.split("**State:**")[1].strip()
        elif line.startswith("**Fit Score:**"):
            try:
                info["fit_score"] = int(re.search(r'\d+', line.split("**Fit Score:**")[1]).group())
            except Exception:
                pass
        elif line.startswith("**Relationship:**"):
            rel_raw = line.split("**Relationship:**")[1].strip()
            # Strip "| **Discovered:** ..." suffix
            if " | " in rel_raw:
                rel_raw = rel_raw.split(" | ", 1)[0].strip()
            info["relationship"] = rel_raw

    # Full evaluation: after first ---
    try:
        sep_idx = next(i for i, l in enumerate(lines) if l.strip() == "---")
        info["full_evaluation"] = "\n".join(lines[sep_idx + 1:]).strip()
    except StopIteration:
        info["full_evaluation"] = text

    if not info["name"]:
        info["name"] = md_path.stem.replace("_", " ")
    # Normalize category to slug form for consistent lookup
    cat = info["category"]
    if cat:
        info["category"] = cat.lower().strip().replace(" ", "_")

    return info


def migrate_freelance(dry_run: bool):
    if not FREELANCE_DIR.exists():
        print("\n=== No freelance/ directory — skipping ===")
        return

    date_dirs = sorted([d for d in FREELANCE_DIR.iterdir()
                        if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', d.name)])
    print(f"\n=== Migrating {len(date_dirs)} freelance run(s) ===")

    total = 0
    TIER_DIRS = ["hot", "warm", "cold"]

    for date_dir in date_dirs:
        date_str = date_dir.name
        companies = []

        for tier_name in TIER_DIRS:
            tier_dir = date_dir / tier_name
            if not tier_dir.is_dir():
                continue
            for md_file in sorted(tier_dir.glob("*.md")):
                info = parse_company_md(md_file, tier_name)
                if not info["name"]:
                    continue
                company_id = make_company_id(info["name"], info["city"])
                companies.append({
                    "company_id": company_id,
                    "name": info["name"],
                    "city": info["city"],
                    "state": info["state"] or None,
                    "website": info["website"] or None,
                    "category": info["category"] or None,
                    "fit_tier": info["fit_tier"],
                    "fit_score": info["fit_score"],
                    "fit_reasoning": info["fit_reasoning"] or None,
                    "full_evaluation": info["full_evaluation"] or None,
                    "outreach_draft": info["outreach_draft"] or None,
                    "outreach_subject": info["outreach_subject"] or None,
                    "relationship": info["relationship"],
                    "relationship_notes": info["relationship_notes"] or None,
                    "first_seen_date": date_str,
                    "last_seen_date": date_str,
                })

        # Deduplicate by company_id within the same run (keep first/highest tier)
        seen = {}
        for c in companies:
            cid = c["company_id"]
            if cid not in seen:
                seen[cid] = c
        companies = list(seen.values())

        print(f"  {date_str}: {len(companies)} companies")

        if dry_run or not companies:
            total += len(companies)
            continue

        BATCH = 100
        for i in range(0, len(companies), BATCH):
            supabase_post("freelance_companies", companies[i:i + BATCH], on_conflict="company_id")

        total += len(companies)
        print(f"    ✓ Upserted {len(companies)} companies")

    print(f"\nFreelance migration: {total} companies")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Migrate results/ and freelance/ data to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Count files only, do not write to Supabase")
    parser.add_argument("--jobs-only", action="store_true", help="Only migrate job results")
    parser.add_argument("--freelance-only", action="store_true", help="Only migrate freelance data")
    args = parser.parse_args()

    if not os.environ.get("SUPABASE_URL"):
        print("ERROR: SUPABASE_URL env var not set")
        sys.exit(1)
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        print("ERROR: SUPABASE_SERVICE_ROLE_KEY env var not set")
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN — no data will be written\n")

    if not args.freelance_only:
        migrate_jobs(args.dry_run)

    if not args.jobs_only:
        migrate_freelance(args.dry_run)

    if args.dry_run:
        print("\nDry run complete. Run without --dry-run to write to Supabase.")


if __name__ == "__main__":
    main()
