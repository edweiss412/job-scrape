"""Job description fetching: BS4, Playwright fallback, batch, and backfill."""

import atexit
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from pipeline.config import console, log
from pipeline.models import JobListing
from pipeline.urls import _is_indirect_url, _resolve_apply_url


# ---------------------------------------------------------------------------
# Supabase headers helper (inlined to avoid circular imports with sync/)
# ---------------------------------------------------------------------------
def _supabase_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Job description fetcher
# ---------------------------------------------------------------------------
def fetch_job_description(url: str, use_playwright_fallback: bool = True) -> str:
    """
    Fetch the full job description from a listing URL.
    Tries requests+BS4 first; falls back to Playwright for JS-rendered pages.
    """
    if not url:
        return ""

    desc = _fetch_description_bs4(url)
    if len(desc.strip()) < 100 and use_playwright_fallback:
        log.debug(f"BS4 returned <100 chars for {url}, trying Playwright")
        desc = _fetch_description_playwright(url)
    return desc


def _fetch_description_bs4(url: str) -> str:
    """Fetch job description using requests + BeautifulSoup (fast, no JS)."""
    try:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Try to find the job description container
        # ATS-specific selectors first, then generic fallbacks
        desc_selectors = [
            # Workday
            "[data-automation-id='jobPostingDescription']",
            # Greenhouse
            "#content .job-post-content", ".job__description",
            # Lever
            ".posting-page .content", ".section-wrapper.page-full-width",
            # iCIMS
            ".iCIMS_JobContent", ".iCIMS_MainWrapper",
            # SmartRecruiters
            ".job-sections", ".st-wrapper",
            # Taleo
            ".requisitionDescription", "#requisitionDescriptionInterface",
            # Jobvite
            ".jv-job-detail-description",
            # Ashby
            "[data-testid='job-description']", ".ashby-job-posting-description",
            # Paycom / Paylocity
            ".job-description", ".job-details-content",
            # Generic (existing, kept as fallback)
            "[class*='description']",
            "[class*='Description']",
            "[id*='description']",
            "[class*='job-details']",
            "[class*='jobDetail']",
            "article",
            ".content",
            "main",
        ]
        for selector in desc_selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text("\n", strip=True)
                if len(text) > 100:
                    return text[:5000]  # Truncate for LLM context

        # Fallback: get all text
        text = soup.get_text("\n", strip=True)
        return text[:5000]

    except Exception as e:
        log.debug(f"Could not fetch description from {url}: {e}")
        return ""


# ---------------------------------------------------------------------------
# Playwright fallback for JS-rendered job descriptions
# ---------------------------------------------------------------------------
_pw_browser = None  # Lazy singleton — initialized on first use


def _get_pw_browser():
    """Return a shared headless Chromium browser instance (lazy init)."""
    global _pw_browser
    if _pw_browser is None:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            _pw_browser = pw.chromium.launch(headless=True)
            atexit.register(_close_playwright)
            log.info("Playwright browser launched for description fetching")
        except Exception as e:
            log.warning(f"Playwright unavailable: {e}")
            return None
    return _pw_browser


def _close_playwright():
    """Shutdown Playwright browser on exit."""
    global _pw_browser
    if _pw_browser is not None:
        try:
            _pw_browser.close()
        except Exception:
            pass
        _pw_browser = None


def _fetch_description_playwright(url: str) -> str:
    """Fetch job description from a JS-rendered page using Playwright."""
    browser = _get_pw_browser()
    if browser is None:
        return ""

    try:
        page = browser.new_page()
        page.set_default_timeout(15000)
        page.goto(url, wait_until="domcontentloaded")
        # Wait for network idle or 5s, whichever comes first
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass  # Timeout is fine — page may have long-polling

        # Try the same CSS selector cascade as BS4 path
        # ATS-specific selectors first, then generic fallbacks
        desc_selectors = [
            # Workday
            "[data-automation-id='jobPostingDescription']",
            # Greenhouse
            "#content .job-post-content", ".job__description",
            # Lever
            ".posting-page .content", ".section-wrapper.page-full-width",
            # iCIMS
            ".iCIMS_JobContent", ".iCIMS_MainWrapper",
            # SmartRecruiters
            ".job-sections", ".st-wrapper",
            # Taleo
            ".requisitionDescription", "#requisitionDescriptionInterface",
            # Jobvite
            ".jv-job-detail-description",
            # Ashby
            "[data-testid='job-description']", ".ashby-job-posting-description",
            # Paycom / Paylocity
            ".job-description", ".job-details-content",
            # Generic fallbacks
            "[class*='description']",
            "[class*='Description']",
            "[id*='description']",
            "[class*='job-details']",
            "[class*='jobDetail']",
            "article",
            ".content",
            "main",
        ]
        for selector in desc_selectors:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text()
                if text and len(text.strip()) > 100:
                    page.close()
                    return text.strip()[:5000]

        # Fallback: full body text
        text = page.inner_text("body")
        page.close()
        return text.strip()[:5000] if text else ""

    except Exception as e:
        log.debug(f"Playwright fetch failed for {url}: {e}")
        try:
            page.close()
        except Exception:
            pass
        return ""


# ---------------------------------------------------------------------------
# Batch description fetching
# ---------------------------------------------------------------------------
def _fetch_desc_for_job(job: JobListing) -> str:
    """Fetch description for a single job, resolving indirect URLs first.
    Skips Playwright fallback — batch function handles that in a separate pass."""
    url = job.url
    if url and _is_indirect_url(url):
        url = _resolve_apply_url(url)
        job.url = url
    return fetch_job_description(url, use_playwright_fallback=False) if url else ""


def fetch_descriptions_batch(jobs: list[JobListing], max_workers: int = 8) -> list[JobListing]:
    """Fetch job descriptions in parallel for all jobs that don't already have one."""
    need_fetch = [j for j in jobs if not j.description and j.url]
    already = len(jobs) - len(need_fetch)
    if already:
        console.print(f"[dim]Descriptions: {already} already populated, fetching {len(need_fetch)}[/dim]")

    if not need_fetch:
        return jobs

    console.print(f"[bold]Fetching descriptions for {len(need_fetch)} jobs...[/bold]")
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_fetch_desc_for_job, j): j for j in need_fetch
        }
        for future in as_completed(future_map):
            completed += 1
            job = future_map[future]
            try:
                desc = future.result()
                if desc:
                    job.description = desc
            except Exception as e:
                log.debug(f"Description fetch failed for {job.title}: {e}")
            if completed % 20 == 0:
                console.print(f"  [dim]{completed}/{len(need_fetch)} descriptions fetched[/dim]")

    fetched = sum(1 for j in need_fetch if j.description)
    console.print(f"  Fetched {fetched}/{len(need_fetch)} descriptions (BS4 pass)")

    # Pass 2: parallel Playwright fallback for jobs still missing descriptions
    still_empty = [j for j in need_fetch if not j.description and j.url]
    if still_empty:
        # Prioritize Indeed jobs — their RSS snippets are always incomplete
        still_empty.sort(key=lambda j: (0 if 'indeed' in (j.source or '') else 1))
        console.print(f"[bold]Retrying {len(still_empty)} jobs with Playwright (3 workers)...[/bold]")
        pw_fetched = 0
        pw_completed = 0

        def _pw_fetch(job):
            return job, _fetch_description_playwright(job.url)

        with ThreadPoolExecutor(max_workers=3) as pw_executor:
            pw_futures = {pw_executor.submit(_pw_fetch, j): j for j in still_empty}
            for future in as_completed(pw_futures):
                pw_completed += 1
                try:
                    job, desc = future.result()
                    if desc:
                        job.description = desc
                        pw_fetched += 1
                except Exception as e:
                    log.debug(f"Playwright worker failed: {e}")
                if pw_completed % 10 == 0:
                    console.print(f"  [dim]Playwright: {pw_completed}/{len(still_empty)} attempted[/dim]")
        console.print(f"  Playwright fetched {pw_fetched}/{len(still_empty)} additional descriptions")

    total_fetched = sum(1 for j in need_fetch if j.description)
    total_with_desc = already + total_fetched
    total_missing = len(jobs) - total_with_desc
    console.print(f"  Total: {total_fetched}/{len(need_fetch)} descriptions populated")
    if total_missing:
        console.print(f"  [yellow]Warning: {total_missing}/{len(jobs)} jobs have no description — keyword scoring and LLM eval will be title-only[/yellow]")
        missing_jobs = [j for j in jobs if not j.description]
        for j in missing_jobs[:10]:
            console.print(f"    [dim]- {j.title} @ {j.company} ({j.source})[/dim]")
        if total_missing > 10:
            console.print(f"    [dim]  ... and {total_missing - 10} more[/dim]")

        # Log description fetch failure domains for debugging
        domain_counts = Counter()
        for j in missing_jobs:
            try:
                domain_counts[urlparse(j.url).hostname or "unknown"] += 1
            except Exception:
                domain_counts["unknown"] += 1
        top_failures = domain_counts.most_common(10)
        log.warning(f"Description fetch failures by domain: {top_failures}")

    return jobs


def backfill_missing_descriptions(config: dict, max_jobs: int = 200):
    """
    Fetch descriptions for active jobs in Supabase that have no description.
    These are jobs where the initial fetch failed (site down, rate-limited, etc.)
    but may succeed on a subsequent attempt days later.

    Respects a retry cap: jobs with description_fetch_attempts >= 5 are marked
    description_unfetchable=true and excluded from future attempts.
    """
    MAX_FETCH_ATTEMPTS = 5

    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return 0

    headers = _supabase_headers(supabase_key)

    # Fetch active jobs with no description, excluding permanently unfetchable ones
    # Order by fewest attempts first (retry least-tried jobs first)
    resp = requests.get(
        f"{supabase_url}/rest/v1/jobs"
        f"?listing_status=eq.active"
        f"&description=is.null"
        f"&description_unfetchable=eq.false"
        f"&url=neq."
        f"&select=job_id,title,company,url,description_fetch_attempts"
        f"&order=description_fetch_attempts.asc,date_scraped.asc"
        f"&limit={max_jobs}",
        headers=headers, timeout=30,
    )
    if not resp.ok:
        log.warning(f"Description backfill: failed to query jobs: {resp.status_code}")
        return 0

    jobs_to_fill = resp.json()
    if not jobs_to_fill:
        return 0

    console.print(f"[bold]Backfilling descriptions for {len(jobs_to_fill)} jobs with missing descriptions...[/bold]")

    filled = 0
    newly_unfetchable = 0

    def _try_fetch(row):
        url = row["url"]
        if _is_indirect_url(url):
            url = _resolve_apply_url(url)
        desc = fetch_job_description(url, use_playwright_fallback=True)
        return row["job_id"], desc, url

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_try_fetch, r): r for r in jobs_to_fill}
        for future in as_completed(futures):
            row = futures[future]
            job_id = row["job_id"]
            current_attempts = row.get("description_fetch_attempts", 0) or 0
            try:
                job_id, desc, resolved_url = future.result()
                if desc and len(desc.strip()) >= 50:
                    payload = {
                        "description": desc[:50000],
                        "description_length": len(desc),
                        "description_fetch_attempts": current_attempts + 1,
                    }
                    # Also update URL if it was resolved from an indirect link
                    if resolved_url != row["url"]:
                        payload["url"] = resolved_url
                    requests.patch(
                        f"{supabase_url}/rest/v1/jobs?job_id=eq.{job_id}",
                        headers=headers, json=payload, timeout=10,
                    )
                    filled += 1
                else:
                    # Failed fetch — increment attempts, maybe mark unfetchable
                    new_attempts = current_attempts + 1
                    fail_payload = {"description_fetch_attempts": new_attempts}
                    if new_attempts >= MAX_FETCH_ATTEMPTS:
                        fail_payload["description_unfetchable"] = True
                        newly_unfetchable += 1
                    requests.patch(
                        f"{supabase_url}/rest/v1/jobs?job_id=eq.{job_id}",
                        headers=headers, json=fail_payload, timeout=10,
                    )
            except Exception as e:
                log.debug(f"Description backfill failed for {row.get('title', '?')}: {e}")
                # Still increment attempt counter on exception
                new_attempts = current_attempts + 1
                fail_payload = {"description_fetch_attempts": new_attempts}
                if new_attempts >= MAX_FETCH_ATTEMPTS:
                    fail_payload["description_unfetchable"] = True
                    newly_unfetchable += 1
                try:
                    requests.patch(
                        f"{supabase_url}/rest/v1/jobs?job_id=eq.{job_id}",
                        headers=headers, json=fail_payload, timeout=10,
                    )
                except Exception:
                    pass

    console.print(f"  Backfilled {filled}/{len(jobs_to_fill)} descriptions")
    if newly_unfetchable:
        console.print(f"  Marked {newly_unfetchable} jobs as permanently unfetchable (>={MAX_FETCH_ATTEMPTS} attempts)")
    return filled
