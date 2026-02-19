#!/usr/bin/env python3
"""
fix_freelance_names.py

One-time backfill: reads all freelance_companies rows from Supabase, uses
an LLM via OpenRouter to extract the real company name from each row's
full_evaluation, and updates the name column.

Usage:
    python fix_freelance_names.py              # Full backfill
    python fix_freelance_names.py --dry-run    # Show renames without writing

Required env vars:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

Also needs openrouter_key in config.yaml (or OPENROUTER_KEY env var).
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests
import yaml

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


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


def supabase_patch(url_path: str, payload: dict, params: dict = None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    resp = requests.patch(
        f"{base}/rest/v1/{url_path}",
        headers=get_supabase_headers(),
        json=payload,
        params=params,
        timeout=30,
    )
    if not resp.ok:
        print(f"  ERROR {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Config + LLM setup
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    val = os.environ.get("OPENROUTER_KEY")
    if val:
        config["openrouter_key"] = val
    return config


def extract_name_via_llm(client, model: str, current_name: str, evaluation_text: str) -> str:
    """Ask the LLM to extract the real company name from the evaluation."""
    snippet = evaluation_text[:600]
    prompt = f"""The following is an LLM evaluation of a company. The current stored name is "{current_name}", which may be wrong (it might be a page title like "About Us", "Careers", "Contact", "Audio", etc. instead of a real company name).

Extract the ACTUAL company name from the evaluation text below. Reply with ONLY the company name — nothing else.

---
{snippet}"""

    response = client.chat.completions.create(
        model=model,
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
        extra_headers={
            "HTTP-Referer": "https://github.com/job-scraper",
            "X-Title": "Freelance Name Fix",
        },
    )
    return response.choices[0].message.content.strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Fix freelance company names via LLM extraction")
    parser.add_argument("--dry-run", action="store_true", help="Show renames without writing to Supabase")
    args = parser.parse_args()

    if not os.environ.get("SUPABASE_URL"):
        print("ERROR: SUPABASE_URL env var not set")
        sys.exit(1)
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        print("ERROR: SUPABASE_SERVICE_ROLE_KEY env var not set")
        sys.exit(1)

    config = load_config()
    api_key = config.get("openrouter_key", "")
    if not api_key:
        print("ERROR: openrouter_key not set in config.yaml or OPENROUTER_KEY env var")
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    model = config.get("openrouter_model", "google/gemini-3-flash-preview")

    # Fetch all freelance companies that have evaluations
    print(f"Using model: {model}")
    print("Fetching freelance_companies from Supabase...")
    rows = supabase_get("freelance_companies", params={
        "select": "company_id,name,full_evaluation",
        "full_evaluation": "neq.",
        "order": "name.asc",
        "limit": "1000",
    })
    print(f"  Found {len(rows)} companies with evaluations")

    renamed = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(rows):
        cid = row["company_id"]
        old_name = row["name"]
        evaluation = row.get("full_evaluation", "")

        if not evaluation:
            skipped += 1
            continue

        try:
            new_name = extract_name_via_llm(client, model, old_name, evaluation)
        except Exception as e:
            print(f"  [{i+1}/{len(rows)}] ERROR on '{old_name}': {e}")
            errors += 1
            continue

        if not new_name or new_name.lower() == old_name.lower():
            skipped += 1
            continue

        print(f"  [{i+1}/{len(rows)}] '{old_name}' → '{new_name}'")
        renamed += 1

        if not args.dry_run:
            supabase_patch("freelance_companies", {"name": new_name}, params={
                "company_id": f"eq.{cid}",
            })

        # Small delay to avoid rate limiting
        time.sleep(0.1)

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{mode}Done! Renamed: {renamed}, Skipped (unchanged): {skipped}, Errors: {errors}")


if __name__ == "__main__":
    main()
