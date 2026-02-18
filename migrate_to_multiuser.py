#!/usr/bin/env python3
"""
One-time migration: assign existing single-user data to the admin user.

Steps:
  1. Find admin user UUID via Supabase Auth admin API
  2. Patch all runs WHERE user_id IS NULL → admin UUID
  3. Patch all interview_qa WHERE user_id IS NULL → admin UUID
  4. Copy jobs with evaluations → user_evaluations (admin user)
  5. Upsert user_profiles row for admin
  6. Print verification counts

Usage:
    python migrate_to_multiuser.py              # Live run
    python migrate_to_multiuser.py --dry-run    # Print counts only, no writes

After this script succeeds, apply the UNIQUE constraint in the Supabase SQL editor:
    ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_run_date_key;
    ALTER TABLE runs ADD CONSTRAINT runs_user_run_date_key UNIQUE (user_id, run_date);
"""

import argparse
import os
import sys

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "edweiss412@gmail.com")


def headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def get_admin_uuid() -> str:
    """Fetch the admin user's UUID from Supabase Auth."""
    resp = requests.get(
        f"{SUPABASE_URL}/auth/v1/admin/users?page=1&per_page=1000",
        headers=headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    users = data.get("users", data) if isinstance(data, dict) else data
    for u in users:
        if u.get("email") == ADMIN_EMAIL:
            return u["id"]
    raise SystemExit(f"ERROR: Could not find user with email {ADMIN_EMAIL!r} in Supabase Auth")


def count(table: str, where: str = "") -> int:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if where:
        url += f"?{where}"
    resp = requests.get(
        url,
        headers={**headers(), "Prefer": "count=exact", "Accept": "application/json"},
        params={"select": "id"},
        timeout=15,
    )
    resp.raise_for_status()
    content_range = resp.headers.get("Content-Range", "")
    # Content-Range: 0-99/150 → total = 150
    if "/" in content_range:
        return int(content_range.split("/")[1])
    return len(resp.json())


def patch_nulls(table: str, payload: dict, dry_run: bool = False):
    """Patch all rows where user_id IS NULL."""
    n = count(table, "user_id=is.null")
    print(f"  {table}: {n} rows with user_id IS NULL")
    if dry_run or n == 0:
        return n
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}?user_id=is.null",
        headers={**headers(), "Prefer": "return=minimal"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    print(f"  {table}: patched {n} rows ✓")
    return n


def migrate_user_evaluations(admin_uuid: str, dry_run: bool = False) -> int:
    """
    Batch-copy jobs with evaluations into user_evaluations for the admin user.
    Uses resolution=ignore-duplicates so re-running is safe.
    """
    BATCH = 200
    page = 0
    total_inserted = 0

    while True:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/jobs"
            f"?match_verdict=not.is.null"
            f"&select=job_id,match_score,match_verdict,match_reasoning,job_summary,full_evaluation,deep_evaluation"
            f"&offset={page * BATCH}&limit={BATCH}",
            headers=headers(),
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        if not dry_run:
            records = [{
                "user_id": admin_uuid,
                "job_id": j["job_id"],
                "match_score": j.get("match_score"),
                "match_verdict": j.get("match_verdict"),
                "match_reasoning": j.get("match_reasoning"),
                "job_summary": j.get("job_summary"),
                "full_evaluation": j.get("full_evaluation"),
                "deep_evaluation": j.get("deep_evaluation"),
            } for j in batch]

            ins = requests.post(
                f"{SUPABASE_URL}/rest/v1/user_evaluations",
                headers={**headers(), "Prefer": "resolution=ignore-duplicates"},
                json=records,
                timeout=60,
            )
            ins.raise_for_status()

        total_inserted += len(batch)
        page += 1
        if len(batch) < BATCH:
            break

    print(f"  user_evaluations: {'would copy' if dry_run else 'copied'} {total_inserted} rows ✓")
    return total_inserted


def upsert_admin_profile(admin_uuid: str, dry_run: bool = False):
    """Create a user_profiles row for the admin if it doesn't exist yet."""
    if dry_run:
        print("  user_profiles: would upsert admin profile (dry-run)")
        return
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/user_profiles",
        headers={**headers(), "Prefer": "resolution=ignore-duplicates"},
        json=[{
            "user_id": admin_uuid,
            "notify_email": ADMIN_EMAIL,
        }],
        timeout=15,
    )
    resp.raise_for_status()
    print("  user_profiles: admin profile upserted ✓")


def main():
    parser = argparse.ArgumentParser(description="Migrate Job Scout to multi-user architecture")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, no writes")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars must be set")

    dry_run = args.dry_run
    label = "[DRY RUN] " if dry_run else ""
    print(f"{label}Starting multi-user migration…\n")

    print("Step 1: Locate admin user")
    admin_uuid = get_admin_uuid()
    print(f"  Admin UUID: {admin_uuid}\n")

    print("Step 2: Assign orphaned runs to admin")
    patch_nulls("runs", {"user_id": admin_uuid}, dry_run=dry_run)
    print()

    print("Step 3: Assign orphaned interview_qa to admin")
    patch_nulls("interview_qa", {"user_id": admin_uuid}, dry_run=dry_run)
    print()

    print("Step 4: Copy job evaluations → user_evaluations")
    migrate_user_evaluations(admin_uuid, dry_run=dry_run)
    print()

    print("Step 5: Upsert admin user_profiles row")
    upsert_admin_profile(admin_uuid, dry_run=dry_run)
    print()

    print("Step 6: Verification counts")
    print(f"  runs with user_id: {count('runs', 'user_id=not.is.null')}")
    print(f"  interview_qa with user_id: {count('interview_qa', 'user_id=not.is.null')}")
    print(f"  user_evaluations total: {count('user_evaluations')}")
    print(f"  user_profiles total: {count('user_profiles')}")
    print()

    if dry_run:
        print("[DRY RUN] No data was written. Run without --dry-run to apply changes.")
    else:
        print("Migration complete!")
        print()
        print("Next step — run in Supabase SQL editor:")
        print("  ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_run_date_key;")
        print("  ALTER TABLE runs ADD CONSTRAINT runs_user_run_date_key UNIQUE (user_id, run_date);")


if __name__ == "__main__":
    main()
