"""Resume download helpers: active resume and per-user resume."""

import os
from pathlib import Path
from typing import Optional

import requests

from pipeline.config import log, SCRIPT_DIR
from pipeline.sync.client import _supabase_headers


def download_active_resume(config: dict) -> Optional[Path]:
    """
    Download the primary resume from Supabase Storage.
    Returns local path on success, None if Supabase is not configured.
    Falls back to local resume.txt if no primary is set or on error.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return None

    try:
        headers = _supabase_headers(supabase_key)
        resp = requests.get(
            f"{supabase_url}/rest/v1/resumes?is_primary=eq.true&select=id,file_path,file_name",
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            log.info("Supabase: no primary resume set -- using local file")
            return None

        row = rows[0]
        file_path = row["file_path"]
        file_name = row["file_name"]
        ext = Path(file_name).suffix or ".txt"

        dl = requests.get(
            f"{supabase_url}/storage/v1/object/resumes/{file_path}",
            headers=headers, timeout=30,
        )
        dl.raise_for_status()

        local_path = SCRIPT_DIR / f"resume_active{ext}"
        local_path.write_bytes(dl.content)
        log.info(f"Supabase: downloaded active resume '{file_name}' -> {local_path}")
        return local_path

    except Exception as e:
        log.warning(f"Supabase: could not download resume ({e}) -- using local file")
        return None


def download_resume_for_user(
    config: dict,
    user_id: str,
    file_path: str,
    file_name: str,
) -> Optional[Path]:
    """Download a specific user's primary resume to a per-user local path."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return None
    try:
        ext = Path(file_name).suffix or ".txt"
        dl = requests.get(
            f"{supabase_url}/storage/v1/object/resumes/{file_path}",
            headers=_supabase_headers(supabase_key), timeout=30,
        )
        dl.raise_for_status()
        local_path = SCRIPT_DIR / f"resume_active_{user_id[:8]}{ext}"
        local_path.write_bytes(dl.content)
        log.info(f"Multi-user: downloaded resume for {user_id[:8]}... -> {local_path.name}")
        return local_path
    except Exception as e:
        log.warning(f"Multi-user: could not download resume for {user_id[:8]}... ({e})")
        return None
