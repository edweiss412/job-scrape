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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode

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

            # Prefer direct apply link over Google Jobs share link
            apply_options = item.get("apply_options", [])
            if apply_options:
                url = apply_options[0].get("link", "")
            else:
                url = item.get("share_link", item.get("link", ""))

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

            # Link is a Google Jobs detail URL; postings may have direct apply links
            url = item.get("link", "")
            postings = item.get("postings", [])
            if postings and isinstance(postings, list):
                url = postings[0].get("link", url)

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
                        # Keep the one with more description
                        merged_indices.add(j)
                        if len(group[j].description) > len(job_a.description):
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

    def __init__(self, config: dict, resume_text: str):
        self.resume_text = resume_text
        self.candidate_context = config.get("candidate_context", "")
        self.city_profiles = config.get("city_profiles", {})
        self.provider = config.get("llm_provider", "openrouter")
        self.client = None
        self.model = None
        self.new_job_ids = set()  # job_ids evaluated fresh this run (not cached)
        self.cache_path = SCRIPT_DIR / "eval_cache.json"  # override per-user via evaluator.cache_path

        if self.provider == "openrouter":
            api_key = config.get("openrouter_key", "")
            self.model = config.get("openrouter_model", "anthropic/claude-sonnet-4")
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
            self.model = config.get("anthropic_model", "claude-sonnet-4-20250514")
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
            self.model = config.get("google_aistudio_model", "gemini-2.5-flash")
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
            self.model = config.get("openai_compatible_model", "local-model")
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=base_url, api_key=api_key)
            except ImportError:
                log.error("Install openai: pip install openai")

        else:
            log.error(f"Unknown LLM provider: {self.provider}")

    def _call_llm(self, prompt: str) -> str:
        """Send a prompt to the configured LLM and return the response text."""
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
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
            return response.choices[0].message.content.strip()

    def _city_profiles_str(self) -> str:
        """Format city relocation profiles for injection into the prompt."""
        if not self.city_profiles:
            return ""
        baseline = self.city_profiles.get("Chicago, IL", {})
        baseline_cost = baseline.get("monthly_cost", 2354)

        lines = [
            "RELOCATION REFERENCE DATA (candidate baseline: Ravenswood, Chicago — "
            f"$1,900/mo rent, 4.95% tax, ${baseline_cost:,}/mo total):\n"
        ]
        for city, profile in self.city_profiles.items():
            if city == "Chicago, IL":
                continue
            premium = profile.get("annual_premium", 0)
            premium_str = f"+${premium:,}/yr" if premium > 0 else f"-${abs(premium):,}/yr (cheaper)"
            lines.append(
                f"  {city} ({profile.get('neighborhood', '?')}):\n"
                f"    Rent: ${profile.get('rent_1br', '?'):,}/mo | Tax: {profile.get('tax_rate', 0):.1%} "
                f"| Total: ${profile.get('monthly_cost', '?'):,}/mo ({premium_str} vs Chicago)\n"
                f"    Commute: {profile.get('commute', '?')}\n"
                f"    Walk: {profile.get('walk_score', '?')} | Bike: {profile.get('bike_score', '?')} "
                f"| Car required: {'Yes' if profile.get('car_required') else 'No'}\n"
                f"    Waterfront: {profile.get('waterfront', '?')}\n"
                f"    Notes: {profile.get('lifestyle_notes', '')}"
            )
        return "\n".join(lines)

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

        job_info = f"""Title: {job.title}
Company: {job.company}
Location: {job.location}
Source: {job.source}
Salary: {job.salary or 'Not listed'}
Company Tier: {job.tier or 'N/A'}

Description:
{job.description or '(No description available — evaluate based on title/company only)'}"""

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
Rate the overall match on this scale:
- 🟢 STRONG MATCH — Candidate meets 80%+ of requirements and experience is directly relevant
- 🟡 MODERATE MATCH — Candidate meets 60-80% of requirements, with addressable gaps
- 🟠 STRETCH — Candidate meets 40-60% of requirements, significant gaps but potentially worth pursuing
- 🔴 WEAK MATCH — Below 40%, likely not worth the time to apply

### 3. REQUIREMENTS ALREADY MET
List each requirement from the posting alongside the specific line, bullet, or section of the resume that demonstrates it. Be precise — cite actual resume content.

### 4. REQUIREMENTS WITH EXPERIENCE BUT NOT HIGHLIGHTED
Things the candidate can likely do based on the full picture of the resume and context but that aren't explicitly stated or are buried. For each, suggest where and how to surface it in a tailored version.

### 5. TRUE GAPS
Requirements where the candidate genuinely lacks the qualification or experience. Be honest — don't stretch. For each gap, note:
- How critical it appears to be (dealbreaker vs. nice-to-have vs. learnable)
- Whether it's something that could realistically be developed quickly or addressed in a cover letter

### 6. RED FLAGS & LOGISTICS
- Location/relocation requirements and whether they're feasible given Chicago base
- Salary range (if listed) and whether it aligns with experience level
- Any requirements that suggest a different seniority level (too junior or too senior)
- ATS keywords from the posting that are missing from the resume
- Anything that seems off about the posting (vague requirements, unrealistic expectations, title/comp mismatch)

### 7. VERDICT
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
- COMPENSATION & RELOCATION ANALYSIS: The candidate currently earns ~$85K/year freelancing in Chicago (Ravenswood). Use the relocation reference data below to perform a full financial and lifestyle comparison for any role outside Chicago. For each non-Chicago role:
  1. Estimate or use the listed salary
  2. Calculate the annual relocation premium from the reference data (rent + tax difference)
  3. Add car ownership costs ($6,000-9,600/yr) if car_required=Yes for that city
  4. Calculate **net annual gain** = (new salary - $85K) - annual_premium - car_costs
  5. If net annual gain is negative or negligible (<$5K), downgrade the match by one level
  6. Factor in lifestyle: Walk Score, Bike Score, waterfront access, commute. If a move represents a significant QOL downgrade from Ravenswood, note it clearly
  7. A permanent role also offers benefits (health insurance, 401k match, PTO) worth ~$15-25K/yr — factor this into the comparison vs. freelance
  Always show your math in the RED FLAGS & LOGISTICS section.
{self._city_profiles_str()}
- LOCATION MATTERS: The candidate will only relocate to walkable urban areas (e.g., NYC, Boston, SF, DC, Seattle). Suburban or car-dependent locations should be flagged as a negative. If relocation is required to a non-walkable area, downgrade the match accordingly.

After the full evaluation, add final lines in exactly this format:
JOB_SUMMARY: [2-sentence plain-text summary of the role itself. Do NOT mention the candidate.]
MATCH_LEVEL: [STRONG|MODERATE|STRETCH|WEAK]"""

        try:
            text = self._call_llm(prompt)

            # Extract match level from the trailing tag
            verdict = ""
            score = 0
            level_match = re.search(r"MATCH_LEVEL:\s*(STRONG|MODERATE|STRETCH|WEAK)", text)
            if level_match:
                verdict = level_match.group(1)
                score = {
                    "STRONG": 85,
                    "MODERATE": 70,
                    "STRETCH": 50,
                    "WEAK": 25,
                }.get(verdict, 0)
            else:
                # Fallback: detect from emoji
                if "🟢" in text:
                    verdict, score = "STRONG", 85
                elif "🟡" in text:
                    verdict, score = "MODERATE", 70
                elif "🟠" in text:
                    verdict, score = "STRETCH", 50
                elif "🔴" in text:
                    verdict, score = "WEAK", 25

            # Extract JOB_SUMMARY from trailing tags
            job_summary = ""
            summary_match = re.search(
                r"JOB_SUMMARY:\s*(.+?)(?:\nMATCH_LEVEL)", text, re.DOTALL,
            )
            if summary_match:
                job_summary = summary_match.group(1).strip()

            # Extract a short reasoning from the verdict section
            reasoning = ""
            verdict_section = re.search(
                r"###?\s*7\.?\s*VERDICT(.*?)(?:JOB_SUMMARY|MATCH_LEVEL|$)",
                text, re.DOTALL | re.IGNORECASE,
            )
            if verdict_section:
                reasoning = verdict_section.group(1).strip()[:500]

            # Clean the trailing JOB_SUMMARY and MATCH_LEVEL lines from the full evaluation
            full_eval = re.sub(r"\n?JOB_SUMMARY:.*$", "", text, flags=re.DOTALL).strip()
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

    def deep_evaluate(self, job: JobListing, config: dict) -> str:
        """
        Perform a deep second-pass evaluation on a STRONG match job.
        Creates a separate evaluator using the deep_eval model config and
        generates a full application prep package with 10 sections.
        Returns a detailed markdown string.
        """
        deep_cfg = config.get("deep_eval", {})
        provider = deep_cfg.get("provider", "openrouter")
        model = deep_cfg.get("model", "anthropic/claude-sonnet-4.5")

        # Build a config dict for a one-off evaluator using the deep_eval model
        eval_config = dict(config)
        eval_config["llm_provider"] = provider
        if provider == "openrouter":
            eval_config["openrouter_model"] = model
        elif provider == "anthropic":
            eval_config["anthropic_model"] = model
        elif provider == "google_aistudio":
            eval_config["google_aistudio_model"] = model
        elif provider == "openai_compatible":
            eval_config["openai_compatible_model"] = model

        deep_evaluator = ResumeEvaluator(config=eval_config, resume_text=self.resume_text)
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

        prompt = f"""You are a senior technical recruiter with 15+ years of experience placing AV, broadcast, and live event engineers into permanent corporate roles. You've worked at firms like PRG, PSAV (now Encore), and Clair Global, and have deep relationships with hiring managers at major financial services firms and Fortune 500 pharma companies. You know exactly what makes a candidate stand out — and what gets a resume thrown in the "no" pile.

You are performing a DEEP evaluation of a job posting that has already been identified as a STRONG match for this candidate. Your job is to produce a complete application preparation package.

CANDIDATE RESUME:
{self.resume_text}

ADDITIONAL CONTEXT ABOUT THE CANDIDATE:
{self.candidate_context}

JOB POSTING:
{job_info}

---

Produce the following 10-section evaluation. Be thorough, specific, and actionable. Write as if you're personally coaching this candidate before they apply.

### 1. ROLE SUMMARY
- Company name, actual role (translate past any disguised titles — e.g., "Technology Delivery, VP" = Lead Audio Engineer), location, and compensation if listed
- Is this an in-house permanent role, a contract, or a staffed/embedded integrator position?
- On-site requirements (hybrid, fully on-site, remote) and any relocation implications
- Industry vertical (financial services, pharma, tech, education, entertainment, etc.)

### 2. MATCH SCORE
Rate the overall match on this scale:
- STRONG MATCH — Candidate meets 80%+ of requirements and experience is directly relevant
- MODERATE MATCH — Candidate meets 60-80% of requirements, with addressable gaps
- STRETCH — Candidate meets 40-60% of requirements, significant gaps but potentially worth pursuing
- WEAK MATCH — Below 40%, likely not worth the time to apply

### 3. REQUIREMENTS ALREADY MET
List each requirement from the posting alongside the specific line, bullet, or section of the resume that demonstrates it. Be precise — cite actual resume content.

### 4. REQUIREMENTS WITH EXPERIENCE BUT NOT HIGHLIGHTED
Things the candidate can likely do based on the full picture of the resume and context but that aren't explicitly stated or are buried. For each, suggest where and how to surface it in a tailored version.

### 5. TRUE GAPS
Requirements where the candidate genuinely lacks the qualification or experience. Be honest — don't stretch. For each gap, note:
- How critical it appears to be (dealbreaker vs. nice-to-have vs. learnable)
- Whether it's something that could realistically be developed quickly or addressed in a cover letter

### 6. RED FLAGS & LOGISTICS
- Location/relocation requirements and whether they're feasible given Chicago base
- Salary range (if listed) and whether it aligns with experience level
- Any requirements that suggest a different seniority level (too junior or too senior)
- ATS keywords from the posting that are missing from the resume
- Anything that seems off about the posting (vague requirements, unrealistic expectations, title/comp mismatch)

#### COMPENSATION & RELOCATION ANALYSIS
The candidate currently earns ~$85K/year freelancing in Chicago (Ravenswood). Use the relocation reference data below to perform a full financial and lifestyle comparison for any role outside Chicago. Show your math.
{self._city_profiles_str()}

### 7. VERDICT
Answer three questions directly:
1. **Should I apply?** Yes / Yes but temper expectations / Only if genuinely interested in this company / No
2. **Is it worth tailoring my resume?** Yes — significant tailoring needed / Light tailoring only / No — baseline resume is sufficient
3. **What's the single most important thing to change or add if tailoring?** One specific, actionable recommendation.

### 8. RESUME TAILORING
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

Provide at least 3-5 specific before/after rewrites.

### 9. COVER LETTER TALKING POINTS
Write 3-5 key talking points for the cover letter, framed in terms of "what would make me pick up the phone and call this candidate." For each point:
- The core message (one sentence)
- Why it matters to THIS employer specifically
- A suggested opening line or phrase the candidate could use

Think like a recruiter scanning 200 applications — what makes this one jump off the page?

### 10. INTERVIEW PREP
Based on this posting, prepare the candidate for the interview:
- **Likely technical questions** (5-7 specific questions they'll probably ask, based on the role requirements)
- **Behavioral/situational questions** (3-5 questions about experience, especially around any gaps or transitions)
- **Questions about the freelance-to-permanent transition** — how to frame this positively
- **Stories to prepare** — specific projects or experiences from the resume that map to this role's key requirements. Name the project/client and the talking point.
- **Questions to ASK the interviewer** — 3-5 smart questions that show domain knowledge and genuine interest

---

RULES:
- Begin your response directly with ### 1. ROLE SUMMARY — no preamble, no intro paragraph, no framing text.
- Be direct and brutally honest. This candidate can handle it.
- Don't inflate qualifications. If something is a gap, say so — then help them address it.
- Write as if you're personally preparing this candidate for a specific interview, not generating generic advice.
- Every suggestion should reference specific content from either the resume or the job posting.
- The resume tailoring section is the most important — make it specific enough that the candidate can make changes in 30 minutes."""

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
        if fetch_description and not job.description and job.url:
            job.description = fetch_job_description(job.url)
        return self.evaluate(job)

    def _load_eval_cache(self) -> dict:
        """Load eval cache — a persistent map of job_id -> evaluation results."""
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
        max_workers: int = 8,
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
            f"{supabase_url}/rest/v1/runs",
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
            records = [{
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
            } for j in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/jobs",
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
                f"{supabase_url}/rest/v1/run_jobs",
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
                target_locations, resume_file_path, resume_file_name}
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

        users = []
        for profile in profiles:
            uid = profile["user_id"]
            resume = resumes_by_user.get(uid)
            if not resume:
                log.info(f"Multi-user: skipping user {uid[:8]}… — no primary resume")
                continue
            users.append({
                "user_id": uid,
                "notify_email": profile.get("notify_email"),
                "candidate_context": profile.get("candidate_context"),
                "target_roles": profile.get("target_roles", []),
                "target_locations": profile.get("target_locations", []),
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
            f"{supabase_url}/rest/v1/runs",
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
                f"{supabase_url}/rest/v1/jobs",
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
                f"{supabase_url}/rest/v1/user_evaluations",
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
                f"{supabase_url}/rest/v1/run_jobs",
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

    console.print(f"\n[bold]Deep evaluation: {len(strong_jobs)} STRONG match(es)[/bold]")
    console.print(f"[dim]Provider: {deep_cfg.get('provider', 'openrouter')} | Model: {deep_cfg.get('model', 'anthropic/claude-sonnet-4.5')}[/dim]")

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
        result = evaluator.deep_evaluate(job, config)
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


def _set_eval_status(supabase_url: str, supabase_key: str, user_id: str, status: str, job_count: int = None):
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

    # 2. Fetch recent jobs in batches
    BATCH = 500
    offset = 0
    all_rows = []
    while True:
        resp = requests.get(
            f"{supabase_url}/rest/v1/jobs"
            f"?last_seen_date=gte.{cutoff}"
            f"&select=job_id,title,company,location,url,source,salary,date_posted,tier,date_scraped"
            f"&offset={offset}&limit={BATCH}",
            headers=headers, timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        all_rows.extend(batch)
        if len(batch) < BATCH:
            break
        offset += BATCH

    # 3. Filter out already-evaluated ones and convert to JobListing
    unevaluated = [r for r in all_rows if r["job_id"] not in already_evaluated]
    log.info(f"On-demand eval: {len(unevaluated)} new jobs to evaluate (of {len(all_rows)} recent)")

    jobs = []
    for r in unevaluated:
        j = JobListing(
            title=r["title"],
            company=r["company"],
            location=r["location"],
            url=r["url"],
            source=r["source"],
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

        # Build user-specific config — context is isolated per user
        user_config = dict(config)
        user_config["candidate_context"] = build_user_context(
            user, config_context=config.get("candidate_context", ""),
        )

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

        # Evaluate
        evaluator = ResumeEvaluator(config=user_config, resume_text=resume_text)
        evaluator.cache_path = SCRIPT_DIR / f"eval_cache_{user_id[:8]}.json"
        evaluated_jobs = evaluator.evaluate_batch(jobs, fetch_descriptions=True)

        # Sync results to user_evaluations
        scored = [j for j in evaluated_jobs if j.match_verdict]
        date_str = datetime.now().strftime("%Y-%m-%d")
        fake_metadata = {
            "date": date_str,
            "total_jobs": len(evaluated_jobs),
            "evaluated": len(scored),
            "verdicts": {},
        }
        for j in scored:
            v = j.match_verdict
            fake_metadata["verdicts"][v] = fake_metadata["verdicts"].get(v, 0) + 1

        # Only upsert user_evaluations (no new run record for on-demand)
        BATCH = 100
        headers = _supabase_headers(supabase_key)
        for i in range(0, len(scored), BATCH):
            batch = scored[i:i + BATCH]
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
                f"{supabase_url}/rest/v1/user_evaluations",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=eval_records, timeout=60,
            )
            resp.raise_for_status()

        console.print(f"\n[bold green]On-demand eval complete: {len(scored)} jobs scored for user {user_id[:8]}…[/bold green]")
        _set_eval_status(supabase_url, supabase_key, user_id, "completed", job_count=len(scored))

    except Exception as e:
        log.error(f"On-demand eval failed for {user_id[:8]}…: {e}")
        _set_eval_status(supabase_url, supabase_key, user_id, "error")


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
            from copy import deepcopy
            for user in users:
                console.print(f"\n[bold cyan]── User {user['user_id'][:8]}… ──[/bold cyan]")

                user_config = dict(config)
                # Build user-specific context — isolated per user, no config bleed
                user_config["candidate_context"] = build_user_context(
                    user, config_context=config.get("candidate_context", ""),
                )

                resume_path = download_resume_for_user(
                    config, user["user_id"],
                    user["resume_file_path"], user["resume_file_name"],
                )
                if not resume_path:
                    log.warning(f"Multi-user: skipping user {user['user_id'][:8]}… — resume download failed")
                    continue
                user_config["resume_path"] = str(resume_path)

                resume_text = load_resume(user_config)
                if not resume_text:
                    log.warning(f"Multi-user: skipping user {user['user_id'][:8]}… — could not read resume")
                    continue

                evaluator = ResumeEvaluator(config=user_config, resume_text=resume_text)
                evaluator.cache_path = SCRIPT_DIR / f"eval_cache_{user['user_id'][:8]}.json"
                user_jobs = evaluator.evaluate_batch(deepcopy(jobs), fetch_descriptions=True)
                user_new_ids = evaluator.new_job_ids

                user_verdict_counts: dict = {}
                for j in user_jobs:
                    v = j.match_verdict or "UNSCORED"
                    user_verdict_counts[v] = user_verdict_counts.get(v, 0) + 1

                user_metadata = {
                    **metadata,
                    "verdicts": user_verdict_counts,
                    "evaluated": len([j for j in user_jobs if j.match_verdict]),
                }
                sync_to_supabase_for_user(config, user_jobs, user["user_id"], user_new_ids, user_metadata)

                if not args.no_deep and not args.no_evaluate:
                    run_deep_evaluation(user_config, user_jobs)
                    sync_deep_evals_for_user(config, user_jobs, user["user_id"])
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
    1. Take 3 sample jobs (or use existing results)
    2. Run each model against all 3
    3. Save side-by-side comparisons
    4. Print a summary scorecard
    """
    # Models to benchmark — edit this list to test others.
    # Format: (model_id, display_name, approx_cost_per_1M_output_tokens)
    # Models to benchmark — edit this list to test others.
    # Format: (model_id, display_name, approx_cost_per_1M_output_tokens, provider_override)
    # provider_override: None = use OpenRouter, "google_aistudio" = use Google AI Studio direct
    BENCHMARK_MODELS = [
        ("google/gemini-3-flash-preview", "Gemini 3 Flash (OR)", 4.0, None),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", 2.0, None),
        ("x-ai/grok-4.1-fast", "Grok 4.1 Fast", 5.0, None),
        ("google/gemini-2.5-flash", "Gemini 2.5 Flash (OR)", 2.5, None),
        ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", 15.0, None),
        ("openai/gpt-oss-120b", "GPT-OSS 120B", 3.5, None),
    ]

    # If Google AI Studio key is set, add direct Gemini entries for comparison
    if config.get("google_aistudio_key"):
        BENCHMARK_MODELS.extend([
            ("gemini-3-flash-preview", "Gemini 3 Flash (AI Studio)", 0.0, "google_aistudio"),
            ("gemini-2.5-flash", "Gemini 2.5 Flash (AI Studio)", 0.0, "google_aistudio"),
        ])

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
    console.print(f"Testing {len(BENCHMARK_MODELS)} models × {len(sample_jobs)} jobs\n")

    results = {}  # model_id -> list of (job, evaluation_dict, elapsed_seconds)

    for model_id, model_name, cost_per_m, provider_override in BENCHMARK_MODELS:
        console.print(f"\n[bold]── {model_name} ({model_id}) ──[/bold]")

        # Create evaluator with this model, using the appropriate provider
        bench_config = dict(config)
        if provider_override == "google_aistudio":
            bench_config["llm_provider"] = "google_aistudio"
            bench_config["google_aistudio_model"] = model_id
        else:
            bench_config["llm_provider"] = "openrouter"
            bench_config["openrouter_model"] = model_id
        evaluator = ResumeEvaluator(config=bench_config, resume_text=resume_text)

        if not evaluator.client:
            console.print(f"  [red]Failed to initialize — skipping[/red]")
            continue

        model_results = []
        for i, job in enumerate(sample_jobs):
            console.print(f"  [{i+1}/{len(sample_jobs)}] {job.title} @ {job.company}...", end=" ")
            start = time.time()
            try:
                result = evaluator.evaluate(job)
                elapsed = time.time() - start
                model_results.append((job, result, elapsed))
                console.print(
                    f"{result['verdict'] or '???'} — {elapsed:.1f}s"
                )
            except Exception as e:
                elapsed = time.time() - start
                console.print(f"[red]ERROR: {e}[/red]")
                model_results.append((job, {
                    "score": 0, "verdict": "ERROR", "reasoning": str(e),
                    "full_evaluation": "",
                }, elapsed))
            time.sleep(1)  # Rate limiting between calls

        results[model_id] = (model_name, cost_per_m, model_results)

    # --- Generate comparison report ---
    _save_benchmark_report(results, sample_jobs)


def _get_benchmark_samples(config: dict) -> list[JobListing]:
    """
    Get sample jobs for benchmarking. Tries existing results first,
    then falls back to synthetic test cases that exercise different
    aspects of the evaluation.
    """
    # Try loading previous results
    previous = load_previous_results()
    if previous:
        # Pick a diverse sample: try to get one with description, varied sources
        with_desc = [j for j in previous if len(j.description) > 200]
        if len(with_desc) >= 3:
            console.print(f"Using {min(3, len(with_desc))} jobs from previous scan results")
            return with_desc[:3]

    # Synthetic test cases that exercise different evaluation dimensions
    console.print("No previous results found — using built-in test postings")
    return [
        JobListing(
            title="AV Engineer",
            company="Goldman Sachs",
            location="New York, NY",
            url="",
            source="benchmark",
            tier="Tier 2 — Finance",
            description="""
AV Engineer — Goldman Sachs — New York, NY

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

Salary: $95,000 - $125,000 + bonus
""",
        ),
        JobListing(
            title="Technology Delivery Analyst, VP",
            company="BlackRock",
            location="New York, NY",
            url="",
            source="benchmark",
            tier="Tier 2 — Finance",
            description="""
Technology Delivery Analyst, VP — BlackRock — New York

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

Compensation: $130,000 - $160,000 base + annual bonus
""",
        ),
        JobListing(
            title="Broadcast Systems Engineer",
            company="Netflix",
            location="Los Angeles, CA",
            url="",
            source="benchmark",
            tier="Tier 3 — Big Tech",
            description="""
Broadcast Systems Engineer — Netflix — Los Angeles, CA

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

Salary: $140,000 - $180,000
""",
        ),
    ]


def _save_benchmark_report(results: dict, sample_jobs: list[JobListing]):
    """Generate and save the benchmark comparison report."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    benchmark_dir = RESULTS_DIR / "benchmarks"
    benchmark_dir.mkdir(exist_ok=True)
    report_path = benchmark_dir / f"benchmark_{timestamp}.md"

    lines = [
        "# LLM Benchmark — Model Comparison",
        f"\n*Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}*\n",
    ]

    # Summary scorecard
    lines.append("## Summary Scorecard\n")
    lines.append("| Model | Avg Time | Format OK | Verdicts | Est. Cost/100 Jobs |")
    lines.append("|---|---|---|---|---|")

    for model_id, (model_name, cost_per_m, model_results) in results.items():
        if not model_results:
            continue

        avg_time = sum(r[2] for r in model_results) / len(model_results)

        # Check format compliance: did it produce all 7 sections?
        format_scores = []
        for _, result, _ in model_results:
            text = result.get("full_evaluation", "")
            sections_found = sum(1 for marker in [
                "ROLE SUMMARY", "MATCH SCORE", "REQUIREMENTS",
                "NOT HIGHLIGHTED", "TRUE GAPS", "RED FLAGS", "VERDICT"
            ] if marker.upper() in text.upper())
            format_scores.append(sections_found)
        avg_format = sum(format_scores) / len(format_scores)
        format_pct = f"{avg_format:.1f}/7"

        # Verdicts
        verdicts = [r.get("verdict", "???") for _, r, _ in model_results]
        verdict_str = " / ".join(verdicts)

        # Cost estimate (rough: ~2K input + ~1.5K output tokens per eval)
        est_cost_100 = (cost_per_m / 1_000_000) * 1500 * 100
        cost_str = f"~${est_cost_100:.2f}"

        lines.append(
            f"| {model_name} | {avg_time:.1f}s | {format_pct} | {verdict_str} | {cost_str} |"
        )

    # Detailed side-by-side for each sample job
    for i, job in enumerate(sample_jobs):
        lines.append(f"\n---\n## Job {i+1}: {job.title} @ {job.company}\n")

        for model_id, (model_name, _, model_results) in results.items():
            if i >= len(model_results):
                continue
            _, result, elapsed = model_results[i]

            lines.append(f"### {model_name}")
            lines.append(f"*Verdict: {result.get('verdict', '???')} | Time: {elapsed:.1f}s*\n")

            eval_text = result.get("full_evaluation", "(no output)")
            # Truncate very long outputs for readability
            if len(eval_text) > 3000:
                eval_text = eval_text[:3000] + "\n\n*[truncated for benchmark report]*"

            lines.append("<details><summary>Full evaluation</summary>\n")
            lines.append(eval_text)
            lines.append("\n</details>\n")

    # Evaluation criteria guide
    lines.append("\n---\n## How to Read This\n")
    lines.append("""When comparing models, look for:

1. **Format compliance** — Did the model produce all 7 sections? Models that skip sections or merge them are harder to parse programmatically.
2. **Verdict honesty** — The Netflix posting should be a STRETCH or WEAK match (broadcast studio focus, Pro Tools/Avid S6/Atmos/AES67 are genuine gaps). Models that rate it MODERATE or STRONG are inflating.
3. **Citation quality** — In section 3, does the model cite *specific* resume lines or just say "your experience covers this"?
4. **Gap honesty** — In section 5, does the model clearly distinguish dealbreakers from nice-to-haves? Does it acknowledge the broadcast studio gap honestly?
5. **Tailoring advice** — In section 7, is the recommendation specific and actionable, or generic?
6. **Title translation** — Does the model catch that "Technology Delivery Analyst, VP" is a disguised AV/audio role?

The BlackRock posting is designed to be a STRONG match. The Goldman posting should be MODERATE (Crestron/Extron gap). The Netflix posting should be STRETCH/WEAK (studio engineering is a different discipline). Models that get all three right are well-calibrated for your use case.""")

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
