#!/usr/bin/env python3
"""
Job Search Automation Pipeline
===============================
Scrapes job listings from multiple sources, deduplicates them,
and scores each against your resume using Claude.

Sources:
  1. SerpAPI (Google Jobs) — best aggregator, pulls from LinkedIn/Indeed/etc.
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
                    jobs = self.search(query, location)
                    all_jobs.extend(jobs)
                    time.sleep(1)  # Rate limiting

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

After the full evaluation, add a final line in exactly this format:
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

            # Extract a short reasoning from the verdict section
            reasoning = ""
            verdict_section = re.search(
                r"###?\s*7\.?\s*VERDICT(.*?)(?:MATCH_LEVEL|$)",
                text, re.DOTALL | re.IGNORECASE,
            )
            if verdict_section:
                reasoning = verdict_section.group(1).strip()[:500]

            # Clean the trailing MATCH_LEVEL line from the full evaluation
            full_eval = re.sub(r"\n?MATCH_LEVEL:.*$", "", text).strip()

            return {
                "score": score,
                "verdict": verdict,
                "reasoning": reasoning,
                "full_evaluation": full_eval,
            }

        except Exception as e:
            log.error(f"LLM evaluation error: {e}")
            return {
                "score": 0, "verdict": "", "reasoning": f"Evaluation failed: {e}",
                "full_evaluation": "",
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
- COMPENSATION & RELOCATION ANALYSIS: The candidate currently earns ~$85K/year freelancing in Chicago (Ravenswood). Use the relocation reference data below to perform a full financial and lifestyle comparison for any role outside Chicago. Show your math.
{self._city_profiles_str()}

### 7. VERDICT
Answer three questions directly:
1. **Should I apply?** Yes / Yes but temper expectations / Only if genuinely interested in this company / No
2. **Is it worth tailoring my resume?** Yes — significant tailoring needed / Light tailoring only / No — baseline resume is sufficient
3. **What's the single most important thing to change or add if tailoring?** One specific, actionable recommendation.

### 8. RESUME TAILORING
This is where you earn your fee. For each suggestion:
- Quote the EXISTING bullet point or section from the resume (use "> BEFORE:" formatting)
- Write the REWRITTEN version (use "> AFTER:" formatting)
- Explain WHY the change matters for this specific posting
- If a bullet point should be ADDED (not rewritten), mark it as "> ADD:" with the suggested placement

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

    @staticmethod
    def _load_eval_cache() -> dict:
        """Load previously evaluated job_ids from results/ directories.

        Scans existing .md evaluation files across all run dates and extracts
        the job_id from the filename pattern + header. Returns a dict mapping
        job_id -> {score, verdict, reasoning, full_evaluation}.
        """
        cache = {}
        for date_dir in RESULTS_DIR.iterdir():
            if not date_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}$", date_dir.name):
                continue
            for verdict_dir in date_dir.iterdir():
                if not verdict_dir.is_dir() or verdict_dir.name == "benchmarks":
                    continue
                verdict_name = verdict_dir.name.upper()
                if verdict_name not in ("STRONG", "MODERATE", "STRETCH", "WEAK"):
                    continue
                for md_file in verdict_dir.glob("*.md"):
                    if md_file.parent.name == "deep":
                        continue
                    try:
                        text = md_file.read_text()
                        lines = text.split("\n")
                        # Extract title, company from header "# Title — Company"
                        title = company = location = ""
                        for line in lines:
                            if line.startswith("# "):
                                parts = line[2:].split(" — ", 1)
                                title = parts[0].strip()
                                if len(parts) > 1:
                                    company = parts[1].strip()
                                break
                        for line in lines:
                            if line.startswith("**Location:**"):
                                location = line.split("**Location:**")[1].strip()
                                break
                        if not title or not company:
                            continue
                        # Reconstruct the job_id the same way JobListing does
                        norm_loc = JobListing._normalize_location(location)
                        raw = f"{title}|{company}|{norm_loc}".lower().strip()
                        job_id = hashlib.md5(raw.encode()).hexdigest()[:12]
                        # Extract the section between --- markers as full_evaluation
                        eval_start = text.find("---\n")
                        full_eval = text[eval_start + 4:].strip() if eval_start != -1 else ""
                        # Extract reasoning from section 2
                        reasoning = ""
                        in_sec = False
                        for line in lines:
                            if re.match(r"###\s*2\.", line):
                                in_sec = True
                                continue
                            if re.match(r"###\s*3\.", line):
                                break
                            if in_sec and line.strip():
                                reasoning += line.strip() + " "
                        # Extract score from verdict
                        score_map = {"STRONG": 85, "MODERATE": 65, "STRETCH": 50, "WEAK": 30}
                        cache[job_id] = {
                            "score": score_map.get(verdict_name, 0),
                            "verdict": verdict_name,
                            "reasoning": reasoning.strip()[:300],
                            "full_evaluation": full_eval,
                        }
                    except Exception:
                        continue
        return cache

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
# Main pipeline
# ---------------------------------------------------------------------------
def run_scrape(config: dict, quick: bool = False) -> list[JobListing]:
    """Run the scraping pipeline."""
    all_jobs = []

    # Source 1: SerpAPI (Google Jobs)
    serpapi_key = config.get("serpapi_key", "")
    if serpapi_key:
        scraper = SerpAPIScraper(
            api_key=serpapi_key,
            results_per_query=config["search"]["results_per_query"],
        )
        jobs = scraper.run_all_queries(config)
        all_jobs.extend(jobs)
    else:
        console.print("[yellow]⚠ SerpAPI key not set — skipping Google Jobs[/yellow]")
        console.print("  Get a free key at https://serpapi.com (100 searches/mo)")

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
        return jobs

    resume_text = load_resume(config)
    if not resume_text:
        console.print("[yellow]⚠ No resume found — skipping LLM evaluation[/yellow]")
        return jobs

    evaluator = ResumeEvaluator(config=config, resume_text=resume_text)
    return evaluator.evaluate_batch(jobs, fetch_descriptions=True)


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
    args = parser.parse_args()

    config = load_config()

    # Auto-cleanup results older than 30 days
    cleanup_old_results(max_age_days=30)

    console.print("[bold blue]═══════════════════════════════════════[/bold blue]")
    console.print("[bold blue]  Job Search Automation Pipeline[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════[/bold blue]\n")

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

    if not args.no_evaluate and jobs:
        jobs = run_evaluate(config, jobs)

    if jobs:
        json_path, csv_path, md_path = save_results(jobs)
        print_summary(jobs)
        console.print(f"\n[bold green]Results saved:[/bold green]")
        console.print(f"  📊 CSV:      {csv_path}")
        console.print(f"  📝 Markdown: {md_path}")
        console.print(f"  💾 Raw JSON: {json_path}")

        # Deep evaluation on STRONG matches
        if not args.no_deep and not args.no_evaluate:
            run_deep_evaluation(config, jobs)

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
        }
        metadata_path = SCRIPT_DIR / "run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        log.info(f"Run metadata saved to {metadata_path}")
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
