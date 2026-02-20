#!/usr/bin/env python3
"""
Job Search Automation Pipeline
===============================
Scrapes job listings from multiple sources, deduplicates them,
and scores each against your resume using Claude.

Sources:
  1. SerpAPI or BrightData (Google Jobs) — best aggregator, pulls from LinkedIn/Indeed/etc.
  2. Indeed RSS feeds — free, no API key needed
  3. AVIXA Career Center — AV-industry-specific
  4. Direct career page scraping — for target companies

Usage:
  python job_scraper.py                  # Full scan, all sources
  python job_scraper.py --quick          # Quick scan (SerpAPI + Indeed only)
  python job_scraper.py --evaluate-only  # Re-score existing results with LLM
  python job_scraper.py --no-deep        # Skip deep evaluation of STRONG matches
  python job_scraper.py --schedule       # Run on configured schedule

Requirements:
  pip install requests beautifulsoup4 pyyaml feedparser anthropic rich
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode, urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
console = Console(force_terminal=False, no_color=True) if os.environ.get("CI") else Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("job_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("job_scraper")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = SCRIPT_DIR / "results"

DATA_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class JobListing:
    title: str
    company: str
    location: str
    url: str
    source: str  # serpapi, indeed_rss, avixa, career_page
    description: str = ""
    salary: str = ""
    date_posted: str = ""
    date_scraped: str = field(default_factory=lambda: datetime.now().isoformat())
    job_id: str = ""  # dedupe hash
    match_score: int = 0
    match_reasoning: str = ""
    match_verdict: str = ""  # STRONG / MODERATE / STRETCH / WEAK
    full_evaluation: str = ""  # Full structured evaluation text
    tier: str = ""  # From target company list
    job_summary: str = ""  # 2-sentence summary of the role itself

    @staticmethod
    def _normalize_location(loc: str) -> str:
        """Normalize location for dedup — strip country suffixes, translations, extra whitespace."""
        import re as _re
        # Remove common country suffixes (English, Spanish, Portuguese, etc.)
        loc = _re.sub(
            r',?\s*(United States|USA|US|Estados Unidos|Est\w+\s+Uni\w+)$',
            '', loc, flags=_re.IGNORECASE,
        ).strip().rstrip(',').strip()
        # Collapse whitespace
        loc = _re.sub(r'\s+', ' ', loc)
        return loc

    def __post_init__(self):
        if not self.job_id:
            norm_loc = self._normalize_location(self.location)
            raw = f"{self.title}|{self.company}|{norm_loc}".lower().strip()
            self.job_id = hashlib.md5(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found: {CONFIG_PATH}[/red]")
        console.print("Copy config.yaml.example to config.yaml and fill in your API keys.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Allow env vars to override config values (for CI / GitHub Actions secrets)
    env_overrides = {
        "serpapi_key": "SERPAPI_KEY",
        "brightdata_api_token": "BRIGHTDATA_API_TOKEN",
        "brightdata_zone": "BRIGHTDATA_ZONE",
        "openrouter_key": "OPENROUTER_KEY",
        "google_aistudio_key": "GOOGLE_AISTUDIO_KEY",
    }
    for config_key, env_var in env_overrides.items():
        val = os.environ.get(env_var)
        if val:
            config[config_key] = val

    return config


def resolve_model(config: dict, role: str) -> tuple[str, str]:
    """Return (provider, model_id) for *role* from the centralized models section.

    Falls back to legacy per-provider keys so existing configs still work.
    """
    models = config.get("models", {})
    entry = models.get(role, {})
    if entry.get("model"):
        provider = entry.get("provider", config.get("llm_provider", "openrouter"))
        return provider, entry["model"]

    # Role-specific legacy fallbacks
    if role == "deep_eval":
        deep_cfg = config.get("deep_eval", {})
        if deep_cfg.get("model"):
            return deep_cfg.get("provider", "openrouter"), deep_cfg["model"]
    elif role == "freelance_eval":
        fl_cfg = config.get("freelance_search", {})
        if fl_cfg.get("llm_model"):
            provider = fl_cfg.get("llm_provider", config.get("llm_provider", "google_aistudio"))
            return provider, fl_cfg["llm_model"]

    # Generic legacy fallback — derive from the active provider's top-level key
    provider = config.get("llm_provider", "openrouter")
    legacy_map = {
        "openrouter": ("openrouter_model", "anthropic/claude-sonnet-4"),
        "anthropic": ("anthropic_model", "claude-sonnet-4-20250514"),
        "google_aistudio": ("google_aistudio_model", "gemini-2.5-flash"),
        "openai_compatible": ("openai_compatible_model", "local-model"),
    }
    key, default = legacy_map.get(provider, ("openrouter_model", "anthropic/claude-sonnet-4"))
    return provider, config.get(key, default)


def load_resume(config: dict) -> str:
    """Load resume text from file."""
    resume_path = Path(config.get("resume_path", "resume.txt"))
    if not resume_path.is_absolute():
        resume_path = SCRIPT_DIR / resume_path

    if not resume_path.exists():
        console.print(f"[yellow]Resume not found at {resume_path}[/yellow]")
        console.print("Place your resume as resume.txt in the job-scraper directory.")
        return ""

    suffix = resume_path.suffix.lower()
    if suffix == ".txt" or suffix == ".md":
        return resume_path.read_text()
    elif suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(resume_path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            log.warning("Install pdfplumber to read PDF resumes: pip install pdfplumber")
            return ""
    elif suffix == ".docx":
        try:
            import docx
            doc = docx.Document(resume_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            log.warning("Install python-docx to read DOCX resumes: pip install python-docx")
            return ""
    else:
        return resume_path.read_text()


# ---------------------------------------------------------------------------
# Apply URL selection helpers
# ---------------------------------------------------------------------------

# Direct employer ATS platforms — highest quality apply links
ATS_DOMAINS = {"greenhouse.io", "lever.co", "myworkdayjobs.com", "icims.com",
               "smartrecruiters.com", "ashbyhq.com", "breezy.hr", "jobvite.com"}

# Aggregator / recruiter intermediaries — deprioritized
AGGREGATOR_DOMAINS = {"indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
                      "dice.com", "monster.com", "careerbuilder.com", "simplyhired.com",
                      "teal.com", "adzuna.com", "talent.com", "jooble.org"}


def _url_domain_score(url: str) -> int:
    """Score a URL by its domain: ATS → 100, unknown → 50, aggregator → 10."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return 0
    host = host.lower()
    for domain in ATS_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return 100
    for domain in AGGREGATOR_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return 10
    return 50


def _pick_best_apply_url(options: list[dict], fallback: str = "") -> str:
    """Pick the best apply URL from a list of {link, title} dicts."""
    if not options:
        return fallback
    best_url = fallback
    best_score = -1
    for opt in options:
        link = opt.get("link", "")
        if not link:
            continue
        score = _url_domain_score(link)
        if score > best_score:
            best_score = score
            best_url = link
    return best_url or fallback


def _is_indirect_url(url: str) -> bool:
    """Check if a URL is a Google search link or aggregator that likely redirects."""
    if not url:
        return False
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    # Google Jobs deep links
    if ("google.com" in host or "google.co" in host) and "ibp=htl" in url:
        return True
    for domain in AGGREGATOR_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _resolve_apply_url(url: str) -> str:
    """Follow redirects via HEAD request to get the final employer URL."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5,
                             headers={"User-Agent": "Mozilla/5.0"})
        final = resp.url
        # Only use the resolved URL if it looks better than what we started with
        if final and _url_domain_score(final) >= _url_domain_score(url):
            return final
    except Exception:
        pass
    return url


# ---------------------------------------------------------------------------
# Source 1: SerpAPI (Google Jobs)
# ---------------------------------------------------------------------------
class SerpAPIScraper:
    """
    Uses SerpAPI to query Google Jobs. This is the single best source
    because Google Jobs aggregates from LinkedIn, Indeed, Glassdoor,
    ZipRecruiter, and company career pages.

    Free tier: 100 searches/month.
    Docs: https://serpapi.com/google-jobs-api
    """

    BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, results_per_query: int = 10):
        self.api_key = api_key
        self.results_per_query = results_per_query
        self._rate_limited = False

    def search(self, query: str, location: str) -> list[JobListing]:
        if not self.api_key:
            log.warning("SerpAPI key not set — skipping Google Jobs")
            return []

        params = {
            "engine": "google_jobs",
            "q": query,
            "location": location,
            "api_key": self.api_key,
            "num": self.results_per_query,
        }

        try:
            log.info(f"SerpAPI: '{query}' in {location}")
            resp = requests.get(self.BASE_URL, params=params, timeout=30)
            if resp.status_code == 429:
                log.warning("SerpAPI quota exhausted (429)")
                self._rate_limited = True
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"SerpAPI error: {e}")
            return []

        from pipeline_utils import log_api_usage
        log_api_usage(
            source="external", category="search_api", operation="serpapi_search",
            provider="serpapi", cost_usd=0.01, success=True,
            http_status=resp.status_code,
        )

        jobs = []
        for item in data.get("jobs_results", []):
            # Try to get the full description via the job details endpoint
            description = item.get("description", "")

            # Extract salary if available
            salary = ""
            for ext in item.get("detected_extensions", {}).items():
                if "salary" in str(ext).lower():
                    salary = str(ext)
            if item.get("detected_extensions", {}).get("salary"):
                salary = item["detected_extensions"]["salary"]

            # Pick the best apply link — prefer ATS domains over aggregators
            raw_options = item.get("apply_options", [])
            fallback = item.get("share_link", item.get("link", ""))
            url = _pick_best_apply_url(raw_options, fallback=fallback)

            # If we're stuck with a Google/aggregator link and have no description,
            # try resolving the URL now so fetch_job_description has a real target later
            if _is_indirect_url(url) and not description:
                resolved = _resolve_apply_url(url)
                if resolved != url and not _is_indirect_url(resolved):
                    url = resolved

            job = JobListing(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("location", location),
                url=url,
                source="serpapi_google_jobs",
                description=description,
                salary=salary,
                date_posted=item.get("detected_extensions", {}).get("posted_at", ""),
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict) -> list[JobListing]:
        all_jobs = []
        locations = config["search"]["locations"]
        query_groups = config["queries"]

        for group_name, queries in query_groups.items():
            for query in queries:
                for location in locations:
                    if self._rate_limited:
                        log.warning("SerpAPI rate-limited — stopping queries")
                        return all_jobs
                    jobs = self.search(query, location)
                    all_jobs.extend(jobs)
                    time.sleep(1)  # Rate limiting

        return all_jobs


# ---------------------------------------------------------------------------
# Source 1b: BrightData SERP API (Google Jobs)
# ---------------------------------------------------------------------------
class BrightDataScraper:
    """
    Uses BrightData SERP API to query Google Jobs. Drop-in alternative
    to SerpAPIScraper when SerpAPI monthly quota is exhausted.

    Pay-as-you-go: $1.50/CPM (~$0.0015/request).
    Docs: https://docs.brightdata.com/scraping-automation/serp-api/introduction
    """

    API_URL = "https://api.brightdata.com/request"

    def __init__(self, api_token: str, zone: str = "serp_api1", results_per_query: int = 10):
        self.api_token = api_token
        self.zone = zone
        self.results_per_query = results_per_query

    def search(self, query: str, location: str) -> list[JobListing]:
        if not self.api_token:
            log.warning("BrightData API token not set — skipping Google Jobs")
            return []

        # BrightData uses gl/hl for country; city goes into the query string.
        # Strip boolean OR syntax — Google Jobs handles space-separated terms fine,
        # and quoted OR queries cause timeouts through BrightData's parser.
        clean_query = query.replace('" OR "', " ").replace('"', "").strip()
        city = location.split(",")[0].strip()
        search_query = f"{clean_query} {city}"

        # ibp=htl;jobs triggers Google Jobs view (semicolon must NOT be url-encoded)
        google_url = (
            f"https://www.google.com/search"
            f"?q={requests.utils.quote(search_query)}"
            f"&ibp=htl;jobs&gl=us&hl=en&brd_json=1"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        payload = {
            "zone": self.zone,
            "url": google_url,
            "format": "raw",
        }

        try:
            log.info(f"BrightData: '{query}' in {location}")
            resp = requests.post(self.API_URL, headers=headers, json=payload, timeout=90)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"BrightData error: {e}")
            return []

        # Response: {"jobs": {"items": [...]}} or {"jobs": [...]}
        jobs_data = data.get("jobs", {})
        if isinstance(jobs_data, dict):
            results = jobs_data.get("items", [])
        elif isinstance(jobs_data, list):
            results = jobs_data
        else:
            results = []

        jobs = []
        for item in results:
            if not isinstance(item, dict):
                continue

            description = item.get("description", "")

            # Tags are [{name: "Salary $", value: "80K"}, {name: "Posted", value: "3 days ago"}, ...]
            salary = ""
            posted_at = ""
            for tag in item.get("tags", []):
                name = tag.get("name", "").lower()
                value = tag.get("value", "")
                if "salary" in name:
                    salary = value
                elif "posted" in name:
                    posted_at = value

            # Pick the best apply link from postings — prefer ATS over aggregators
            google_url = item.get("link", "")
            postings = item.get("postings", [])
            apply_options = [{"link": p.get("link", ""), "title": p.get("title", "")}
                             for p in postings if isinstance(p, dict)]
            url = _pick_best_apply_url(apply_options, fallback=google_url)

            # If we're stuck with a Google/aggregator link and have no description,
            # try resolving the URL now so fetch_job_description has a real target later
            if _is_indirect_url(url) and not description:
                resolved = _resolve_apply_url(url)
                if resolved != url and not _is_indirect_url(resolved):
                    url = resolved

            job = JobListing(
                title=item.get("title", ""),
                company=item.get("company", ""),
                location=item.get("location", location),
                url=url,
                source="brightdata_google_jobs",
                description=description,
                salary=salary,
                date_posted=posted_at,
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict, max_workers: int = 6) -> list[JobListing]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        locations = config["search"]["locations"]
        query_groups = config["queries"]

        # Build list of (query, location) pairs
        tasks = []
        for group_name, queries in query_groups.items():
            for query in queries:
                for location in locations:
                    tasks.append((query, location))

        log.info(f"BrightData: {len(tasks)} queries with {max_workers} workers")
        all_jobs = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self.search, q, loc): (q, loc) for q, loc in tasks}
            for future in as_completed(futures):
                try:
                    all_jobs.extend(future.result())
                except Exception as e:
                    q, loc = futures[future]
                    log.error(f"BrightData worker error for '{q}' in {loc}: {e}")

        return all_jobs


# ---------------------------------------------------------------------------
# Source 2: Indeed RSS
# ---------------------------------------------------------------------------
class IndeedRSSScraper:
    """
    Indeed provides RSS feeds for search results.
    No API key needed. Limited to ~25 results per feed.

    Feed URL format:
    https://www.indeed.com/rss?q=QUERY&l=LOCATION&salary=SALARY
    """

    BASE_URL = "https://www.indeed.com/rss"

    def __init__(self, salary_min: int = 80000):
        self.salary_min = salary_min

    def search(self, query: str, location: str = "") -> list[JobListing]:
        params = {
            "q": query,
            "l": location,
            "sort": "date",
        }
        if self.salary_min:
            params["salary"] = str(self.salary_min)

        url = f"{self.BASE_URL}?{urlencode(params)}"

        try:
            log.info(f"Indeed RSS: '{query}' in {location or 'US'}")
            feed = feedparser.parse(url)
        except Exception as e:
            log.error(f"Indeed RSS error: {e}")
            return []

        jobs = []
        for entry in feed.entries:
            # Parse the Indeed RSS entry
            description = BeautifulSoup(
                entry.get("summary", ""), "html.parser"
            ).get_text(strip=True)

            # Extract company from title (Indeed format: "Title - Company")
            title = entry.get("title", "")
            company = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                company = parts[1].strip()

            location_text = entry.get("title", "")
            # Try to get location from the formatted address
            if hasattr(entry, "where"):
                location_text = entry.where

            job = JobListing(
                title=title,
                company=company,
                location=location_text,
                url=entry.get("link", ""),
                source="indeed_rss",
                description=description,
                date_posted=entry.get("published", ""),
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict) -> list[JobListing]:
        if not config.get("indeed", {}).get("enabled", True):
            return []

        all_jobs = []
        queries = config.get("indeed", {}).get("queries", [])
        locations = config["search"]["locations"]

        for query in queries:
            for location in locations:
                jobs = self.search(query, location)
                all_jobs.extend(jobs)
                time.sleep(0.5)

        return all_jobs


# ---------------------------------------------------------------------------
# Source 3: AVIXA Career Center
# ---------------------------------------------------------------------------
class AVIXAScraper:
    """
    Scrapes the AVIXA (Audiovisual and Integrated Experience Association)
    career center. Lower volume but high signal-to-noise for AV roles.
    """

    BASE_URL = "https://jobs.avixa.org/jobs/"

    def search(self, keyword: str) -> list[JobListing]:
        params = {"keywords": keyword, "page": 1}
        url = f"{self.BASE_URL}?{urlencode(params)}"

        try:
            log.info(f"AVIXA: '{keyword}'")
            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (compatible; JobSearchBot/1.0)"
            })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log.error(f"AVIXA scrape error: {e}")
            return []

        jobs = []
        # AVIXA uses a standard job board layout
        for card in soup.select(".job-result, .job-listing, [class*='job-item']"):
            title_el = card.select_one("a[href*='/job/'], h2 a, .job-title a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            if link and not link.startswith("http"):
                link = f"https://jobs.avixa.org{link}"

            company_el = card.select_one(".company, .employer, [class*='company']")
            company = company_el.get_text(strip=True) if company_el else ""

            location_el = card.select_one(".location, [class*='location']")
            location = location_el.get_text(strip=True) if location_el else ""

            job = JobListing(
                title=title,
                company=company,
                location=location,
                url=link,
                source="avixa",
                description="",  # Would need to fetch individual pages
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict) -> list[JobListing]:
        if not config.get("avixa", {}).get("enabled", True):
            return []

        all_jobs = []
        keywords = config.get("avixa", {}).get("keywords", ["audio", "AV engineer"])

        for keyword in keywords:
            jobs = self.search(keyword)
            all_jobs.extend(jobs)
            time.sleep(1)

        return all_jobs


# ---------------------------------------------------------------------------
# Source 4: Direct Career Page Scraper
# ---------------------------------------------------------------------------
class CareerPageScraper:
    """
    Fetches search result pages from target company career sites.
    This is inherently fragile — career page HTML changes frequently.
    Results may need manual verification.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    # Common career page patterns for extracting job listings
    JOB_SELECTORS = [
        # Workday (used by many large corps)
        "a[data-automation-id='jobTitle']",
        # Oracle/Taleo
        ".requisitionListItem a",
        # Greenhouse
        ".opening a",
        # Lever
        ".posting-title a",
        # Generic patterns
        "a[href*='/job/']",
        "a[href*='/jobs/']",
        "a[href*='/position/']",
        "a[href*='requisition']",
        ".job-title a",
        ".job-listing a",
        "[class*='job'] a[href]",
        "[class*='Job'] a[href]",
    ]

    def scrape_company(self, name: str, search_url: str, base_url: str, tier: str = "") -> list[JobListing]:
        try:
            log.info(f"Career page: {name}")
            resp = requests.get(search_url, headers=self.HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log.error(f"  Career page error ({name}): {e}")
            return []

        jobs = []
        seen_urls = set()

        for selector in self.JOB_SELECTORS:
            for el in soup.select(selector):
                title = el.get_text(strip=True)
                href = el.get("href", "")

                if not title or len(title) < 3:
                    continue

                # Build absolute URL
                if href and not href.startswith("http"):
                    if href.startswith("/"):
                        # Extract domain from search_url
                        from urllib.parse import urlparse
                        parsed = urlparse(search_url)
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"
                    else:
                        href = f"{base_url.rstrip('/')}/{href}"

                if href in seen_urls:
                    continue
                seen_urls.add(href)

                # Filter: only include if title looks AV/audio related
                title_lower = title.lower()
                av_keywords = [
                    "av ", "a/v", "audio", "video", "broadcast",
                    "production", "media", "multimedia", "studio",
                    "event tech", "conference", "audiovisual",
                    "unified comm", "collaboration",
                ]
                if not any(kw in title_lower for kw in av_keywords):
                    continue

                job = JobListing(
                    title=title,
                    company=name,
                    location="",  # Often not on listing page
                    url=href,
                    source="career_page",
                    tier=tier,
                )
                jobs.append(job)

        log.info(f"  → Found {len(jobs)} AV-relevant results")
        return jobs

    def run_all_pages(self, config: dict) -> list[JobListing]:
        all_jobs = []
        career_pages = config.get("career_pages", {})

        tier_map = {
            "tier1_prior_clients": "Tier 1 — Prior Client",
            "tier2_finance": "Tier 2 — Finance",
            "tier3_bigtech": "Tier 3 — Big Tech",
            "tier5_integrators": "Tier 5 — Integrator",
        }

        for tier_key, companies in career_pages.items():
            tier_label = tier_map.get(tier_key, tier_key)
            for company in companies:
                jobs = self.scrape_company(
                    name=company["name"],
                    search_url=company["search_url"],
                    base_url=company["url"],
                    tier=tier_label,
                )
                all_jobs.extend(jobs)
                time.sleep(1)  # Be polite

        return all_jobs


# ---------------------------------------------------------------------------
# Source 5: JobSpy (free direct scraping — Indeed, Glassdoor, Google, etc.)
# ---------------------------------------------------------------------------
class JobSpyScraper:
    """
    Uses the python-jobspy library to scrape job listings directly from
    Indeed, LinkedIn, Glassdoor, Google Jobs, and ZipRecruiter.
    No API key needed. Indeed has no rate limiting.
    """

    def search(self, query: str, location: str, config: dict) -> list[JobListing]:
        try:
            from jobspy import scrape_jobs # type: ignore
        except ImportError:
            log.error("Install python-jobspy: pip install -U python-jobspy")
            return []

        jobspy_cfg = config.get("jobspy", {})
        sites = jobspy_cfg.get("sites", ["indeed", "glassdoor", "google"])
        results_wanted = jobspy_cfg.get("results_per_query", 25)
        hours_old = jobspy_cfg.get("hours_old", 168)

        try:
            log.info(f"JobSpy: '{query}' in {location} ({', '.join(sites)})")
            df = scrape_jobs(
                site_name=sites,
                search_term=query,
                location=location,
                results_wanted=results_wanted,
                hours_old=hours_old,
                country_indeed="USA",
                description_format="markdown",
                verbose=0,
            )
        except Exception as e:
            log.error(f"JobSpy error: {e}")
            return []

        jobs = []
        for _, row in df.iterrows():
            # Build salary string from min/max amounts
            salary = ""
            if row.get("min_amount") and not (hasattr(row["min_amount"], '__class__') and str(row["min_amount"]) == "nan"):
                try:
                    min_amt = int(row["min_amount"])
                    max_amt = int(row.get("max_amount", 0) or 0)
                    interval = row.get("interval", "yearly")
                    if max_amt:
                        salary = f"${min_amt:,} - ${max_amt:,} ({interval})"
                    else:
                        salary = f"${min_amt:,} ({interval})"
                except (ValueError, TypeError):
                    pass

            # Build location string
            loc_parts = []
            if row.get("city") and str(row["city"]) != "nan":
                loc_parts.append(str(row["city"]))
            if row.get("state") and str(row["state"]) != "nan":
                loc_parts.append(str(row["state"]))
            job_location = ", ".join(loc_parts) if loc_parts else location

            site = str(row.get("site", "jobspy"))
            job = JobListing(
                title=str(row.get("title", "")),
                company=str(row.get("company", "")),
                location=job_location,
                url=str(row.get("job_url", "")),
                source=f"jobspy_{site}",
                description=str(row.get("description", "")) if str(row.get("description", "")) != "nan" else "",
                salary=salary,
                date_posted=str(row.get("date_posted", "")) if str(row.get("date_posted", "")) != "nan" else "",
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict) -> list[JobListing]:
        jobspy_cfg = config.get("jobspy", {})
        if not jobspy_cfg.get("enabled", False):
            return []

        all_jobs = []
        queries = jobspy_cfg.get("queries", ["audio engineer", "AV engineer"])
        locations = config["search"]["locations"]

        for query in queries:
            for location in locations:
                jobs = self.search(query, location, config)
                all_jobs.extend(jobs)
                time.sleep(2)  # Be polite between queries

        return all_jobs


# ---------------------------------------------------------------------------
# Job description fetcher
# ---------------------------------------------------------------------------
def fetch_job_description(url: str) -> str:
    """
    Fetch the full job description from a listing URL.
    Used to get details for LLM evaluation.
    """
    if not url:
        return ""

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
        desc_selectors = [
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
# Deduplication
# ---------------------------------------------------------------------------
def _normalize_company(name: str) -> str:
    """Normalize company name for fuzzy dedup."""
    name = name.lower().strip()
    # Strip common suffixes
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc",
                   ", ltd", " ltd", " corp.", " corp", " corporation",
                   " company", " co.", " co", " careers", " jobs"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _normalize_title_words(title: str) -> set[str]:
    """Extract meaningful words from a title for fuzzy comparison."""
    title = re.sub(r'[^\w\s]', ' ', title.lower())
    stopwords = {
        'a', 'an', 'the', 'and', 'or', 'of', 'for', 'in', 'at', 'to',
        'is', 'with', 'on', 'by', '-', '–', '—', '&', 'i', 'ii', 'iii',
        'sr', 'senior', 'jr', 'junior', 'lead', 'principal', 'staff',
        'associate', 'level', 'new', 'open',
    }
    # Normalize AV-industry synonyms before splitting
    synonyms = {
        'audiovisual': 'av', 'audio visual': 'av', 'a v': 'av',
        'technician': 'tech', 'specialist': 'spec',
        'information technology': 'it',
    }
    for old, new in synonyms.items():
        title = title.replace(old, new)
    return {w for w in title.split() if w and w not in stopwords and len(w) > 1}


def deduplicate_jobs(jobs: list[JobListing]) -> list[JobListing]:
    """Remove duplicate listings using exact hash, then fuzzy matching for aggregator echoes."""
    # Pass 1: exact job_id dedup
    seen = {}
    for job in jobs:
        if job.job_id not in seen:
            seen[job.job_id] = job
        else:
            existing = seen[job.job_id]
            if len(job.description) > len(existing.description):
                seen[job.job_id] = job
            elif len(job.description) == len(existing.description) and _is_indirect_url(existing.url) and not _is_indirect_url(job.url):
                seen[job.job_id] = job
            elif job.tier and not existing.tier:
                seen[job.job_id] = job

    exact_deduped = list(seen.values())
    exact_count = len(jobs) - len(exact_deduped)

    # Pass 2: fuzzy dedup — catch aggregator rewrites (same company + location + salary,
    # with overlapping title words). Keep the version with the longest description.
    fuzzy_groups = {}  # (norm_company, norm_location, salary) -> list of jobs
    for job in exact_deduped:
        norm_company = _normalize_company(job.company)
        norm_loc = JobListing._normalize_location(job.location).lower()
        # Use salary as an additional signal (aggregators preserve salary)
        salary_key = re.sub(r'[^\d]', '', job.salary)[:6] if job.salary else ""
        key = (norm_company, norm_loc, salary_key)
        fuzzy_groups.setdefault(key, []).append(job)

    final = []
    fuzzy_merged = 0
    for key, group in fuzzy_groups.items():
        if len(group) == 1 or not key[0]:  # single job or no company name
            final.extend(group)
            continue

        # Within each group, check title word overlap
        merged_indices = set()
        for i, job_a in enumerate(group):
            if i in merged_indices:
                continue
            words_a = _normalize_title_words(job_a.title)
            for j in range(i + 1, len(group)):
                if j in merged_indices:
                    continue
                words_b = _normalize_title_words(group[j].title)
                # If titles share 50%+ of meaningful words, likely same role
                if words_a and words_b:
                    overlap = len(words_a & words_b)
                    min_words = min(len(words_a), len(words_b))
                    if min_words > 0 and overlap / min_words > 0.5:
                        # Keep the one with more description, or better URL
                        merged_indices.add(j)
                        if len(group[j].description) > len(job_a.description):
                            group[i] = group[j]
                            job_a = group[i]
                            words_a = _normalize_title_words(job_a.title)
                        elif len(group[j].description) == len(job_a.description) and _is_indirect_url(job_a.url) and not _is_indirect_url(group[j].url):
                            group[i] = group[j]
                            job_a = group[i]
                            words_a = _normalize_title_words(job_a.title)
                        fuzzy_merged += 1

        for i, job in enumerate(group):
            if i not in merged_indices:
                final.append(job)

    log.info(
        f"Deduplicated: {len(jobs)} → {len(final)} unique listings "
        f"({exact_count} exact, {fuzzy_merged} fuzzy)"
    )
    return final


# ---------------------------------------------------------------------------
# LLM Evaluation (Claude)
# ---------------------------------------------------------------------------
class ResumeEvaluator:
    """
    Uses an LLM to score each job listing against the resume.
    Supports OpenRouter, Anthropic (direct), and any OpenAI-compatible endpoint.
    Returns a 0-100 match score and reasoning.
    """

    def __init__(self, config: dict, resume_text: str, role: str = "job_eval"):
        self.resume_text = resume_text
        self._role = role
        self.candidate_context = config.get("candidate_context", "")
        self.city_profiles = config.get("city_profiles", {})
        self.home_city = config.get("home_city", "Chicago, IL")
        self.current_income = int(config.get("current_income", 85000))
        home_profile = self.city_profiles.get(self.home_city, {})
        self.home_neighborhood = home_profile.get("neighborhood", self.home_city)
        self.client = None
        self.new_job_ids = set()  # job_ids evaluated fresh this run (not cached)
        self.cache_path = SCRIPT_DIR / "eval_cache.json"  # override per-user via evaluator.cache_path
        self._last_usage = None  # token usage from most recent _call_llm

        self.provider, self.model = resolve_model(config, role)

        if self.provider == "openrouter":
            api_key = config.get("openrouter_key", "")
            if not api_key:
                log.warning("OpenRouter key not set")
                return
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                )
            except ImportError:
                log.error("Install openai: pip install openai")

        elif self.provider == "anthropic":
            api_key = config.get("anthropic_key", "")
            if not api_key:
                log.warning("Anthropic key not set")
                return
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                log.error("Install anthropic: pip install anthropic")

        elif self.provider == "google_aistudio":
            api_key = config.get("google_aistudio_key", "")
            if not api_key:
                log.warning("Google AI Studio key not set")
                return
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except ImportError:
                log.error("Install google-genai: pip install google-genai")

        elif self.provider == "openai_compatible":
            base_url = config.get("openai_compatible_base_url", "http://localhost:1234/v1")
            api_key = config.get("openai_compatible_key", "not-needed")
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=base_url, api_key=api_key)
            except ImportError:
                log.error("Install openai: pip install openai")

        else:
            log.error(f"Unknown LLM provider: {self.provider}")

    def _call_llm(self, prompt: str, operation: str = None) -> str:
        """Send a prompt to the configured LLM and return the response text."""
        import time as _time
        from pipeline_utils import log_api_usage
        self._last_usage = None
        _start = _time.time()
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            self._last_usage = {
                "prompt_tokens": getattr(response.usage, "input_tokens", 0),
                "completion_tokens": getattr(response.usage, "output_tokens", 0),
            }
            _latency = int((_time.time() - _start) * 1000)
            _op = operation or self._role
            log_api_usage(
                source="pipeline", category="llm", operation=_op,
                provider=self.provider, model=self.model,
                prompt_tokens=self._last_usage["prompt_tokens"],
                completion_tokens=self._last_usage["completion_tokens"],
                total_tokens=self._last_usage["prompt_tokens"] + self._last_usage["completion_tokens"],
                latency_ms=_latency, success=True,
            )
            return response.content[0].text.strip()
        elif self.provider == "google_aistudio":
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "max_output_tokens": 4000,
                    "temperature": 0.5,
                },
            )
            um = getattr(response, "usage_metadata", None)
            if um:
                self._last_usage = {
                    "prompt_tokens": getattr(um, "prompt_token_count", 0),
                    "completion_tokens": getattr(um, "candidates_token_count", 0),
                }
            _latency = int((_time.time() - _start) * 1000)
            _op = operation or self._role
            _pt = (self._last_usage or {}).get("prompt_tokens", 0)
            _ct = (self._last_usage or {}).get("completion_tokens", 0)
            log_api_usage(
                source="pipeline", category="llm", operation=_op,
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                latency_ms=_latency, success=True,
            )
            return response.text.strip()
        else:
            # OpenRouter and OpenAI-compatible both use the OpenAI SDK
            extra_headers = {}
            if self.provider == "openrouter":
                extra_headers = {
                    "HTTP-Referer": "https://github.com/job-scraper",
                    "X-Title": "Job Search Pipeline",
                }
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
                extra_headers=extra_headers,
            )
            if response.usage:
                self._last_usage = {
                    "prompt_tokens": response.usage.prompt_tokens or 0,
                    "completion_tokens": response.usage.completion_tokens or 0,
                    "cost": getattr(response.usage, "cost", None),  # OpenRouter actual cost
                }
            _latency = int((_time.time() - _start) * 1000)
            _op = operation or self._role
            _pt = (self._last_usage or {}).get("prompt_tokens", 0)
            _ct = (self._last_usage or {}).get("completion_tokens", 0)
            _cost = (self._last_usage or {}).get("cost")
            log_api_usage(
                source="pipeline", category="llm", operation=_op,
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                cost_usd=_cost, latency_ms=_latency, success=True,
            )
            return response.choices[0].message.content.strip()

    def _city_profiles_str(self) -> str:
        """Format city relocation profiles for injection into the prompt."""
        if not self.city_profiles:
            return ""
        baseline = self.city_profiles.get(self.home_city, {})
        baseline_rent = baseline.get("rent_1br", 0)
        baseline_tax = baseline.get("tax_rate", 0)
        baseline_cost = baseline.get("monthly_cost", 0)

        lines = [
            f"RELOCATION REFERENCE DATA (candidate baseline: {self.home_neighborhood} — "
            f"${baseline_rent:,}/mo rent, {baseline_tax:.1%} tax, ${baseline_cost:,}/mo total):\n"
        ]
        for city, profile in self.city_profiles.items():
            if city == self.home_city:
                continue
            premium = profile.get("annual_premium", 0)
            premium_str = f"+${premium:,}/yr" if premium > 0 else f"-${abs(premium):,}/yr (cheaper)"
            lines.append(
                f"  {city} ({profile.get('neighborhood', '?')}):\n"
                f"    Rent: ${profile.get('rent_1br', '?'):,}/mo | Tax: {profile.get('tax_rate', 0):.1%} "
                f"| Total: ${profile.get('monthly_cost', '?'):,}/mo ({premium_str} vs {self.home_city})\n"
                f"    Commute: {profile.get('commute', '?')}\n"
                f"    Walk: {profile.get('walk_score', '?')} | Bike: {profile.get('bike_score', '?')} "
                f"| Car required: {'Yes' if profile.get('car_required') else 'No'}\n"
                f"    Waterfront: {profile.get('waterfront', '?')}\n"
                f"    Notes: {profile.get('lifestyle_notes', '')}"
            )
        return "\n".join(lines)

    def _relocation_prompt_block(self, *, deep: bool = False) -> str:
        """
        Return the compensation & relocation analysis block for the prompt.
        Returns an empty string if home_city, current_income, or city_profiles
        are not set — so the section is silently omitted rather than broken.
        """
        if not self.home_city or not self.current_income or not self.city_profiles:
            return ""
        city_data = self._city_profiles_str()
        if not city_data:
            return ""
        income_k = self.current_income // 1000
        if deep:
            return (
                f"#### COMPENSATION & RELOCATION ANALYSIS\n"
                f"The candidate currently earns ~${income_k}K/year based in {self.home_neighborhood}. "
                f"Use the relocation reference data below to perform a full financial and lifestyle "
                f"comparison for any role outside {self.home_city}. Show your math.\n"
                f"{city_data}"
            )
        return (
            f"- COMPENSATION & RELOCATION ANALYSIS: The candidate currently earns ~${income_k}K/year "
            f"based in {self.home_neighborhood}. Use the relocation reference data below to perform a "
            f"full financial and lifestyle comparison for any role outside {self.home_city}. "
            f"For each non-{self.home_city} role:\n"
            f"  1. Estimate or use the listed salary\n"
            f"  2. Calculate the annual relocation premium from the reference data (rent + tax difference)\n"
            f"  3. Add car ownership costs ($6,000-9,600/yr) if car_required=Yes for that city\n"
            f"  4. Calculate **net annual gain** = (new salary - ${income_k}K) - annual_premium - car_costs\n"
            f"  5. If net annual gain is negative or negligible (<$5K), downgrade the match by one level\n"
            f"  6. Factor in lifestyle: Walk Score, Bike Score, waterfront access, commute. "
            f"If a move represents a significant QOL downgrade from {self.home_neighborhood}, note it clearly\n"
            f"  7. A permanent role also offers benefits (health insurance, 401k match, PTO) "
            f"worth ~$15-25K/yr — factor this into the comparison vs. current income\n"
            f"  Always show your math in the RED FLAGS and LOGISTICS sections.\n"
            f"{city_data}\n"
            f"- LOCATION MATTERS: Use the candidate's context above to determine their relocation "
            f"preferences. Suburban or car-dependent locations should be flagged as a negative if "
            f"the candidate prefers walkable urban areas."
        )

    def evaluate(self, job: JobListing) -> dict:
        """
        Score a job against the resume using the full structured evaluation.
        Returns dict with score, verdict, reasoning (short), and full_evaluation.
        """
        if not self.client or not self.resume_text:
            return {
                "score": 0, "verdict": "", "reasoning": "Evaluation skipped",
                "full_evaluation": "",
            }

        description_missing = not job.description or len(job.description.strip()) < 50

        if description_missing:
            desc_text = (
                "(No description available. You MUST NOT fabricate or assume job requirements. "
                "Evaluate ONLY what can be confirmed from the title and company name. "
                "Cap your verdict at MODERATE maximum — without a description, a STRONG rating is not justified.)"
            )
        else:
            desc_text = job.description

        job_info = f"""Title: {job.title}
Company: {job.company}
Location: {job.location}
Source: {job.source}
Salary: {job.salary or 'Not listed'}
Company Tier: {job.tier or 'N/A'}

Description:
{desc_text}"""

        prompt = f"""You are a senior technical recruiter specializing in live events, AV production, broadcast audio, and corporate AV — with deep knowledge of both the freelance production world and the permanent in-house corporate AV world. Your job is to evaluate a job posting against the candidate's resume.

CANDIDATE RESUME:
{self.resume_text}

ADDITIONAL CONTEXT ABOUT THE CANDIDATE:
{self.candidate_context}

JOB POSTING:
{job_info}

---

Perform the following evaluation:

### 1. ROLE SUMMARY
- Company name, actual role (translate past any disguised titles — e.g., "Technology Delivery, VP" = Lead Audio Engineer), location, and compensation if listed
- Is this an in-house permanent role, a contract, or a staffed/embedded integrator position?
- On-site requirements (hybrid, fully on-site, remote) and any relocation implications
- Industry vertical (financial services, pharma, tech, education, entertainment, etc.)

### 2. MATCH SCORE
Score each dimension 1–5 honestly. 3 = adequate, NOT a safe default. Show scores in a table:

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Core Skills | _/5 | 5=meets nearly all required skills, 3=meets ~half, 1=almost no overlap. Weight REQUIRED qualifications heavily; "preferred" / "nice to have" / "strong candidates may also have" sections are bonuses, not gaps. Different AV sub-disciplines (e.g. integration/service vs live production, or post-production vs live events) count as partial gaps even if both are "AV" — score 2 unless there is genuine day-to-day skill overlap |
| Seniority Fit | _/5 | 5=perfect level, 3=slightly off, 1=wildly mismatched (too junior or senior) |
| Compensation | _/5 | 5=clear upgrade, 3=lateral, 1=major pay cut. If unlisted, default to 3 |
| Logistics | _/5 | 5=ideal location/setup, 3=workable with trade-offs, 1=dealbreaker |
| Career Value | _/5 | 5=clearly advances goals, 3=neutral, 1=step backward or dead end |

**WEIGHTED COMPOSITE** = (2×Core Skills + Seniority + Compensation + Logistics + Career Value) / 6
↑ Core Skills counts DOUBLE — a job you can't do is a bad match regardless of pay.
Calculate explicitly, e.g. "(2×4 + 3 + 2 + 4 + 3)/6 = 2.67"

Use the FULL 1–5 range. 5 means excellent (not perfect). 1 means dealbreaker or clearly wrong. Don't compress everything into 2–4.

Map weighted composite to verdict:
- **3.8–5.0** → 🟢 STRONG — Apply with confidence. Core skills align and circumstances work.
- **2.6–3.7** → 🟡 MODERATE — Worth applying, but meaningful concerns to address.
- **1.6–2.5** → 🟠 STRETCH — Major gaps or practical barriers. Only if strategically motivated.
- **1.0–1.5** → 🔴 WEAK — Wrong role, wrong level, or impractical. Skip it.

**Override rules** (apply AFTER computing composite — these are hard caps):
- If Core Skills ≤ 2 → verdict CANNOT exceed STRETCH, regardless of composite. A job in the wrong discipline is not a good match no matter how well it pays.
- If Seniority Fit = 1 → verdict CANNOT exceed STRETCH. A wildly mismatched level (entry-level for a 15-year veteran, or VP for a mid-career professional) is not worth pursuing.

**Calibration anchors** — use these to gut-check your scoring:
- Corporate AV role, Crestron/Extron/Dante, good pay, candidate's own city → (2×5+4+4+5+4)/6 = **4.5 STRONG**
- Same role but requires relocation for a pay upgrade → (2×5+4+4+3+4)/6 = **4.2 STRONG**
- Same role but lateral pay AND costly relocation → (2×5+4+2+2+4)/6 = **3.7 MODERATE**
- Broadcast post-production (Pro Tools HDX, Dolby Atmos) for a live-events person → (2×2+3+4+3+2)/6 = **2.7 MODERATE** but Core Skills ≤ 2 cap → **STRETCH**
- AV integrator service/support engineer (Crestron/AMX ticketing, remote troubleshooting) for a live-production A1 → (2×2+3+3+3+2)/6 = **2.5 STRETCH** — integration support ≠ live production; Core Skills ≤ 2 cap also applies
- Part-time venue audio gig, right skills but $20/hr and too junior → (2×4+1+1+4+1)/6 = **2.5 STRETCH** (Seniority=1 cap also applies)
- Entry-level "AV Tech I" at $45K when candidate has 15+ yrs → (2×3+1+1+3+1)/6 = **2.0 STRETCH** + Seniority=1 cap
- IT helpdesk / desktop support role with no AV → (2×1+2+3+3+1)/6 = **1.8 STRETCH** + Core Skills ≤ 2 cap
- Warehouse associate or food service → (2×1+1+1+3+1)/6 = **1.3 WEAK**

### 3. REQUIREMENTS ALREADY MET
List each requirement from the posting alongside the specific line, bullet, or section of the resume that demonstrates it. Be precise — cite actual resume content.

### 4. REQUIREMENTS WITH EXPERIENCE BUT NOT HIGHLIGHTED
Things the candidate can likely do based on the full picture of the resume and context but that aren't explicitly stated or are buried. For each, suggest where and how to surface it in a tailored version.

### 5. TRUE GAPS
Requirements where the candidate genuinely lacks the qualification or experience. Be honest — don't stretch. For each gap, note:
- How critical it appears to be (dealbreaker vs. nice-to-have vs. learnable)
- Whether it's something that could realistically be developed quickly or addressed in a cover letter

### 6. RED FLAGS
- Anything that seems off about the posting (vague requirements, unrealistic expectations, title/comp mismatch)
- Any requirements that suggest a different seniority level (too junior or too senior)
- ATS keywords from the posting that are missing from the resume

### 7. LOGISTICS
- Location/relocation requirements and whether they're feasible given {self.home_city} base
- Salary range (if listed) and whether it aligns with experience level
- On-site / hybrid / remote details and commute implications

### 8. VERDICT
Answer three questions directly:
1. **Should I apply?** Yes / Yes but temper expectations / Only if genuinely interested in this company / No
2. **Is it worth tailoring my resume?** Yes — significant tailoring needed / Light tailoring only / No — baseline resume is sufficient
3. **What's the single most important thing to change or add if tailoring?** One specific, actionable recommendation.

---

RULES:
- Be direct and honest. Say "this is a weak match, don't waste your time" if that's the case.
- Don't inflate qualifications. If the resume doesn't demonstrate something, say so.
- Pay attention to disguised titles. Corporate AV roles are frequently hidden behind titles like "Technology Delivery," "Multimedia Specialist," "Event Technology Manager," "Collaboration Engineer," etc. Translate these.
- When a posting lists "required" vs. "preferred" qualifications, weigh them differently.
- If the posting is vague or poorly written, say so.
- VERDICT CALIBRATION: Do NOT default to MODERATE. Trust your dimensional scores and apply the override rules. If the composite is below 2.6 (or override rules apply), commit to STRETCH or WEAK. If it's 3.8+ with no overrides, commit to STRONG. A typical job search yields a MIX of all four verdicts.
{self._relocation_prompt_block()}

After the full evaluation, add final lines in exactly this format:
JOB_SUMMARY: [2-sentence plain-text summary of the role itself. Do NOT mention the candidate.]
COMPOSITE_SCORE: [your calculated average, e.g., 3.4]
MATCH_LEVEL: [STRONG|MODERATE|STRETCH|WEAK]

CRITICAL: The MATCH_LEVEL must follow directly from your COMPOSITE_SCORE using the thresholds above,
AFTER applying the override rules (Core Skills ≤ 2 → STRETCH max; Seniority Fit = 1 → STRETCH max).
Do not override your dimensional scoring with a gut feeling. Trust the math — that's the whole point
of scoring dimensions first. If overrides apply, state which one and adjust the verdict accordingly."""

        try:
            text = self._call_llm(prompt)

            # --- Parse dimension scores from the table and recompute composite ---
            # LLMs frequently make arithmetic errors; we recompute to be safe.
            dim_names = ["Core Skills", "Seniority Fit", "Compensation", "Logistics", "Career Value"]
            dim_scores = {}
            for dim in dim_names:
                # Match patterns like "| Core Skills | 4/5 |" or "| **Core Skills** | **4**/5 |"
                pat = re.compile(
                    rf"\|\s*\**{re.escape(dim)}\**\s*\|\s*\**(\d)\**\s*(?:/5)?\s*\|",
                    re.IGNORECASE,
                )
                m = pat.search(text)
                if m:
                    dim_scores[dim] = int(m.group(1))

            # Recompute weighted composite if we got all 5 dimensions
            recalc_composite = None
            if len(dim_scores) == 5:
                cs = dim_scores["Core Skills"]
                sf = dim_scores["Seniority Fit"]
                co = dim_scores["Compensation"]
                lo = dim_scores["Logistics"]
                cv = dim_scores["Career Value"]
                recalc_composite = round((2 * cs + sf + co + lo + cv) / 6, 2)

            # Extract COMPOSITE_SCORE from trailing tag (model's own calculation)
            comp_match = re.search(r"COMPOSITE_SCORE:\s*\**\s*([\d.]+)", text)
            model_composite = float(comp_match.group(1)) if comp_match else None

            # Use recalculated composite (authoritative); fall back to model's
            composite = recalc_composite if recalc_composite is not None else model_composite

            # --- Determine verdict from composite + override rules ---
            verdict = ""
            score = 0

            if composite is not None:
                # Apply threshold mapping
                if composite >= 3.8:
                    verdict = "STRONG"
                elif composite >= 2.6:
                    verdict = "MODERATE"
                elif composite >= 1.6:
                    verdict = "STRETCH"
                else:
                    verdict = "WEAK"

                # Apply override rules (hard caps from the prompt)
                if dim_scores:
                    if dim_scores.get("Core Skills", 5) <= 2 and verdict in ("STRONG", "MODERATE"):
                        verdict = "STRETCH"
                    if dim_scores.get("Seniority Fit", 5) == 1 and verdict in ("STRONG", "MODERATE"):
                        verdict = "STRETCH"

            else:
                # Fallback: extract MATCH_LEVEL tag from text
                level_match = re.search(
                    r"MATCH_LEVEL:\s*\**(?:🟢|🟡|🟠|🔴)?\s*\**\s*(STRONG|MODERATE|STRETCH|WEAK)",
                    text,
                )
                if not level_match:
                    level_match = re.search(
                        r"\*{0,2}MATCH_LEVEL\*{0,2}:\s*\**\s*(STRONG|MODERATE|STRETCH|WEAK)",
                        text,
                    )
                if level_match:
                    verdict = level_match.group(1)
                else:
                    # Last resort: detect from emoji
                    if "🟢" in text:
                        verdict = "STRONG"
                    elif "🟡" in text:
                        verdict = "MODERATE"
                    elif "🟠" in text:
                        verdict = "STRETCH"
                    elif "🔴" in text:
                        verdict = "WEAK"

            # Cap verdict when description was missing — LLM can't justify STRONG
            if description_missing and verdict == "STRONG":
                log.warning(f"Capping {job.title} @ {job.company} from STRONG → MODERATE (no description)")
                verdict = "MODERATE"

            # Compute score: prefer composite for granularity, fall back to fixed mapping
            if composite is not None:
                score = max(1, min(100, int(composite * 20)))  # 1-5 → 20-100
            else:
                score = {"STRONG": 85, "MODERATE": 70, "STRETCH": 50, "WEAK": 25}.get(verdict, 0)

            # Adjust score down if verdict was capped due to missing description
            if description_missing and score > 70:
                score = 70

            # Extract JOB_SUMMARY from trailing tags
            job_summary = ""
            summary_match = re.search(
                r"JOB_SUMMARY:\s*(.+?)(?:\n(?:COMPOSITE_SCORE|MATCH_LEVEL))", text, re.DOTALL,
            )
            if summary_match:
                job_summary = summary_match.group(1).strip()

            # Extract a short reasoning from the verdict section
            reasoning = ""
            verdict_section = re.search(
                r"###?\s*8\.?\s*VERDICT(.*?)(?:JOB_SUMMARY|COMPOSITE_SCORE|MATCH_LEVEL|$)",
                text, re.DOTALL | re.IGNORECASE,
            )
            if verdict_section:
                reasoning = verdict_section.group(1).strip()[:500]

            # Clean the trailing JOB_SUMMARY, COMPOSITE_SCORE, and MATCH_LEVEL lines
            full_eval = re.sub(r"\n?JOB_SUMMARY:.*$", "", text, flags=re.DOTALL).strip()
            full_eval = re.sub(r"\n?COMPOSITE_SCORE:.*$", "", full_eval).strip()
            full_eval = re.sub(r"\n?MATCH_LEVEL:.*$", "", full_eval).strip()

            return {
                "score": score,
                "verdict": verdict,
                "reasoning": reasoning,
                "full_evaluation": full_eval,
                "job_summary": job_summary,
            }

        except Exception as e:
            log.error(f"LLM evaluation error: {e}")
            return {
                "score": 0, "verdict": "", "reasoning": f"Evaluation failed: {e}",
                "full_evaluation": "", "job_summary": "",
            }

    def deep_evaluate(self, job: JobListing, config: dict, first_pass_eval: str = "") -> str:
        """
        Generate application prep package for a STRONG match job.
        Uses the first-pass evaluation as context (no redundant re-scoring)
        and produces 3 sections: Resume Tailoring, Cover Letter, Interview Prep.
        Returns a detailed markdown string.
        """
        # Skip deep eval when description is missing — can't generate useful prep
        if not job.description or len(job.description.strip()) < 50:
            log.warning(f"Skipping deep eval for {job.title} @ {job.company} — no description available")
            return ""

        deep_evaluator = ResumeEvaluator(config=config, resume_text=self.resume_text, role="deep_eval")
        if not deep_evaluator.client:
            log.error("Failed to initialize deep evaluation model")
            return ""

        job_info = f"""Title: {job.title}
Company: {job.company}
Location: {job.location}
Source: {job.source}
Salary: {job.salary or 'Not listed'}
Company Tier: {job.tier or 'N/A'}

Description:
{job.description or '(No description available — evaluate based on title/company only)'}"""

        # Build first-pass context block
        first_pass_block = ""
        if first_pass_eval:
            first_pass_block = f"""
FIRST-PASS EVALUATION (already completed — use this as context, do NOT repeat it):
{first_pass_eval}

---
"""

        prompt = f"""You are a senior technical recruiter with 15+ years of experience placing AV, broadcast, and live event engineers into permanent corporate roles. You've worked at firms like PRG, PSAV (now Encore), and Clair Global, and have deep relationships with hiring managers at major financial services firms and Fortune 500 pharma companies. You know exactly what makes a candidate stand out — and what gets a resume thrown in the "no" pile.

This job has already been evaluated as a STRONG match. A first-pass evaluation with match analysis, requirements mapping, gaps, and logistics is provided below. Your job is to produce the APPLICATION PREP PACKAGE — the actionable deliverables the candidate needs to actually apply and interview.

CANDIDATE RESUME:
{self.resume_text}

ADDITIONAL CONTEXT ABOUT THE CANDIDATE:
{self.candidate_context}

JOB POSTING:
{job_info}
{first_pass_block}
Produce the following 3-section application prep package. Be thorough, specific, and actionable. Write as if you're personally coaching this candidate before they apply.

### 1. RESUME TAILORING
This is where you earn your fee. For each suggestion:
- Quote the EXISTING bullet point or section from the resume (use "**BEFORE:**" formatting)
- Write the REWRITTEN version (use "**AFTER:**" formatting)
- Explain WHY the change matters for this specific posting
- If a bullet point should be ADDED (not rewritten), mark it as "**ADD:**" with the suggested placement

Focus on:
- ATS keyword optimization (pull exact phrases from the posting)
- Reframing freelance experience to emphasize the skills this employer cares about
- Quantifying impact where possible
- Moving the most relevant experience to prominent positions

Provide at least 5-7 specific before/after rewrites. More is better — the candidate should be able to make all changes in 30 minutes.

### 2. COVER LETTER TALKING POINTS
Write 3-5 key talking points for the cover letter, framed in terms of "what would make me pick up the phone and call this candidate." For each point:
- The core message (one sentence)
- Why it matters to THIS employer specifically
- A suggested opening line or phrase the candidate could use

Think like a recruiter scanning 200 applications — what makes this one jump off the page?

### 3. INTERVIEW PREP
Based on this posting, prepare the candidate for the interview:
- **Likely technical questions** (5-7 specific questions they'll probably ask, based on the role requirements)
- **Behavioral/situational questions** (3-5 questions about experience, especially around any gaps or transitions)
- **Questions about the freelance-to-permanent transition** — how to frame this positively
- **Stories to prepare** — specific projects or experiences from the resume that map to this role's key requirements. Name the project/client and the talking point.
- **Questions to ASK the interviewer** — 3-5 smart questions that show domain knowledge and genuine interest

---

RULES:
- Begin your response directly with ### 1. RESUME TAILORING — no preamble, no intro paragraph, no framing text.
- Be direct and brutally honest. This candidate can handle it.
- Don't inflate qualifications. If something is a gap, say so — then help them address it.
- Write as if you're personally preparing this candidate for a specific interview, not generating generic advice.
- Every suggestion should reference specific content from either the resume or the job posting.
- The resume tailoring section is the most important — make it specific enough that the candidate can make changes in 30 minutes.
- Use the first-pass evaluation as a foundation — don't contradict its analysis, but ADD actionable detail on top of it."""

        try:
            # Use higher token limit for deep evaluation
            if deep_evaluator.provider == "anthropic":
                response = deep_evaluator.client.messages.create(
                    model=deep_evaluator.model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()
            elif deep_evaluator.provider == "google_aistudio":
                response = deep_evaluator.client.models.generate_content(
                    model=deep_evaluator.model,
                    contents=prompt,
                    config={
                        "max_output_tokens": 8000,
                        "temperature": 0.5,
                    },
                )
                return response.text.strip()
            else:
                extra_headers = {}
                if deep_evaluator.provider == "openrouter":
                    extra_headers = {
                        "HTTP-Referer": "https://github.com/job-scraper",
                        "X-Title": "Job Search Pipeline",
                    }
                response = deep_evaluator.client.chat.completions.create(
                    model=deep_evaluator.model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                    extra_headers=extra_headers,
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"Deep evaluation error for {job.title} @ {job.company}: {e}")
            return ""

    def _evaluate_single(self, job: JobListing, fetch_description: bool) -> dict:
        """Evaluate a single job (thread-safe). Returns (job, result) tuple."""
        # Resolve indirect URLs (Google search links, aggregators) to final destination
        if job.url and _is_indirect_url(job.url):
            job.url = _resolve_apply_url(job.url)
        # Only fetch description from web if not already stored (e.g. from Supabase)
        if fetch_description and not job.description and job.url:
            job.description = fetch_job_description(job.url)
        if not job.description or len(job.description.strip()) < 50:
            log.warning(f"No description available for {job.title} @ {job.company} — evaluation will be capped")
        return self.evaluate(job)

    def _load_eval_cache(self) -> dict:
        """Load eval cache - a persistent map of job_id -> evaluation results."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                log.warning(f"Failed to load eval cache: {e}")
        return {}

    def _save_eval_cache(self, cache: dict):
        """Persist the eval cache to disk."""
        with open(self.cache_path, "w") as f:
            json.dump(cache, f, separators=(",", ":"))
        log.info(f"Eval cache saved ({self.cache_path.name}): {len(cache)} entries")

    def evaluate_batch(
        self, jobs: list[JobListing], fetch_descriptions: bool = True,
        max_workers: int = 8, progress_callback=None, on_job_complete=None,
    ) -> list[JobListing]:
        """Evaluate a batch of jobs concurrently, skipping previously evaluated ones."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Load cache of previous evaluations
        eval_cache = self._load_eval_cache()
        cached_jobs = []
        new_jobs = []
        for job in jobs:
            if job.job_id in eval_cache:
                cached = eval_cache[job.job_id]
                job.match_score = cached["score"]
                job.match_verdict = cached["verdict"]
                job.match_reasoning = cached["reasoning"]
                job.full_evaluation = cached["full_evaluation"]
                job.job_summary = cached.get("job_summary", "")
                cached_jobs.append(job)
            else:
                new_jobs.append(job)

        total_new = len(new_jobs)
        total_cached = len(cached_jobs)
        console.print(f"\n[bold]Evaluating {total_new} new jobs against resume...[/bold]")
        if total_cached:
            console.print(f"[dim]Skipping {total_cached} previously evaluated jobs (cached)[/dim]")
        console.print(f"[dim]Provider: {self.provider} | Model: {self.model} | Workers: {max_workers}[/dim]")

        verdict_style_map = {
            "STRONG": "green bold",
            "MODERATE": "yellow",
            "STRETCH": "rgb(255,165,0)",
            "WEAK": "dim",
        }

        completed = 0
        if new_jobs:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_job = {
                    executor.submit(self._evaluate_single, job, fetch_descriptions): (i, job)
                    for i, job in enumerate(new_jobs)
                }

                for future in as_completed(future_to_job):
                    i, job = future_to_job[future]
                    completed += 1
                    try:
                        result = future.result()
                        job.match_score = result["score"]
                        job.match_verdict = result["verdict"]
                        job.match_reasoning = result["reasoning"]
                        job.full_evaluation = result["full_evaluation"]
                        job.job_summary = result.get("job_summary", "")
                    except Exception as e:
                        log.error(f"Evaluation failed for {job.title}: {e}")
                        job.match_score = 0
                        job.match_verdict = ""
                        job.match_reasoning = f"Evaluation failed: {e}"
                        job.full_evaluation = ""

                    verdict_style = verdict_style_map.get(job.match_verdict, "white")
                    console.print(
                        f"  [{completed}/{total_new}] {job.title} @ {job.company}... "
                        f"[{verdict_style}]{job.match_verdict} ({job.match_score})[/{verdict_style}]"
                    )
                    if on_job_complete and job.match_verdict:
                        on_job_complete(job)
                    if progress_callback and completed % 5 == 0:
                        progress_callback(completed)

        # Track new job IDs and save into the cache
        self.new_job_ids = {job.job_id for job in new_jobs if job.match_verdict}
        for job in new_jobs:
            if job.match_verdict:
                eval_cache[job.job_id] = {
                    "score": job.match_score,
                    "verdict": job.match_verdict,
                    "reasoning": job.match_reasoning[:300],
                    "full_evaluation": job.full_evaluation,
                    "job_summary": job.job_summary,
                }
        self._save_eval_cache(eval_cache)

        return cached_jobs + new_jobs


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
                        f.write(f"# {job.title} — {job.company}\n\n")
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
        f"# Job Search Results — {timestamp}",
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

    # Strong matches — full evaluations
    if strong:
        lines.append(f"## 🟢 STRONG MATCHES ({len(strong)})\n")
        for job in strong:
            lines.append(f"### {job.title} — {job.company}")
            lines.append(f"📍 {job.location} | 🔗 [Apply]({job.url})")
            if job.tier:
                lines.append(f"*{job.tier}*")
            if job.salary:
                lines.append(f"💰 {job.salary}")
            lines.append("")
            if job.full_evaluation:
                lines.append("<details><summary>Full Evaluation</summary>\n")
                lines.append(job.full_evaluation)
                lines.append("\n</details>")
            lines.append("---")

    # Moderate matches — full evaluations
    if moderate:
        lines.append(f"\n## 🟡 MODERATE MATCHES ({len(moderate)})\n")
        for job in moderate:
            lines.append(f"### {job.title} — {job.company}")
            lines.append(f"📍 {job.location} | 🔗 [Apply]({job.url})")
            if job.tier:
                lines.append(f"*{job.tier}*")
            if job.salary:
                lines.append(f"💰 {job.salary}")
            lines.append("")
            if job.full_evaluation:
                lines.append("<details><summary>Full Evaluation</summary>\n")
                lines.append(job.full_evaluation)
                lines.append("\n</details>")
            lines.append("---")

    # Stretch — condensed
    if stretch:
        lines.append(f"\n## 🟠 STRETCH ({len(stretch)})\n")
        for job in stretch:
            lines.append(f"- **{job.title}** at {job.company} ({job.location})")
            lines.append(f"  🔗 [Link]({job.url})")
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

    # Weak — just titles
    if weak:
        lines.append(f"\n## 🔴 WEAK MATCHES ({len(weak)})\n")
        for job in weak:
            lines.append(
                f"- {job.title} at {job.company} ({job.location}) — "
                f"[Link]({job.url})"
            )

    # Unscored
    if unscored:
        lines.append(f"\n## ⬜ NOT EVALUATED ({len(unscored)})\n")
        for job in unscored[:20]:
            lines.append(f"- {job.title} at {job.company} — {job.source}")

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
        verdict_display = job.match_verdict or "—"
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
    stretch = sum(1 for j in jobs if j.match_verdict == "STRETCH")
    weak = sum(1 for j in jobs if j.match_verdict == "WEAK")
    console.print(f"\n  🟢 Strong matches:   {top}")
    console.print(f"  🟡 Moderate matches: {good}")
    console.print(f"  🟠 Stretch:          {stretch}")
    console.print(f"  🔴 Weak:             {weak}")


# ---------------------------------------------------------------------------
# Supabase sync (optional — only runs when SUPABASE_URL is set)
# ---------------------------------------------------------------------------
def _supabase_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


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
            log.info("Supabase: no primary resume set — using local file")
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
        log.info(f"Supabase: downloaded active resume '{file_name}' → {local_path}")
        return local_path

    except Exception as e:
        log.warning(f"Supabase: could not download resume ({e}) — using local file")
        return None


def sync_to_supabase(config: dict, jobs: list[JobListing], new_job_ids: set, metadata: dict):
    """
    Upsert this run's evaluated jobs into Supabase via REST API.
    No-op if SUPABASE_URL is not set.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        log.info("Supabase: not configured — skipping sync")
        return

    headers = _supabase_headers(supabase_key)
    date_str = metadata["date"]
    verdict_counts = metadata.get("verdicts", {})

    try:
        # 1. Upsert run record
        run_payload = {
            "run_date": date_str,
            "total_jobs": metadata["total_jobs"],
            "evaluated": metadata["evaluated"],
            "strong_count": verdict_counts.get("STRONG", 0),
            "moderate_count": verdict_counts.get("MODERATE", 0),
            "stretch_count": verdict_counts.get("STRETCH", 0),
            "weak_count": verdict_counts.get("WEAK", 0),
            "new_job_ids": sorted(new_job_ids),
            "sources": sorted(set(j.source for j in jobs)),
        }
        run_resp = requests.post(
            f"{supabase_url}/rest/v1/runs?on_conflict=user_id,run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=run_payload, timeout=30,
        )
        run_resp.raise_for_status()
        run_id = run_resp.json()[0]["id"]
        log.info(f"Supabase: upserted run {date_str} → {run_id}")

        # 2. Upsert evaluated jobs in batches
        evaluated = [j for j in jobs if j.match_verdict]
        BATCH = 100
        for i in range(0, len(evaluated), BATCH):
            batch = evaluated[i:i + BATCH]
            records = []
            for j in batch:
                rec = {
                    "job_id": j.job_id,
                    "title": j.title,
                    "company": j.company,
                    "location": j.location or "Unknown",
                    "url": j.url or "",
                    "source": j.source,
                    "salary": j.salary or None,
                    "date_posted": j.date_posted or None,
                    "tier": j.tier or None,
                    "match_score": j.match_score,
                    "match_verdict": j.match_verdict,
                    "match_reasoning": (j.match_reasoning or "")[:500] or None,
                    "job_summary": j.job_summary or None,
                    "full_evaluation": j.full_evaluation or None,
                    "first_seen_run": run_id,
                    "last_seen_run": run_id,
                    "first_seen_date": date_str,
                    "last_seen_date": date_str,
                    "date_scraped": j.date_scraped,
                }
                if j.description:
                    rec["description"] = j.description[:50000]
                    rec["description_length"] = len(j.description)
                records.append(rec)
            resp = requests.post(
                f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=records, timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Supabase: upserted {len(evaluated)} jobs")

        # 3. Insert run_jobs junction rows
        rj_records = [{
            "run_id": run_id,
            "job_id_ref": j.job_id,
            "is_new_this_run": j.job_id in new_job_ids,
        } for j in evaluated]
        for i in range(0, len(rj_records), BATCH):
            resp = requests.post(
                f"{supabase_url}/rest/v1/run_jobs?on_conflict=run_id,job_id_ref",
                headers={**headers, "Prefer": "resolution=ignore-duplicates"},
                json=rj_records[i:i + BATCH], timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Supabase: sync complete (run {run_id})")

    except Exception as e:
        log.error(f"Supabase sync failed: {e}")
        # Non-fatal — file-based results are already saved


def sync_deep_evals(config: dict, jobs: list[JobListing]):
    """Update deep_evaluation field for STRONG jobs after deep eval pass."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)
    strong_with_deep = [j for j in jobs if j.match_verdict == "STRONG" and j.full_evaluation]

    # Read deep eval files written to disk and patch the DB
    date_str = datetime.now().strftime("%Y-%m-%d")
    deep_dir = RESULTS_DIR / date_str / "strong" / "deep"
    if not deep_dir.exists():
        return

    updated = 0
    for md_path in deep_dir.glob("*.md"):
        try:
            deep_text = md_path.read_text()
            # Match to a job by filename heuristic (company_title pattern)
            stem = md_path.stem.lower()
            matched = next(
                (j for j in strong_with_deep if stem.startswith(j.company.lower()[:10].replace(" ", "_"))),
                None,
            )
            if not matched:
                continue
            resp = requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=eq.{matched.job_id}",
                headers={**headers, "Prefer": "return=minimal"},
                json={"deep_evaluation": deep_text}, timeout=30,
            )
            resp.raise_for_status()
            updated += 1
        except Exception as e:
            log.warning(f"Supabase: could not sync deep eval for {md_path.name}: {e}")

    if updated:
        log.info(f"Supabase: synced {updated} deep evaluations")


# ---------------------------------------------------------------------------
# Multi-user helpers
# ---------------------------------------------------------------------------
def fetch_users_with_profiles(supabase_url: str, supabase_key: str) -> list[dict]:
    """
    Return a list of active users who have a primary resume set.
    Each dict: {user_id, notify_email, candidate_context, target_roles,
                target_locations, home_city, current_income, city_profiles,
                resume_file_path, resume_file_name}
    Users without a primary resume are skipped.
    """
    if not supabase_url or not supabase_key:
        return []
    headers = _supabase_headers(supabase_key)
    try:
        # Fetch all user profiles
        resp = requests.get(
            f"{supabase_url}/rest/v1/user_profiles?select=*",
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        profiles = resp.json()

        # Fetch primary resumes
        resp2 = requests.get(
            f"{supabase_url}/rest/v1/resumes?is_primary=eq.true&select=user_id,file_path,file_name",
            headers=headers, timeout=15,
        )
        resp2.raise_for_status()
        resumes_by_user = {r["user_id"]: r for r in resp2.json()}

        # Find the admin's city_profiles to use as a global fallback for users
        # who haven't set their own. City cost data is objective and shared.
        global_city_profiles = {}
        for profile in profiles:
            cp = profile.get("city_profiles") or {}
            if cp:
                global_city_profiles = cp
                break  # Use first non-empty set found (admin is first in practice)

        users = []
        for profile in profiles:
            uid = profile["user_id"]
            resume = resumes_by_user.get(uid)
            if not resume:
                log.info(f"Multi-user: skipping user {uid[:8]}… — no primary resume")
                continue
            city_profiles = profile.get("city_profiles") or {}
            users.append({
                "user_id": uid,
                "notify_email": profile.get("notify_email"),
                "candidate_context": profile.get("candidate_context"),
                "target_roles": profile.get("target_roles", []),
                "target_locations": profile.get("target_locations", []),
                "home_city": profile.get("home_city") or "",
                "current_income": profile.get("current_income") or 0,
                # Fall back to global dataset if user has no city profiles
                "city_profiles": city_profiles or global_city_profiles,
                "resume_file_path": resume["file_path"],
                "resume_file_name": resume["file_name"],
            })
        log.info(f"Multi-user: found {len(users)} user(s) with primary resume")
        return users
    except Exception as e:
        log.warning(f"Multi-user: could not fetch user profiles ({e}) — falling back to single-user mode")
        return []


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
        log.info(f"Multi-user: downloaded resume for {user_id[:8]}… → {local_path.name}")
        return local_path
    except Exception as e:
        log.warning(f"Multi-user: could not download resume for {user_id[:8]}… ({e})")
        return None


def _upsert_run_record(
    supabase_url: str,
    key: str,
    user_id: str,
    date_str: str,
    total_jobs: int,
    sources: list[str],
) -> Optional[str]:
    """Create/upsert a run record upfront and return its run_id."""
    headers = _supabase_headers(key)
    run_payload = {
        "run_date": date_str,
        "user_id": user_id,
        "total_jobs": total_jobs,
        "evaluated": 0,
        "strong_count": 0,
        "moderate_count": 0,
        "stretch_count": 0,
        "weak_count": 0,
        "new_job_ids": [],
        "sources": sources,
    }
    try:
        resp = requests.post(
            f"{supabase_url}/rest/v1/runs?on_conflict=user_id,run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=run_payload, timeout=30,
        )
        resp.raise_for_status()
        run_id = resp.json()[0]["id"]
        log.info(f"Incremental sync: upserted run {date_str} for user {user_id[:8]}… → {run_id}")
        return run_id
    except Exception as e:
        log.error(f"Incremental sync: failed to upsert run record for {user_id[:8]}…: {e}")
        return None


def _sync_single_job(
    supabase_url: str,
    key: str,
    user_id: str,
    run_id: str,
    date_str: str,
    job: "JobListing",
):
    """Upsert one job across jobs + user_evaluations + run_jobs. Thread-safe."""
    headers = _supabase_headers(key)
    try:
        # 1. Upsert catalog job record
        job_record = {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "location": job.location or "Unknown",
            "url": job.url or "",
            "source": job.source,
            "salary": job.salary or None,
            "date_posted": job.date_posted or None,
            "tier": job.tier or None,
            "first_seen_run": run_id,
            "last_seen_run": run_id,
            "first_seen_date": date_str,
            "last_seen_date": date_str,
            "date_scraped": job.date_scraped,
        }
        if job.description:
            job_record["description"] = job.description[:50000]
            job_record["description_length"] = len(job.description)
        requests.post(
            f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
            headers={**headers, "Prefer": "resolution=merge-duplicates"},
            json=[job_record],
            timeout=15,
        ).raise_for_status()

        # 2. Upsert user_evaluation
        requests.post(
            f"{supabase_url}/rest/v1/user_evaluations?on_conflict=user_id,job_id",
            headers={**headers, "Prefer": "resolution=merge-duplicates"},
            json=[{
                "user_id": user_id,
                "job_id": job.job_id,
                "match_score": job.match_score,
                "match_verdict": job.match_verdict,
                "match_reasoning": (job.match_reasoning or "")[:500] or None,
                "job_summary": job.job_summary or None,
                "full_evaluation": job.full_evaluation or None,
            }],
            timeout=15,
        ).raise_for_status()

        # 3. Insert run_jobs junction (is_new_this_run set to False initially)
        requests.post(
            f"{supabase_url}/rest/v1/run_jobs?on_conflict=run_id,job_id_ref",
            headers={**headers, "Prefer": "resolution=ignore-duplicates"},
            json=[{
                "run_id": run_id,
                "job_id_ref": job.job_id,
                "is_new_this_run": False,
            }],
            timeout=15,
        ).raise_for_status()

    except Exception as e:
        log.warning(f"Incremental sync: failed for job {job.job_id}: {e}")


def _update_run_record(
    supabase_url: str,
    key: str,
    run_id: str,
    user_jobs: list["JobListing"],
    new_job_ids: set,
):
    """PATCH run with final verdict counts + new_job_ids after batch completes."""
    headers = _supabase_headers(key)
    verdict_counts: dict[str, int] = {}
    for j in user_jobs:
        v = j.match_verdict or "UNSCORED"
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    evaluated = [j for j in user_jobs if j.match_verdict]
    try:
        requests.patch(
            f"{supabase_url}/rest/v1/runs?id=eq.{run_id}",
            headers={**headers, "Prefer": "return=minimal"},
            json={
                "evaluated": len(evaluated),
                "strong_count": verdict_counts.get("STRONG", 0),
                "moderate_count": verdict_counts.get("MODERATE", 0),
                "stretch_count": verdict_counts.get("STRETCH", 0),
                "weak_count": verdict_counts.get("WEAK", 0),
                "new_job_ids": sorted(new_job_ids),
            },
            timeout=30,
        ).raise_for_status()
        log.info(f"Incremental sync: updated run {run_id} with final counts")

        # Batch-update is_new_this_run for new jobs
        if new_job_ids:
            BATCH = 100
            sorted_ids = sorted(new_job_ids)
            for i in range(0, len(sorted_ids), BATCH):
                batch_ids = sorted_ids[i:i + BATCH]
                id_filter = ",".join(batch_ids)
                requests.patch(
                    f"{supabase_url}/rest/v1/run_jobs?run_id=eq.{run_id}&job_id_ref=in.({id_filter})",
                    headers={**headers, "Prefer": "return=minimal"},
                    json={"is_new_this_run": True},
                    timeout=30,
                ).raise_for_status()
            log.info(f"Incremental sync: marked {len(new_job_ids)} jobs as new_this_run")

    except Exception as e:
        log.error(f"Incremental sync: failed to update run {run_id}: {e}")


def sync_to_supabase_for_user(
    config: dict,
    jobs: list[JobListing],
    user_id: str,
    new_job_ids: set,
    metadata: dict,
):
    """
    Upsert run + catalog jobs + user_evaluations for a single user.
    Evaluation fields go into user_evaluations, not jobs.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)
    date_str = metadata["date"]
    verdict_counts = metadata.get("verdicts", {})
    BATCH = 100

    try:
        # 1. Upsert run (scoped to this user)
        run_payload = {
            "run_date": date_str,
            "user_id": user_id,
            "total_jobs": metadata["total_jobs"],
            "evaluated": metadata["evaluated"],
            "strong_count": verdict_counts.get("STRONG", 0),
            "moderate_count": verdict_counts.get("MODERATE", 0),
            "stretch_count": verdict_counts.get("STRETCH", 0),
            "weak_count": verdict_counts.get("WEAK", 0),
            "new_job_ids": sorted(new_job_ids),
            "sources": sorted(set(j.source for j in jobs)),
        }
        run_resp = requests.post(
            f"{supabase_url}/rest/v1/runs?on_conflict=user_id,run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=run_payload, timeout=30,
        )
        run_resp.raise_for_status()
        run_id = run_resp.json()[0]["id"]
        log.info(f"Multi-user: upserted run {date_str} for user {user_id[:8]}… → {run_id}")

        # 2. Upsert catalog-only job records (no eval fields)
        evaluated = [j for j in jobs if j.match_verdict]
        for i in range(0, len(evaluated), BATCH):
            batch = evaluated[i:i + BATCH]
            catalog_records = [{
                "job_id": j.job_id,
                "title": j.title,
                "company": j.company,
                "location": j.location or "Unknown",
                "url": j.url or "",
                "source": j.source,
                "salary": j.salary or None,
                "date_posted": j.date_posted or None,
                "tier": j.tier or None,
                "first_seen_run": run_id,
                "last_seen_run": run_id,
                "first_seen_date": date_str,
                "last_seen_date": date_str,
                "date_scraped": j.date_scraped,
            } for j in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=catalog_records, timeout=60,
            )
            resp.raise_for_status()

        # 3. Upsert user_evaluations
        for i in range(0, len(evaluated), BATCH):
            batch = evaluated[i:i + BATCH]
            eval_records = [{
                "user_id": user_id,
                "job_id": j.job_id,
                "match_score": j.match_score,
                "match_verdict": j.match_verdict,
                "match_reasoning": (j.match_reasoning or "")[:500] or None,
                "job_summary": j.job_summary or None,
                "full_evaluation": j.full_evaluation or None,
            } for j in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/user_evaluations?on_conflict=user_id,job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=eval_records, timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Multi-user: upserted {len(evaluated)} jobs + evals for user {user_id[:8]}…")

        # 4. Insert run_jobs junction rows
        rj_records = [{
            "run_id": run_id,
            "job_id_ref": j.job_id,
            "is_new_this_run": j.job_id in new_job_ids,
        } for j in evaluated]
        for i in range(0, len(rj_records), BATCH):
            resp = requests.post(
                f"{supabase_url}/rest/v1/run_jobs?on_conflict=run_id,job_id_ref",
                headers={**headers, "Prefer": "resolution=ignore-duplicates"},
                json=rj_records[i:i + BATCH], timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Multi-user: sync complete for user {user_id[:8]}… (run {run_id})")

    except Exception as e:
        log.error(f"Multi-user: Supabase sync failed for user {user_id[:8]}…: {e}")


def sync_deep_evals_for_user(config: dict, jobs: list[JobListing], user_id: str):
    """Patch deep_evaluation in user_evaluations for STRONG jobs after deep eval pass."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)
    strong_with_deep = [j for j in jobs if j.match_verdict == "STRONG" and j.full_evaluation]

    date_str = datetime.now().strftime("%Y-%m-%d")
    deep_dir = RESULTS_DIR / date_str / "strong" / "deep"
    if not deep_dir.exists():
        return

    updated = 0
    for md_path in deep_dir.glob("*.md"):
        try:
            deep_text = md_path.read_text()
            stem = md_path.stem.lower()
            matched = next(
                (j for j in strong_with_deep if stem.startswith(j.company.lower()[:10].replace(" ", "_"))),
                None,
            )
            if not matched:
                continue
            resp = requests.patch(
                f"{supabase_url}/rest/v1/user_evaluations"
                f"?user_id=eq.{user_id}&job_id=eq.{matched.job_id}",
                headers={**headers, "Prefer": "return=minimal"},
                json={"deep_evaluation": deep_text}, timeout=30,
            )
            resp.raise_for_status()
            updated += 1
        except Exception as e:
            log.warning(f"Multi-user: could not sync deep eval for {md_path.name}: {e}")

    if updated:
        log.info(f"Multi-user: synced {updated} deep evals for user {user_id[:8]}…")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_scrape(config: dict, quick: bool = False) -> list[JobListing]:
    """Run the scraping pipeline."""
    all_jobs = []

    # Source 1: Google Jobs (SerpAPI → BrightData fallback)
    serpapi_key = config.get("serpapi_key", "")
    brightdata_token = config.get("brightdata_api_token", "")
    used_brightdata_fallback = False

    if serpapi_key:
        scraper = SerpAPIScraper(
            api_key=serpapi_key,
            results_per_query=config["search"]["results_per_query"],
        )
        jobs = scraper.run_all_queries(config)
        if scraper._rate_limited and brightdata_token:
            console.print("[yellow]⚠ SerpAPI quota exhausted — falling back to BrightData[/yellow]")
            used_brightdata_fallback = True
        else:
            all_jobs.extend(jobs)

    if (not serpapi_key or used_brightdata_fallback) and brightdata_token:
        scraper = BrightDataScraper(
            api_token=brightdata_token,
            zone=config.get("brightdata_zone", "serp_api1"),
            results_per_query=config["search"]["results_per_query"],
        )
        jobs = scraper.run_all_queries(config)
        all_jobs.extend(jobs)
    elif not serpapi_key and not brightdata_token:
        console.print("[yellow]⚠ No Google Jobs API key set — skipping[/yellow]")
        console.print("  Set SERPAPI_KEY or BRIGHTDATA_API_TOKEN env var")

    # Source 2: Indeed RSS
    indeed_scraper = IndeedRSSScraper(
        salary_min=config.get("indeed", {}).get("salary_min", 80000)
    )
    jobs = indeed_scraper.run_all_queries(config)
    all_jobs.extend(jobs)

    if not quick:
        # Source 3: AVIXA
        avixa = AVIXAScraper()
        jobs = avixa.run_all_queries(config)
        all_jobs.extend(jobs)

        # Source 4: Career pages
        console.print("\n[bold]Scraping target company career pages...[/bold]")
        career_scraper = CareerPageScraper()
        jobs = career_scraper.run_all_pages(config)
        all_jobs.extend(jobs)

    # Source 5: JobSpy (free direct scraping)
    if config.get("jobspy", {}).get("enabled", False):
        console.print("\n[bold]Scraping via JobSpy (Indeed, Glassdoor, Google, ZipRecruiter)...[/bold]")
        jobspy_scraper = JobSpyScraper()
        jobs = jobspy_scraper.run_all_queries(config)
        all_jobs.extend(jobs)

    return deduplicate_jobs(all_jobs)


def run_evaluate(config: dict, jobs: list[JobListing]) -> list[JobListing]:
    """Run LLM evaluation on jobs."""
    provider = config.get("llm_provider", "openrouter")
    key_map = {
        "openrouter": "openrouter_key",
        "anthropic": "anthropic_key",
        "google_aistudio": "google_aistudio_key",
        "openai_compatible": "openai_compatible_key",
    }
    key_field = key_map.get(provider, "openrouter_key")

    if not config.get(key_field):
        console.print(f"[yellow]⚠ {provider} API key not set — skipping LLM evaluation[/yellow]")
        if provider == "openrouter":
            console.print("  Get a key at https://openrouter.ai/keys")
        elif provider == "anthropic":
            console.print("  Get a key at https://console.anthropic.com")
        elif provider == "google_aistudio":
            console.print("  Get a key at https://aistudio.google.com/apikey")
        return jobs, set()

    # Try to fetch the active resume from Supabase; fall back to local file
    active_path = download_active_resume(config)
    if active_path:
        config = dict(config)
        config["resume_path"] = str(active_path)

    resume_text = load_resume(config)
    if not resume_text:
        console.print("[yellow]⚠ No resume found — skipping LLM evaluation[/yellow]")
        return jobs, set()

    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)
    jobs = evaluator.evaluate_batch(jobs, fetch_descriptions=True)
    return jobs, evaluator.new_job_ids


def run_deep_evaluation(config: dict, jobs: list[JobListing]):
    """
    Run deep second-pass evaluation on STRONG match jobs.
    Saves detailed application prep packages to results/YYYY-MM-DD/strong/deep/.
    """
    deep_cfg = config.get("deep_eval", {})
    if not deep_cfg.get("enabled", False):
        return

    strong_jobs = [j for j in jobs if j.match_verdict == "STRONG"]
    if not strong_jobs:
        console.print("\n[dim]No STRONG matches for deep evaluation.[/dim]")
        return

    deep_provider, deep_model = resolve_model(config, "deep_eval")
    console.print(f"\n[bold]Deep evaluation: {len(strong_jobs)} STRONG match(es)[/bold]")
    console.print(f"[dim]Provider: {deep_provider} | Model: {deep_model}[/dim]")

    resume_text = load_resume(config)
    if not resume_text:
        console.print("[yellow]No resume found — skipping deep evaluation[/yellow]")
        return

    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)

    date_str = datetime.now().strftime("%Y-%m-%d")
    deep_dir = RESULTS_DIR / date_str / "strong" / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)

    def _deep_eval_single(job):
        """Run a single deep evaluation and return (job, result)."""
        first_pass = job.full_evaluation or ""
        result = evaluator.deep_evaluate(job, config, first_pass_eval=first_pass)
        return (job, result)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    saved = 0
    total = len(strong_jobs)
    max_workers = min(4, total)
    console.print(f"[dim]Workers: {max_workers}[/dim]")
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_deep_eval_single, job): job
            for job in strong_jobs
        }
        for future in as_completed(futures):
            completed += 1
            job, result = future.result()
            console.print(f"  [{completed}/{total}] {job.title} @ {job.company}...", end=" ")
            if result:
                safe_name = re.sub(r'[^\w\-]', '_', f"{job.company}_{job.title}")[:80]
                eval_path = deep_dir / f"{safe_name}.md"
                with open(eval_path, "w") as f:
                    f.write(f"# {job.title} — {job.company} (Deep Evaluation)\n\n")
                    f.write(f"**Location:** {job.location}\n")
                    f.write(f"**URL:** {job.url}\n")
                    if job.salary:
                        f.write(f"**Salary:** {job.salary}\n")
                    if job.tier:
                        f.write(f"**Tier:** {job.tier}\n")
                    f.write(f"\n---\n\n{result}\n")
                saved += 1
                console.print("[green]done[/green]")
            else:
                console.print("[red]failed[/red]")

    if saved:
        console.print(f"\n[bold green]Deep evaluations saved: {deep_dir}/ ({saved} files)[/bold green]")


def build_user_context(user: dict, admin_email: str = "edweiss412@gmail.com", config_context: str = "") -> str:
    """
    Build the candidate_context string for a multi-user eval.

    - target_roles and target_locations are always prepended so they
      influence scoring even when the user hasn't written free-form context.
    - The user's own DB context is used exclusively for non-admin users.
      config.yaml context (which is Eric's personal context) only applies
      as a fallback for the admin account, not for other users.
    """
    parts = []

    roles = [r for r in (user.get("target_roles") or []) if r.strip()]
    locs  = [l for l in (user.get("target_locations") or []) if l.strip()]
    if roles:
        parts.append(f"- Target roles: {', '.join(roles)}")
    if locs:
        parts.append(f"- Target locations: {', '.join(locs)}")

    user_context = (user.get("candidate_context") or "").strip()
    if user_context:
        parts.append(user_context)
    elif user.get("email") == admin_email or user.get("notify_email") == admin_email:
        # Admin only: fall back to config.yaml context (Eric's personal details)
        if config_context:
            parts.append(config_context)

    return "\n".join(parts)


def _set_eval_status(supabase_url: str, supabase_key: str, user_id: str, status: str, job_count: int = None, jobs_done: int = None):
    """Update user_profiles.eval_status for a given user."""
    if not supabase_url or not supabase_key:
        return
    headers = _supabase_headers(supabase_key)
    payload = {"eval_status": status}
    if status == "running":
        payload["eval_started_at"] = datetime.utcnow().isoformat() + "Z"
        payload["eval_completed_at"] = None
    elif status in ("completed", "error"):
        payload["eval_completed_at"] = datetime.utcnow().isoformat() + "Z"
    if job_count is not None:
        payload["eval_job_count"] = job_count
    if jobs_done is not None:
        payload["eval_jobs_done"] = jobs_done
    try:
        requests.patch(
            f"{supabase_url}/rest/v1/user_profiles?user_id=eq.{user_id}",
            headers={**headers, "Prefer": "return=minimal"},
            json=payload, timeout=15,
        ).raise_for_status()
    except Exception as e:
        log.warning(f"Could not update eval_status for {user_id[:8]}…: {e}")


def fetch_recent_jobs_for_user(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    days: int = 60,
) -> list[JobListing]:
    """
    Fetch jobs seen in the last `days` days that have no user_evaluation
    for this user yet. Returns them as JobListing objects ready for evaluation.
    """
    from datetime import timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    headers = _supabase_headers(supabase_key)

    # 1. Get job_ids already evaluated for this user
    resp = requests.get(
        f"{supabase_url}/rest/v1/user_evaluations?user_id=eq.{user_id}&select=job_id",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    already_evaluated = {row["job_id"] for row in resp.json()}
    log.info(f"On-demand eval: {len(already_evaluated)} jobs already evaluated for user {user_id[:8]}…")

    # 2. Fetch recent jobs in batches (only pre_filter_passed if available, plus active listings)
    BATCH = 500
    offset = 0
    all_rows = []
    while True:
        query_url = (
            f"{supabase_url}/rest/v1/jobs"
            f"?last_seen_date=gte.{cutoff}"
            f"&listing_status=eq.active"
            f"&select=job_id,title,company,location,url,source,salary,date_posted,tier,date_scraped,description,pre_filter_passed"
            f"&offset={offset}&limit={BATCH}"
        )
        resp = requests.get(query_url, headers=headers, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        all_rows.extend(batch)
        if len(batch) < BATCH:
            break
        offset += BATCH

    # 3. Filter out already-evaluated ones; also skip pre_filter_passed=false if the field is set
    unevaluated = []
    for r in all_rows:
        if r["job_id"] in already_evaluated:
            continue
        # If pre_filter_passed is explicitly False, skip (None means not yet filtered — include it)
        if r.get("pre_filter_passed") is False:
            continue
        unevaluated.append(r)
    log.info(f"On-demand eval: {len(unevaluated)} new jobs to evaluate (of {len(all_rows)} recent)")

    jobs = []
    for r in unevaluated:
        j = JobListing(
            title=r["title"],
            company=r["company"],
            location=r["location"],
            url=r["url"],
            source=r["source"],
            description=r.get("description") or "",
            salary=r.get("salary") or "",
            date_posted=r.get("date_posted") or "",
            date_scraped=r.get("date_scraped") or datetime.now().isoformat(),
            tier=r.get("tier") or "",
        )
        j.job_id = r["job_id"]  # preserve original job_id, don't recompute
        jobs.append(j)
    return jobs


def run_evaluate_for_user(config: dict, user_id: str, days: int = 60):
    """
    On-demand evaluation pipeline for a single user.
    Fetches last `days` days of jobs not yet evaluated, scores them, syncs results.
    Updates user_profiles.eval_status throughout.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")

    if not supabase_url or not supabase_key:
        log.error("On-demand eval: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        return

    console.print(f"\n[bold cyan]On-demand evaluation for user {user_id[:8]}…[/bold cyan]")
    _set_eval_status(supabase_url, supabase_key, user_id, "running")

    try:
        # Fetch user profile
        users = fetch_users_with_profiles(supabase_url, supabase_key)
        user = next((u for u in users if u["user_id"] == user_id), None)
        if not user:
            log.error(f"On-demand eval: user {user_id[:8]}… not found or has no primary resume")
            _set_eval_status(supabase_url, supabase_key, user_id, "error")
            return

        # Build user-specific config — all personal data isolated per user
        user_config = dict(config)
        user_config["candidate_context"] = build_user_context(
            user, config_context=config.get("candidate_context", ""),
        )
        if user.get("home_city"):
            user_config["home_city"] = user["home_city"]
        if user.get("current_income"):
            user_config["current_income"] = user["current_income"]
        if user.get("city_profiles"):
            user_config["city_profiles"] = user["city_profiles"]

        resume_path = download_resume_for_user(
            config, user["user_id"], user["resume_file_path"], user["resume_file_name"],
        )
        if not resume_path:
            log.error(f"On-demand eval: could not download resume for {user_id[:8]}…")
            _set_eval_status(supabase_url, supabase_key, user_id, "error")
            return
        user_config["resume_path"] = str(resume_path)

        resume_text = load_resume(user_config)
        if not resume_text:
            log.error(f"On-demand eval: could not read resume for {user_id[:8]}…")
            _set_eval_status(supabase_url, supabase_key, user_id, "error")
            return

        # Fetch jobs not yet evaluated for this user
        jobs = fetch_recent_jobs_for_user(supabase_url, supabase_key, user_id, days=days)
        if not jobs:
            console.print("[dim]No new jobs to evaluate — all recent jobs already scored.[/dim]")
            _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=0)
            return

        _set_eval_status(supabase_url, supabase_key, user_id, "running", job_count=len(jobs))

        # Evaluate — stream each result to Supabase immediately as it completes
        evaluator = ResumeEvaluator(config=user_config, resume_text=resume_text)
        evaluator.cache_path = SCRIPT_DIR / f"eval_cache_{user_id[:8]}.json"
        headers = _supabase_headers(supabase_key)

        def _progress(done: int):
            _set_eval_status(supabase_url, supabase_key, user_id, "running", jobs_done=done)

        def _on_job_complete(job: JobListing):
            try:
                requests.post(
                    f"{supabase_url}/rest/v1/user_evaluations?on_conflict=user_id,job_id",
                    headers={**headers, "Prefer": "resolution=merge-duplicates"},
                    json=[{
                        "user_id": user_id,
                        "job_id": job.job_id,
                        "match_score": job.match_score,
                        "match_verdict": job.match_verdict,
                        "match_reasoning": (job.match_reasoning or "")[:500] or None,
                        "job_summary": job.job_summary or None,
                        "full_evaluation": job.full_evaluation or None,
                    }],
                    timeout=15,
                )
            except Exception as e:
                log.warning(f"Streaming upsert failed for {job.job_id}: {e}")

        evaluated_jobs = evaluator.evaluate_batch(
            jobs, fetch_descriptions=True,
            progress_callback=_progress, on_job_complete=_on_job_complete,
        )

        scored = [j for j in evaluated_jobs if j.match_verdict]

        console.print(f"\n[bold green]On-demand eval complete: {len(scored)} jobs scored for user {user_id[:8]}…[/bold green]")
        _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=len(scored))

    except Exception as e:
        log.error(f"On-demand eval failed for {user_id[:8]}…: {e}")
        _set_eval_status(supabase_url, supabase_key, user_id, "error")


# ---------------------------------------------------------------------------
# Scrape-only pipeline: descriptions, pre-filter, expired listing checks
# ---------------------------------------------------------------------------

def fetch_descriptions_batch(jobs: list[JobListing], max_workers: int = 8) -> list[JobListing]:
    """Fetch job descriptions in parallel for all jobs that don't already have one."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

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
    console.print(f"  Fetched {fetched}/{len(need_fetch)} descriptions")
    return jobs


def _fetch_desc_for_job(job: JobListing) -> str:
    """Fetch description for a single job, resolving indirect URLs first."""
    url = job.url
    if url and _is_indirect_url(url):
        url = _resolve_apply_url(url)
        job.url = url
    return fetch_job_description(url) if url else ""


def check_expired_listings(config: dict, sample_size: int = 100):
    """
    Check a sample of active job URLs for expiry. Mark expired ones in Supabase.
    Run as part of --scrape-only after syncing new jobs.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return 0, 0

    headers = _supabase_headers(supabase_key)

    # Fetch a sample of active jobs not verified recently (oldest first)
    resp = requests.get(
        f"{supabase_url}/rest/v1/jobs"
        f"?listing_status=eq.active"
        f"&url=neq."
        f"&select=job_id,url"
        f"&order=last_verified_at.asc.nullsfirst"
        f"&limit={sample_size}",
        headers=headers, timeout=30,
    )
    if not resp.ok:
        log.warning(f"Expired check: failed to fetch jobs: {resp.status_code}")
        return 0, 0

    jobs_to_check = resp.json()
    if not jobs_to_check:
        return 0, 0

    console.print(f"[bold]Checking {len(jobs_to_check)} listings for expiry...[/bold]")
    from concurrent.futures import ThreadPoolExecutor, as_completed

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    expired_ids = []
    checked = 0

    def _check_url(job_row):
        url = job_row["url"]
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            # 404, 410 = definitely expired
            if resp.status_code in (404, 410):
                return True
            # Redirected to a generic careers/search page = likely expired
            if resp.status_code == 200 and resp.url:
                final = resp.url.lower()
                if any(p in final for p in ["/search", "/jobs?", "/careers?", "/results", "/job-not-found"]):
                    if job_row["url"].lower() not in final:
                        return True
            return False
        except Exception:
            return False  # Network errors = assume still active

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(_check_url, row): row for row in jobs_to_check}
        for future in as_completed(future_map):
            checked += 1
            row = future_map[future]
            try:
                if future.result():
                    expired_ids.append(row["job_id"])
            except Exception:
                pass

    # Batch-update verified timestamps
    all_ids = [r["job_id"] for r in jobs_to_check]
    BATCH = 50
    for i in range(0, len(all_ids), BATCH):
        batch_ids = all_ids[i:i + BATCH]
        requests.patch(
            f"{supabase_url}/rest/v1/jobs?job_id=in.({','.join(batch_ids)})",
            headers={**headers, "Prefer": "return=minimal"},
            json={"last_verified_at": now_iso},
            timeout=30,
        )

    # Mark expired
    if expired_ids:
        for i in range(0, len(expired_ids), BATCH):
            batch_ids = expired_ids[i:i + BATCH]
            requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=in.({','.join(batch_ids)})",
                headers={**headers, "Prefer": "return=minimal"},
                json={"listing_status": "expired", "listing_expired_at": now_iso},
                timeout=30,
            )
        console.print(f"  Marked {len(expired_ids)} listings as expired")

    log.info(f"Expired check: {checked} checked, {len(expired_ids)} expired")
    return checked, len(expired_ids)


# ---------------------------------------------------------------------------
# Pre-filter: keyword + cheap LLM pass
# ---------------------------------------------------------------------------

# Keyword lists for the pre-filter
RELEVANT_TITLE_KEYWORDS = {
    "audio", "av ", "a/v", "audiovisual", "audio visual", "audio-visual",
    "broadcast", "production engineer", "sound engineer", "sound technician",
    "av engineer", "av technician", "av specialist", "event technology",
    "conference services", "multimedia", "a1 ", "a2 ", "video engineer",
}
IRRELEVANT_TITLE_KEYWORDS = {
    "software engineer", "data analyst", "data engineer", "data scientist",
    "warehouse", "forklift", "truck driver", "nurse", "medical",
    "accountant", "financial analyst", "marketing manager", "sales representative",
    "recruiter", "hr manager", "human resources", "supply chain",
    "mechanical engineer", "civil engineer", "chemical engineer",
    "cloud engineer", "devops", "machine learning", "ml engineer",
    "full stack", "frontend", "backend", "ios developer", "android developer",
    "product manager", "program manager", "scrum master",
}
AV_DESCRIPTION_TERMS = {
    "dante", "crestron", "extron", "qsys", "q-sys", "biamp", "shure",
    "polycom", "cisco webex", "zoom rooms", "teams rooms", "aver",
    "kramer", "atlona", "lightware", "qsc", "harman", "bss",
    "audinate", "sdi", "ndi", "st2110", "st 2110", "tricaster",
    "vmix", "blackmagic", "aja", "ross video", "newtek",
    "allen & heath", "yamaha cl", "yamaha pm", "digico", "midas",
    "avid venue", "soundcraft", "presonus", "pro tools",
    "conference room", "huddle room", "boardroom", "ballroom",
    "av rack", "signal flow", "codec", "dsp", "matrix switcher",
}
# Known target companies that should always pass
TARGET_COMPANY_KEYWORDS = {
    "avi-spl", "diversified", "avispl", "crestron", "extron", "harman",
    "shure", "biamp", "qsc", "encore", "psav",
}


def _keyword_score_job(job: JobListing) -> tuple[float, list[str]]:
    """Score a job based on keyword relevance. Returns (score 0-1, matched_keywords)."""
    title_lower = job.title.lower()
    company_lower = job.company.lower()
    desc_lower = (job.description or "").lower()
    matched = []

    # Check for irrelevant title keywords first (strong negative signal)
    for kw in IRRELEVANT_TITLE_KEYWORDS:
        if kw in title_lower:
            return 0.0, [f"-{kw}"]

    # Target company = automatic pass
    for kw in TARGET_COMPANY_KEYWORDS:
        if kw in company_lower:
            matched.append(f"company:{kw}")
            return 1.0, matched

    score = 0.0

    # Title keyword match (strong signal)
    for kw in RELEVANT_TITLE_KEYWORDS:
        if kw in title_lower:
            score += 0.4
            matched.append(f"title:{kw}")

    # Description keyword density (moderate signal)
    if desc_lower:
        desc_hits = 0
        for term in AV_DESCRIPTION_TERMS:
            if term in desc_lower:
                desc_hits += 1
                matched.append(term)
        if desc_hits >= 3:
            score += 0.4
        elif desc_hits >= 1:
            score += 0.2

    return min(score, 1.0), matched


def _llm_pre_filter(config: dict, jobs: list[JobListing]) -> list[tuple[JobListing, bool, str]]:
    """Run cheap LLM pre-filter on ambiguous jobs. Returns list of (job, passed, reason)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    provider, model = resolve_model(config, "pre_filter")
    log.info(f"Pre-filter LLM: using {provider}/{model} for {len(jobs)} ambiguous jobs")

    # Get the appropriate API key
    key_map = {
        "openrouter": "openrouter_key",
        "google_aistudio": "google_aistudio_key",
        "anthropic": "anthropic_key",
        "openai_compatible": "openai_compatible_key",
    }
    api_key = config.get(key_map.get(provider, "openrouter_key"), "")
    if not api_key:
        log.warning(f"Pre-filter: no API key for {provider} — marking all ambiguous as passed")
        return [(j, True, "no LLM key") for j in jobs]

    results = []

    def _call_llm(job: JobListing) -> tuple[bool, str]:
        import time as _time
        from pipeline_utils import log_api_usage
        prompt = (
            f"Job title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Description excerpt: {(job.description or '')[:500]}\n\n"
            "Is this job relevant to an AV/audio engineering professional "
            "(audiovisual engineer, broadcast engineer, AV technician, event technology, "
            "live sound, corporate AV, conference room technology)? "
            "Reply YES or NO with a 1-sentence reason."
        )
        try:
            _start = _time.time()
            if provider == "google_aistudio":
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=15,
                )
                resp.raise_for_status()
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            else:
                base_url = "https://openrouter.ai/api/v1" if provider == "openrouter" else config.get("openai_compatible_base_url", "")
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 100},
                    timeout=15,
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()

            _latency = int((_time.time() - _start) * 1000)
            log_api_usage(
                source="pipeline", category="llm", operation="pre_filter",
                provider=provider, model=model,
                latency_ms=_latency, success=True,
            )
            passed = text.upper().startswith("YES")
            return passed, text[:200]
        except Exception as e:
            log.debug(f"Pre-filter LLM failed for {job.title}: {e}")
            return True, f"LLM error: {e}"  # Default to pass on error

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(_call_llm, j): j for j in jobs}
        for future in as_completed(future_map):
            job = future_map[future]
            try:
                passed, reason = future.result()
            except Exception:
                passed, reason = True, "error"
            results.append((job, passed, reason))

    return results


def run_pre_filter(config: dict, jobs: list[JobListing]):
    """
    Two-layer pre-filter: keyword scoring + cheap LLM for ambiguous jobs.
    Updates pre_filter_score, pre_filter_passed, title_keywords in Supabase.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)

    console.print(f"\n[bold]Pre-filtering {len(jobs)} jobs...[/bold]")

    # Layer 1: keyword scoring
    clear_pass = []     # score >= 0.7 → pass
    clear_fail = []     # score == 0.0 → fail
    ambiguous = []      # 0.0 < score < 0.7 → needs LLM

    for job in jobs:
        score, keywords = _keyword_score_job(job)
        job._pf_score = score
        job._pf_keywords = keywords
        if score >= 0.7:
            clear_pass.append(job)
        elif score == 0.0:
            clear_fail.append(job)
        else:
            ambiguous.append(job)

    console.print(f"  Keywords: {len(clear_pass)} pass, {len(clear_fail)} fail, {len(ambiguous)} ambiguous")

    # Layer 2: cheap LLM for ambiguous jobs
    llm_results = {}
    if ambiguous:
        # Check if pre_filter model is configured
        models = config.get("models", {})
        if models.get("pre_filter", {}).get("model"):
            llm_out = _llm_pre_filter(config, ambiguous)
            for job, passed, reason in llm_out:
                llm_results[job.job_id] = (passed, reason)
            llm_passed = sum(1 for _, p, _ in llm_out if p)
            console.print(f"  LLM: {llm_passed}/{len(ambiguous)} ambiguous jobs passed")
        else:
            console.print(f"  [dim]No pre_filter model configured — passing all {len(ambiguous)} ambiguous jobs[/dim]")
            for job in ambiguous:
                llm_results[job.job_id] = (True, "no model configured")

    # Build update payloads and batch-update Supabase
    stats = {"total": len(jobs), "passed": 0, "failed": 0, "llm_called": len(ambiguous)}
    BATCH = 50

    all_updates = []
    for job in jobs:
        score = getattr(job, "_pf_score", 0.0)
        keywords = getattr(job, "_pf_keywords", [])

        if job in clear_pass:
            passed = True
        elif job in clear_fail:
            passed = False
        else:
            passed = llm_results.get(job.job_id, (True, ""))[0]

        if passed:
            stats["passed"] += 1
        else:
            stats["failed"] += 1

        all_updates.append({
            "job_id": job.job_id,
            "pre_filter_score": round(score, 3),
            "pre_filter_passed": passed,
            "title_keywords": keywords[:20],  # cap array size
        })

    # Update pre-filter columns on existing rows (PATCH, not upsert)
    failed = 0
    for update in all_updates:
        job_id = update["job_id"]
        payload = {k: v for k, v in update.items() if k != "job_id"}
        try:
            requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=eq.{job_id}",
                headers=headers,
                json=payload,
                timeout=10,
            ).raise_for_status()
        except Exception:
            failed += 1
    if failed:
        log.warning(f"Pre-filter: {failed}/{len(all_updates)} updates failed")

    console.print(f"  [bold green]Pre-filter complete:[/bold green] {stats['passed']} passed, {stats['failed']} filtered out")
    return stats


def sync_scrape_results(config: dict, jobs: list[JobListing], date_str: str):
    """
    Sync scrape-only results to Supabase: upsert scrape_runs + batch upsert jobs catalog.
    No evaluation data, no runs/user_evaluations writes.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        log.info("Supabase: not configured — skipping scrape sync")
        return 0

    headers = _supabase_headers(supabase_key)
    sources = sorted(set(j.source for j in jobs))

    # 1. Count how many are truly new (not yet in DB)
    existing_ids = set()
    BATCH = 500
    offset = 0
    while True:
        resp = requests.get(
            f"{supabase_url}/rest/v1/jobs?select=job_id&offset={offset}&limit={BATCH}",
            headers=headers, timeout=30,
        )
        if not resp.ok:
            break
        batch = resp.json()
        existing_ids.update(r["job_id"] for r in batch)
        if len(batch) < BATCH:
            break
        offset += BATCH

    new_count = sum(1 for j in jobs if j.job_id not in existing_ids)

    # 2. Batch upsert job catalog records (no eval data)
    BATCH = 100
    for i in range(0, len(jobs), BATCH):
        batch = jobs[i:i + BATCH]
        records = []
        for j in batch:
            rec = {
                "job_id": j.job_id,
                "title": j.title,
                "company": j.company,
                "location": j.location or "Unknown",
                "url": j.url or "",
                "source": j.source,
                "salary": j.salary or None,
                "date_posted": j.date_posted or None,
                "tier": j.tier or None,
                "first_seen_date": date_str,
                "last_seen_date": date_str,
                "date_scraped": j.date_scraped,
                "listing_status": "active",
            }
            if j.description:
                rec["description"] = j.description[:50000]
                rec["description_length"] = len(j.description)
            records.append(rec)
        try:
            requests.post(
                f"{supabase_url}/rest/v1/jobs?on_conflict=job_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=records, timeout=60,
            ).raise_for_status()
        except Exception as e:
            log.warning(f"Scrape sync: batch upsert failed: {e}")

    log.info(f"Scrape sync: upserted {len(jobs)} jobs ({new_count} new)")

    # 3. Upsert scrape_runs record
    try:
        requests.post(
            f"{supabase_url}/rest/v1/scrape_runs?on_conflict=run_date",
            headers={**headers, "Prefer": "resolution=merge-duplicates"},
            json=[{
                "run_date": date_str,
                "total_scraped": len(jobs),
                "new_jobs": new_count,
                "sources": sources,
            }],
            timeout=30,
        ).raise_for_status()
        log.info(f"Scrape sync: upserted scrape_run for {date_str}")
    except Exception as e:
        log.warning(f"Scrape sync: failed to upsert scrape_run: {e}")

    return new_count


def cleanup_old_results(max_age_days: int = 30):
    """Remove results and data older than max_age_days."""
    import shutil

    cutoff = datetime.now() - timedelta(days=max_age_days)
    removed = 0

    # Clean date-based run directories (results/2026-02-16/)
    for item in RESULTS_DIR.iterdir():
        if item.is_dir() and item.name != "benchmarks":
            try:
                dir_date = datetime.strptime(item.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    shutil.rmtree(item)
                    removed += 1
                    log.info(f"Cleaned up old results: {item.name}")
            except ValueError:
                # Not a date-named directory (legacy format), check modification time
                if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                    shutil.rmtree(item)
                    removed += 1
                    log.info(f"Cleaned up old results: {item.name}")

    # Clean legacy flat files in results/ (jobs_*.csv, jobs_*.md)
    for item in RESULTS_DIR.iterdir():
        if item.is_file() and item.name.startswith("jobs_"):
            if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                item.unlink()
                removed += 1
                log.info(f"Cleaned up old file: {item.name}")

    # Clean old JSON data files
    for item in DATA_DIR.iterdir():
        if item.is_file() and item.name.startswith("jobs_"):
            if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                item.unlink()
                removed += 1
                log.info(f"Cleaned up old data: {item.name}")

    if removed:
        log.info(f"Cleanup complete: removed {removed} items older than {max_age_days} days")


def main():
    parser = argparse.ArgumentParser(description="Job Search Automation Pipeline")
    parser.add_argument("--quick", action="store_true", help="Quick scan (SerpAPI + Indeed only)")
    parser.add_argument("--evaluate-only", action="store_true", help="Re-evaluate existing results")
    parser.add_argument("--no-evaluate", action="store_true", help="Scrape only, skip LLM scoring")
    parser.add_argument("--schedule", action="store_true", help="Run on configured schedule")
    parser.add_argument(
        "--benchmark", action="store_true",
        help="Run multiple models against a sample of jobs to compare quality and cost",
    )
    parser.add_argument("--no-deep", action="store_true", help="Skip deep evaluation of STRONG matches")
    parser.add_argument("--jobspy-only", action="store_true", help="Only scrape via JobSpy (skip SerpAPI/Indeed/AVIXA/career pages)")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape + store descriptions + pre-filter only (no LLM evaluation)")
    parser.add_argument("--evaluate-for-user", metavar="USER_ID", help="On-demand: evaluate last 60 days of jobs for a specific user UUID")
    args = parser.parse_args()

    config = load_config()

    # Auto-cleanup results older than 30 days
    cleanup_old_results(max_age_days=30)

    console.print("[bold blue]═══════════════════════════════════════[/bold blue]")
    console.print("[bold blue]  Job Search Automation Pipeline[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════[/bold blue]\n")

    if args.evaluate_for_user:
        run_evaluate_for_user(config, args.evaluate_for_user)
        return

    if args.scrape_only:
        console.print("[bold]Scrape-only mode: scraping + descriptions + pre-filter (no LLM evaluation)[/bold]\n")
        jobs = run_scrape(config, quick=args.quick)
        if jobs:
            date_str = datetime.now().strftime("%Y-%m-%d")
            # Fetch descriptions for new jobs
            fetch_descriptions_batch(jobs, max_workers=8)
            # Sync raw catalog to Supabase
            new_count = sync_scrape_results(config, jobs, date_str)
            # Run pre-filter (keyword + optional cheap LLM)
            pf_stats = run_pre_filter(config, jobs)
            # Check for expired listings
            checked, expired = check_expired_listings(config, sample_size=100)
            # Update scrape_run with pre-filter stats + expired counts
            supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
            supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
            if supabase_url and supabase_key:
                try:
                    requests.patch(
                        f"{supabase_url}/rest/v1/scrape_runs?run_date=eq.{date_str}",
                        headers={**_supabase_headers(supabase_key), "Prefer": "return=minimal"},
                        json={
                            "expired_checked": checked,
                            "expired_found": expired,
                            "pre_filter_stats": pf_stats or {},
                        },
                        timeout=30,
                    )
                except Exception as e:
                    log.warning(f"Could not update scrape_run with stats: {e}")

            # Save results locally too
            json_path, csv_path, md_path = save_results(jobs)
            console.print(f"\n[bold green]Scrape-only complete:[/bold green]")
            console.print(f"  Total scraped: {len(jobs)} ({new_count} new)")
            if pf_stats:
                console.print(f"  Pre-filter: {pf_stats.get('passed', 0)} passed, {pf_stats.get('failed', 0)} filtered")
            console.print(f"  Expired: {expired}/{checked} checked")
            # Write run_metadata.json for downstream scripts
            metadata = {
                "date": date_str,
                "results_dir": str(RESULTS_DIR / date_str),
                "total_jobs": len(jobs),
                "new_jobs": new_count,
                "mode": "scrape_only",
                "pre_filter_stats": pf_stats or {},
                "expired_checked": checked,
                "expired_found": expired,
            }
            metadata_path = SCRIPT_DIR / "run_metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        else:
            console.print("[yellow]No job listings found. Check your config and API keys.[/yellow]")
        return

    if args.schedule:
        run_scheduled(config)
        return

    if args.benchmark:
        run_benchmark(config)
        return

    if args.evaluate_only:
        jobs = load_previous_results()
        if not jobs:
            console.print("[red]No previous results found in data/ directory[/red]")
            return
        console.print(f"Loaded {len(jobs)} listings from previous scan")
    elif args.jobspy_only:
        console.print("[bold]Running JobSpy only (skipping SerpAPI/Indeed/AVIXA/career pages)...[/bold]\n")
        jobspy_scraper = JobSpyScraper()
        jobs = deduplicate_jobs(jobspy_scraper.run_all_queries(config))
    else:
        jobs = run_scrape(config, quick=args.quick)

    new_job_ids = set()
    if not args.no_evaluate and jobs:
        jobs, new_job_ids = run_evaluate(config, jobs)

    if jobs:
        json_path, csv_path, md_path = save_results(jobs)
        print_summary(jobs)
        console.print(f"\n[bold green]Results saved:[/bold green]")
        console.print(f"  📊 CSV:      {csv_path}")
        console.print(f"  📝 Markdown: {md_path}")
        console.print(f"  💾 Raw JSON: {json_path}")

        # Write run metadata for downstream scripts (email_sender, build_site)
        date_str = datetime.now().strftime("%Y-%m-%d")
        verdict_counts = {}
        for j in jobs:
            v = j.match_verdict or "UNSCORED"
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
        metadata = {
            "date": date_str,
            "results_dir": str(RESULTS_DIR / date_str),
            "total_jobs": len(jobs),
            "evaluated": len([j for j in jobs if j.match_verdict]),
            "verdicts": verdict_counts,
            "new_job_ids": sorted(new_job_ids),
        }
        metadata_path = SCRIPT_DIR / "run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        log.info(f"Run metadata saved to {metadata_path}")

        # Sync to Supabase — multi-user or single-user path
        supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
        users = fetch_users_with_profiles(supabase_url, supabase_key) if supabase_url else []

        if users:
            # Multi-user: evaluate + sync per user against their own resume
            # Uses incremental sync — each job is pushed to Supabase as it completes
            from copy import deepcopy
            for user in users:
                uid = user["user_id"]
                console.print(f"\n[bold cyan]── User {uid[:8]}… ──[/bold cyan]")

                user_config = dict(config)
                # Build user-specific config — all personal data isolated per user
                user_config["candidate_context"] = build_user_context(
                    user, config_context=config.get("candidate_context", ""),
                )
                if user.get("home_city"):
                    user_config["home_city"] = user["home_city"]
                if user.get("current_income"):
                    user_config["current_income"] = user["current_income"]
                if user.get("city_profiles"):
                    user_config["city_profiles"] = user["city_profiles"]

                resume_path = download_resume_for_user(
                    config, uid,
                    user["resume_file_path"], user["resume_file_name"],
                )
                if not resume_path:
                    log.warning(f"Multi-user: skipping user {uid[:8]}… — resume download failed")
                    continue
                user_config["resume_path"] = str(resume_path)

                resume_text = load_resume(user_config)
                if not resume_text:
                    log.warning(f"Multi-user: skipping user {uid[:8]}… — could not read resume")
                    continue

                # Create run record upfront so incremental syncs can reference it
                sources = sorted(set(j.source for j in jobs))
                run_id = _upsert_run_record(supabase_url, supabase_key, uid, date_str, len(jobs), sources)

                # Set eval status to running
                _set_eval_status(supabase_url, supabase_key, uid, "running", job_count=len(jobs))

                evaluator = ResumeEvaluator(config=user_config, resume_text=resume_text)
                evaluator.cache_path = SCRIPT_DIR / f"eval_cache_{uid[:8]}.json"

                # Track which jobs were synced via callback to avoid double-syncing
                synced_job_ids: set[str] = set()

                def _on_job_complete(job: JobListing, _uid=uid, _run_id=run_id):
                    if _run_id and job.match_verdict:
                        _sync_single_job(supabase_url, supabase_key, _uid, _run_id, date_str, job)
                        synced_job_ids.add(job.job_id)

                jobs_done_counter = [0]
                def _progress(done: int, _uid=uid):
                    jobs_done_counter[0] = done
                    if done % 5 == 0 or done == len(jobs):
                        _set_eval_status(supabase_url, supabase_key, _uid, "running", jobs_done=done)

                user_jobs = evaluator.evaluate_batch(
                    deepcopy(jobs), fetch_descriptions=True,
                    on_job_complete=_on_job_complete, progress_callback=_progress,
                )
                user_new_ids = evaluator.new_job_ids

                # Batch-sync any evaluated jobs that weren't sent via callback (e.g. from cache)
                if run_id:
                    missed = [j for j in user_jobs if j.match_verdict and j.job_id not in synced_job_ids]
                    for j in missed:
                        _sync_single_job(supabase_url, supabase_key, uid, run_id, date_str, j)

                    # Update run record with final verdict counts + new_job_ids
                    _update_run_record(supabase_url, supabase_key, run_id, user_jobs, user_new_ids)

                _set_eval_status(supabase_url, supabase_key, uid, "completed", job_count=len([j for j in user_jobs if j.match_verdict]))

                if not args.no_deep and not args.no_evaluate:
                    run_deep_evaluation(user_config, user_jobs)
                    sync_deep_evals_for_user(config, user_jobs, uid)
        else:
            # Single-user backward-compat path
            sync_to_supabase(config, jobs, new_job_ids, metadata)

            if not args.no_deep and not args.no_evaluate:
                run_deep_evaluation(config, jobs)
                sync_deep_evals(config, jobs)
    else:
        console.print("[yellow]No job listings found. Check your config and API keys.[/yellow]")


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
    # Models to benchmark — edit this list to test others.
    # Format: (model_id, display_name, approx_cost_per_1M_output_tokens, provider_override)
    # provider_override: None = use OpenRouter, "google_aistudio" = use Google AI Studio direct
    BENCHMARK_MODELS = [
        # --- 7/8 calibration leaders ---
        ("google/gemini-3-flash-preview", "Gemini 3 Flash", 0.40, None),       # production model
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

    console.print("[bold blue]═══════════════════════════════════════[/bold blue]")
    console.print("[bold blue]  LLM Benchmark — Model Comparison[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════[/bold blue]\n")
    console.print(f"Testing {len(BENCHMARK_MODELS)} models × {len(sample_jobs)} jobs [bold green](parallel)[/bold green]\n")

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
                console.print(f"  [red]{model_name}: Failed to initialize — skipping[/red]")
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
                        f"{job.title[:30]}… "
                        f"{result['verdict'] or '???'} — {elapsed:.1f}s "
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
                    console.print(f"\n[bold green]✓ {model_name} complete[/bold green]")

    # --- Generate comparison report ---
    _save_benchmark_report(results, sample_jobs)


def _get_benchmark_samples(config: dict) -> list[JobListing]:
    """
    Get benchmark samples combining:
    1. Synthetic test cases with human-verified expected verdicts (ground truth)
    2. Real jobs from previous runs for real-world variety (1 per verdict category)

    The synthetic cases are the calibration benchmark — models that get these
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
        # (skills match but bad economics — e.g. part-time venue gig).
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
    console.print("No previous results found — using built-in test postings")
    synthetic = [
        JobListing(
            title="AV Engineer",
            company="Goldman Sachs",
            location="New York, NY",
            url="",
            source="benchmark",
            tier="Tier 2 — Finance",
            description="""AV Engineer — Goldman Sachs — New York, NY

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
            tier="Tier 2 — Finance",
            description="""Technology Delivery Analyst, VP — BlackRock — New York

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
            tier="Tier 3 — Big Tech",
            description="""Broadcast Systems Engineer — Netflix — Los Angeles, CA

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
            description="""Production Technician - 2nd Shift — Dynamic Manufacturing — Hillside, IL

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
        "# LLM Benchmark — Model Comparison",
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
                    verdict_cells.append(f"**{actual}** ✓")
                    calibration_hits += 1
                else:
                    verdict_cells.append(f"{actual} ✗")
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
            match_icon = "✓" if actual_v == expected.lstrip("~") else "✗"
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
- **Goldman Sachs AV Engineer → MODERATE** — Skills transfer well but Crestron/Extron gap and relocation cost.
- **BlackRock Tech Delivery Analyst → STRONG** — Disguised AV/audio role, excellent skills match, strong comp.
- **Netflix Broadcast Systems Engineer → WEAK** — Studio/post-production engineering is a different discipline (Pro Tools/Avid S6/Atmos/AES67 are genuine gaps).

When comparing models, also look for:
1. **Verdict honesty** — Does the model correctly downgrade when pay/seniority don't match, even if skills overlap?
2. **Citation quality** — Does it cite specific resume lines or hand-wave?
3. **Gap honesty** — Does it distinguish dealbreakers from nice-to-haves?
4. **Title translation** — Does it catch disguised titles (e.g., "Technology Delivery Analyst, VP" = Lead Audio Engineer)?""")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    console.print(f"\n[bold green]Benchmark report saved: {report_path}[/bold green]")
    console.print("\nOpen it and compare:")
    console.print("  • Did each model produce all 7 sections?")
    console.print("  • Is the Netflix role rated STRETCH/WEAK? (it should be)")
    console.print("  • Does the model cite specific resume lines or hand-wave?")
    console.print("  • Is the BlackRock title correctly translated?")


def run_scheduled(config: dict):
    """Run on a schedule defined in config."""
    import sched
    import threading

    schedule_config = config.get("schedule", {})
    console.print("[bold]Running in scheduled mode. Press Ctrl+C to stop.[/bold]")
    console.print(f"  Full scan: {schedule_config.get('full_scan', 'weekly')}")
    console.print(f"  Quick scan: {schedule_config.get('quick_scan', 'daily')}")

    while True:
        try:
            console.print(f"\n[dim]Running quick scan at {datetime.now()}...[/dim]")
            jobs = run_scrape(config, quick=True)
            if jobs:
                jobs = run_evaluate(config, jobs)
                save_results(jobs)
                print_summary(jobs)

            # Sleep until next run (24h for daily quick scan)
            next_run = 24 * 60 * 60
            console.print(f"[dim]Next scan in {next_run // 3600} hours[/dim]")
            time.sleep(next_run)
        except KeyboardInterrupt:
            console.print("\n[bold]Scheduler stopped.[/bold]")
            break


if __name__ == "__main__":
    main()
