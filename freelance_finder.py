#!/usr/bin/env python3
"""
Freelance Prospect Finder
==========================
Discovers AV/audio companies that hire freelance A1 engineers, evaluates their
fit, and generates personalized cold outreach emails.

Companies found: AV rental houses, production companies, music venues,
touring operations, corporate AV departments, and universities.

Usage:
  python freelance_finder.py                          # Full run: discover + verify + evaluate
  python freelance_finder.py --discover-only          # Skip verification and LLM
  python freelance_finder.py --evaluate-only          # Re-run LLM on cached companies
  python freelance_finder.py --no-outreach            # Evaluate but skip email drafts
  python freelance_finder.py --no-verify              # Skip activity verification
  python freelance_finder.py --category av_rental     # One category only
  python freelance_finder.py --relationship all       # Include known partners in output
  python freelance_finder.py --min-tier hot           # Only draft outreach for HOT companies
  python freelance_finder.py --max-companies 50       # Cap discovery volume

Requirements:
  pip install requests pyyaml rich
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

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
        logging.FileHandler("freelance_finder.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("freelance_finder")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
FREELANCE_DIR = SCRIPT_DIR / "freelance"
FREELANCE_CACHE_PATH = SCRIPT_DIR / "freelance_cache.json"
CLIENTS_YAML_PATH = SCRIPT_DIR / "clients.yaml"

FREELANCE_DIR.mkdir(exist_ok=True)
(FREELANCE_DIR / "data").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Shared utilities (copied from job_scraper.py)
# ---------------------------------------------------------------------------
def _normalize_company(name: str) -> str:
    """Normalize company name for fuzzy dedup."""
    name = name.lower().strip()
    for suffix in [
        ", inc.", ", inc", " inc.", " inc", ", llc", " llc",
        ", ltd", " ltd", " corp.", " corp", " corporation",
        " company", " co.", " co", " careers", " jobs",
    ]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found: {CONFIG_PATH}[/red]")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Allow env vars to override config values
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

    # Role-specific legacy fallback for freelance_eval
    if role == "freelance_eval":
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
        return ""

    suffix = resume_path.suffix.lower()
    if suffix in (".txt", ".md"):
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
# Data model
# ---------------------------------------------------------------------------
@dataclass
class CompanyProfile:
    name: str
    city: str
    state: str
    website: str
    category: str       # "av_rental"|"production_co"|"venue"|"touring"|"corporate_av"|"university"
    source: str         # "serpapi_google" | "brightdata_google"
    search_query: str = ""
    description: str = ""
    phone: str = ""
    company_id: str = ""          # MD5(normalized_name|city)[:12], set in __post_init__
    date_discovered: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    # Relationship (from clients.yaml)
    relationship: str = "new_prospect"  # "known_partner"|"known_client"|"new_prospect"
    relationship_notes: str = ""

    # Activity verification fields
    recent_activity: str = ""
    scale_signals: str = ""
    notable_clients: str = ""
    gear_mentioned: str = ""

    # LLM evaluation
    fit_tier: str = ""            # "HOT"|"WARM"|"COLD"|"SKIP"
    fit_score: int = 0            # 0-100
    fit_reasoning: str = ""
    full_evaluation: str = ""
    outreach_draft: str = ""
    outreach_subject: str = ""

    def __post_init__(self):
        if not self.company_id:
            raw = f"{_normalize_company(self.name)}|{self.city.lower().strip()}"
            self.company_id = hashlib.md5(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Clients lookup
# ---------------------------------------------------------------------------
class ClientsLookup:
    """Loads clients.yaml and provides fuzzy name matching."""

    def __init__(self, path: Path):
        self._partners: dict = {}
        self._clients: dict = {}
        if not path.exists():
            log.warning(f"clients.yaml not found at {path} — skipping relationship lookup")
            return
        data = yaml.safe_load(path.read_text())
        self._partners = {
            _normalize_company(e["name"]): e
            for e in data.get("known_partners", [])
        }
        self._clients = {
            _normalize_company(e["name"]): e
            for e in data.get("known_clients", [])
        }

    def lookup(self, name: str, city: str) -> tuple[str, str]:
        key = _normalize_company(name)
        if key in self._partners:
            return "known_partner", self._partners[key].get("notes", "")
        if key in self._clients:
            return "known_client", self._clients[key].get("notes", "")
        return "new_prospect", ""


# ---------------------------------------------------------------------------
# Company discovery: SerpAPI regular web search
# ---------------------------------------------------------------------------
SKIP_DOMAINS = {
    "yelp.com", "linkedin.com", "indeed.com", "thumbtack.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "yellowpages.com", "bbb.org", "manta.com", "glassdoor.com",
    "ziprecruiter.com", "angi.com", "homeadvisor.com", "angieslist.com",
    # Contract AV operators — poor gear, locked contracts, not good freelance targets
    "encoreglobal.com", "psav.com",
}

# Snippet/description keywords that indicate a venue's AV is Encore/PSAV-managed.
# These companies lock hotels into contracts and are not desirable freelance clients.
BLOCKED_OPERATOR_KEYWORDS = {
    "encoreglobal.com", "psav.com",
    "encore event technologies", "encore productions",
    "powered by encore", "av by encore",
    "psav presentation services",
}


def _domain_from_url(url: str) -> str:
    """Extract base domain from URL."""
    m = re.search(r'https?://([^/]+)', url)
    if m:
        parts = m.group(1).split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
    return url


def _clean_company_name(title: str) -> str:
    """Strip everything after |, -, — separators in Google result titles."""
    for sep in [" | ", " - ", " — ", " – "]:
        if sep in title:
            title = title.split(sep)[0]
    return title.strip()


def _extract_location(text: str) -> tuple[str, str]:
    """Extract city, state from text using regex."""
    m = re.search(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s+([A-Z]{2})\b', text)
    if m:
        return m.group(1), m.group(2)
    return "", ""


class SerpAPIWebSearcher:
    """
    Uses SerpAPI with engine=google (regular web search, not Google Jobs).
    Parses organic_results to find company websites.
    """

    BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, results_per_query: int = 10):
        self.api_key = api_key
        self.results_per_query = results_per_query
        self._rate_limited = False

    def search(self, query: str, category: str) -> list[CompanyProfile]:
        params = {
            "engine": "google",
            "q": query,
            "gl": "us",
            "hl": "en",
            "num": self.results_per_query,
            "api_key": self.api_key,
        }
        try:
            log.info(f"SerpAPI web: '{query}'")
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

        companies = []

        # Check knowledge graph first (entity card for specific companies)
        kg = data.get("knowledge_graph", {})
        if kg and kg.get("title") and kg.get("website"):
            city, state = _extract_location(
                kg.get("description", "") + " " + kg.get("address", "")
            )
            if city or state:
                companies.append(CompanyProfile(
                    name=kg.get("title", ""),
                    city=city,
                    state=state,
                    website=kg.get("website", ""),
                    category=category,
                    source="serpapi_google",
                    search_query=query,
                    description=kg.get("description", ""),
                ))

        # Organic results
        for item in data.get("organic_results", []):
            url = item.get("link", "")
            domain = _domain_from_url(url)
            if any(skip in domain for skip in SKIP_DOMAINS):
                continue
            title = _clean_company_name(item.get("title", ""))
            snippet = item.get("snippet", "")
            combined_text = (title + " " + snippet + " " + url).lower()
            if any(kw in combined_text for kw in BLOCKED_OPERATOR_KEYWORDS):
                log.debug(f"Skipping Encore/PSAV managed result: {title}")
                continue
            city, state = _extract_location(snippet + " " + item.get("title", ""))
            if not title:
                continue
            companies.append(CompanyProfile(
                name=title,
                city=city,
                state=state,
                website=url,
                category=category,
                source="serpapi_google",
                search_query=query,
                description=snippet,
            ))

        log.info(f"  → Found {len(companies)} results")
        return companies

    def run_all_queries(
        self,
        config: dict,
        category_filter: Optional[str] = None,
        max_companies: int = 100,
        max_workers: int = 6,
    ) -> list[CompanyProfile]:
        freelance_cfg = config.get("freelance_search", {})
        query_groups = freelance_cfg.get("queries", {})
        self.results_per_query = freelance_cfg.get("results_per_query", 10)

        # Build flat list of (query, category) pairs
        tasks = [
            (query, cat)
            for cat, queries in query_groups.items()
            if not category_filter or cat == category_filter
            for query in queries
        ]

        all_companies: list[CompanyProfile] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(self.search, query, cat): (query, cat)
                for query, cat in tasks
            }
            for future in as_completed(future_to_task):
                if self._rate_limited:
                    log.warning("SerpAPI rate-limited — stopping queries")
                    break
                try:
                    all_companies.extend(future.result())
                except Exception as e:
                    log.error(f"Query error: {e}")
        return all_companies


# ---------------------------------------------------------------------------
# Company discovery: BrightData web search fallback
# ---------------------------------------------------------------------------
class BrightDataWebSearcher:
    """
    Fallback when SerpAPI is unavailable or rate-limited.
    Uses BrightData SERP API with regular Google search (not Google Jobs).
    """

    API_URL = "https://api.brightdata.com/request"

    def __init__(self, api_token: str, zone: str = "serp_api1", results_per_query: int = 10):
        self.api_token = api_token
        self.zone = zone
        self.results_per_query = results_per_query

    def _parse_html_results(self, html: str) -> list[dict]:
        """Parse Google organic results from raw HTML via BeautifulSoup."""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        # Each organic result sits in a <div class="g"> or similar container
        for div in soup.select("div.g, div[data-hveid]"):
            a = div.select_one("a[href]")
            if not a:
                continue
            href = a.get("href", "")
            if not href.startswith("http"):
                continue
            h3 = div.select_one("h3")
            title = h3.get_text(strip=True) if h3 else ""
            # Snippet: try multiple known selectors
            snippet_el = div.select_one("div.VwiC3b, span.st, div[data-sncf], div.s")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if title and href:
                results.append({"title": title, "link": href, "snippet": snippet})
        return results

    def search(self, query: str, category: str) -> list[CompanyProfile]:
        clean_query = query.replace('" OR "', " ").replace('"', "").strip()
        # Regular Google search — no ibp=htl;jobs (that's only for Google Jobs)
        google_url = (
            f"https://www.google.com/search"
            f"?q={requests.utils.quote(clean_query)}"
            f"&gl=us&hl=en&num={self.results_per_query}"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        payload = {"zone": self.zone, "url": google_url, "format": "raw"}

        try:
            log.info(f"BrightData web: '{query}'")
            resp = requests.post(self.API_URL, headers=headers, json=payload, timeout=90)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"BrightData error: {e}")
            return []

        # BrightData returns raw HTML for regular Google search — parse it
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            try:
                data = resp.json()
                # BrightData SERP zone returns "organic" (not "organic_results")
                raw_results = data.get("organic", data.get("organic_results", []))
            except Exception:
                raw_results = []
        else:
            # Raw HTML fallback — parse with BeautifulSoup
            raw_results = self._parse_html_results(resp.text)

        companies = []
        for item in raw_results:
            url = item.get("link", "")
            domain = _domain_from_url(url)
            if any(skip in domain for skip in SKIP_DOMAINS):
                continue
            title = _clean_company_name(item.get("title", ""))
            snippet = item.get("snippet", "")
            combined_text = (title + " " + snippet + " " + url).lower()
            if any(kw in combined_text for kw in BLOCKED_OPERATOR_KEYWORDS):
                log.debug(f"Skipping Encore/PSAV managed result: {title}")
                continue
            city, state = _extract_location(snippet + " " + title)
            if not title:
                continue
            companies.append(CompanyProfile(
                name=title,
                city=city,
                state=state,
                website=url,
                category=category,
                source="brightdata_google",
                search_query=query,
                description=snippet,
            ))

        log.info(f"  → Found {len(companies)} results")
        return companies

    def run_all_queries(
        self,
        config: dict,
        category_filter: Optional[str] = None,
        max_companies: int = 100,
        max_workers: int = 6,
    ) -> list[CompanyProfile]:
        freelance_cfg = config.get("freelance_search", {})
        query_groups = freelance_cfg.get("queries", {})
        self.results_per_query = freelance_cfg.get("results_per_query", 10)

        tasks = [
            (query, cat)
            for cat, queries in query_groups.items()
            if not category_filter or cat == category_filter
            for query in queries
        ]

        all_companies: list[CompanyProfile] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(self.search, query, cat): (query, cat)
                for query, cat in tasks
            }
            for future in as_completed(future_to_task):
                try:
                    all_companies.extend(future.result())
                except Exception as e:
                    log.error(f"Query error: {e}")
        return all_companies


# ---------------------------------------------------------------------------
# Activity verifier
# ---------------------------------------------------------------------------
class ActivityVerifier:
    """
    Runs one search per company to populate research fields:
    recent_activity, scale_signals, notable_clients, gear_mentioned.
    """

    BASE_URL = "https://serpapi.com/search.json"

    def __init__(
        self,
        api_key: str = "",
        brightdata_token: str = "",
        brightdata_zone: str = "serp_api1",
    ):
        self.api_key = api_key
        self.brightdata_token = brightdata_token
        self.brightdata_zone = brightdata_zone

    def _search_serpapi(self, query: str) -> list[dict]:
        params = {
            "engine": "google",
            "q": query,
            "gl": "us",
            "hl": "en",
            "num": 5,
            "api_key": self.api_key,
        }
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=30)
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            return resp.json().get("organic_results", [])
        except Exception as e:
            log.debug(f"Verify search error: {e}")
            return []

    def _search_brightdata(self, query: str) -> list[dict]:
        google_url = (
            f"https://www.google.com/search"
            f"?q={requests.utils.quote(query)}"
            f"&gl=us&hl=en&num=5"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.brightdata_token}",
        }
        payload = {"zone": self.brightdata_zone, "url": google_url, "format": "raw"}
        try:
            resp = requests.post(
                "https://api.brightdata.com/request",
                headers=headers, json=payload, timeout=90,
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                return resp.json().get("organic_results", [])
            # Raw HTML — parse with BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for div in soup.select("div.g, div[data-hveid]"):
                a = div.select_one("a[href]")
                if not a or not a.get("href", "").startswith("http"):
                    continue
                h3 = div.select_one("h3")
                snippet_el = div.select_one("div.VwiC3b, span.st, div[data-sncf]")
                results.append({
                    "title": h3.get_text(strip=True) if h3 else "",
                    "link": a["href"],
                    "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
                    "date": "",
                })
            return results
        except Exception as e:
            log.debug(f"BrightData verify error: {e}")
            return []

    def _search(self, query: str) -> list[dict]:
        if self.api_key:
            results = self._search_serpapi(query)
            if results:
                return results
        if self.brightdata_token:
            return self._search_brightdata(query)
        return []

    def _extract_activity(self, results: list[dict]) -> str:
        """Pull recent event/news snippets from search results."""
        snippets = []
        for item in results[:5]:
            snippet = item.get("snippet", "")
            date = item.get("date", "")
            if date:
                snippet = f"[{date}] {snippet}"
            if snippet:
                snippets.append(snippet)
        return " | ".join(snippets[:3])

    def _extract_scale_signals(self, results: list[dict]) -> str:
        """Look for inventory size, employee count, event scale evidence."""
        scale_keywords = [
            "employees", "staff", "inventory", "trucks", "fleet",
            "capacity", "seats", "K2", "K3", "d&b", "L-Acoustics",
            "Meyer Sound", "nationwide", "national", "international",
        ]
        found = []
        for item in results[:5]:
            snippet = item.get("snippet", "")
            for kw in scale_keywords:
                if kw.lower() in snippet.lower():
                    for s in snippet.split("."):
                        if kw.lower() in s.lower():
                            found.append(s.strip())
                            break
        return " | ".join(found[:3])

    def _extract_notable_clients(self, results: list[dict]) -> str:
        """Look for references to well-known clients or event types."""
        client_keywords = [
            "Fortune 500", "corporate", "concert", "festival", "tour",
            "arena", "stadium", "convention", "conference", "keynote",
        ]
        found = []
        for item in results[:5]:
            snippet = item.get("snippet", "")
            for kw in client_keywords:
                if kw.lower() in snippet.lower():
                    for s in snippet.split("."):
                        if kw.lower() in s.lower():
                            found.append(s.strip())
                            break
        return " | ".join(found[:2])

    def _extract_gear(self, results: list[dict]) -> str:
        """Extract audio gear brand mentions."""
        gear_brands = [
            "L-Acoustics", "d&b audiotechnik", "d&b", "Meyer Sound",
            "DiGiCo", "Yamaha", "Allen & Heath", "SSL", "Avid",
            "Shure", "Sennheiser", "RF", "IEM", "K2", "K3", "KS28",
            "QLab", "Dante", "AVB", "Waves",
        ]
        found = set()
        for item in results[:5]:
            text = (item.get("snippet", "") + " " + item.get("title", "")).lower()
            for brand in gear_brands:
                if brand.lower() in text:
                    found.add(brand)
        return ", ".join(sorted(found))

    def verify(self, company: CompanyProfile) -> CompanyProfile:
        """Run a verification search for one company and populate research fields."""
        query = f'"{company.name}" {company.city} events audio 2024 OR 2025 OR 2026'
        results = self._search(query)
        company.recent_activity = self._extract_activity(results)
        company.scale_signals = self._extract_scale_signals(results)
        company.notable_clients = self._extract_notable_clients(results)
        company.gear_mentioned = self._extract_gear(results)
        return company

    def verify_batch(
        self, companies: list[CompanyProfile], max_workers: int = 8,
    ) -> list[CompanyProfile]:
        """Verify companies concurrently."""
        if not self.api_key and not self.brightdata_token:
            log.warning("No search API key for activity verification — skipping")
            return companies

        console.print(f"\n[bold]Verifying {len(companies)} companies...[/bold]")
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_co = {executor.submit(self.verify, co): co for co in companies}
            completed = 0
            for future in as_completed(future_to_co):
                completed += 1
                try:
                    co = future.result()
                    results.append(co)
                    console.print(
                        f"  [{completed}/{len(companies)}] {co.name} ({co.city}) — "
                        f"gear: {co.gear_mentioned[:40] or 'none found'}"
                    )
                except Exception as e:
                    co = future_to_co[future]
                    log.error(f"Verification failed for {co.name}: {e}")
                    results.append(co)
        return results


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def deduplicate_companies(companies: list[CompanyProfile]) -> list[CompanyProfile]:
    """Remove duplicate companies: exact company_id, then fuzzy name+state."""
    # Pass 1: exact company_id dedup (keep longer description)
    seen: dict[str, CompanyProfile] = {}
    for co in companies:
        if co.company_id not in seen:
            seen[co.company_id] = co
        else:
            existing = seen[co.company_id]
            if len(co.description) > len(existing.description):
                seen[co.company_id] = co

    exact_deduped = list(seen.values())
    exact_count = len(companies) - len(exact_deduped)

    # Pass 2: fuzzy — key (normalized_name, state) catches multi-location companies
    # and slight name variations ("TC Furlong" vs "TC Furlong Inc.")
    fuzzy_groups: dict[tuple, list[CompanyProfile]] = {}
    for co in exact_deduped:
        key = (_normalize_company(co.name), co.state.upper())
        fuzzy_groups.setdefault(key, []).append(co)

    final = []
    fuzzy_merged = 0
    for key, group in fuzzy_groups.items():
        if len(group) == 1 or not key[0]:
            final.extend(group)
            continue
        # Keep the entry with the longest description
        best = max(group, key=lambda c: len(c.description))
        final.append(best)
        fuzzy_merged += len(group) - 1

    log.info(
        f"Deduplicated: {len(companies)} → {len(final)} unique companies "
        f"({exact_count} exact, {fuzzy_merged} fuzzy)"
    )
    return final


# ---------------------------------------------------------------------------
# LLM evaluation
# ---------------------------------------------------------------------------
class CompanyEvaluator:
    """
    Uses an LLM to evaluate each company's fit and generate cold outreach emails.
    Supports OpenRouter, Anthropic, Google AI Studio, OpenAI-compatible endpoints.
    Defaults to google_aistudio / gemini-2.5-flash for cost efficiency.
    """

    def __init__(self, config: dict, resume_text: str):
        self.resume_text = resume_text
        self.candidate_context = config.get("candidate_context", "")
        self.client = None

        self.provider, self.model = resolve_model(config, "freelance_eval")

        if self.provider == "openrouter":
            api_key = config.get("openrouter_key", "")
            if not api_key:
                log.warning("OpenRouter key not set")
                return
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
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

    def _call_llm(self, prompt: str) -> str:
        """Send a prompt to the configured LLM and return the response text."""
        if not self.client:
            return ""
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
                config={"max_output_tokens": 4000, "temperature": 0.5},
            )
            return response.text.strip()
        else:
            # OpenRouter and OpenAI-compatible both use the OpenAI SDK
            extra_headers = {}
            if self.provider == "openrouter":
                extra_headers = {
                    "HTTP-Referer": "https://github.com/job-scraper",
                    "X-Title": "Freelance Finder",
                }
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
                extra_headers=extra_headers,
            )
            return response.choices[0].message.content.strip()

    def evaluate_company(self, company: CompanyProfile) -> dict:
        """Evaluate a company's fit for freelance A1 work."""
        if not self.client or not self.resume_text:
            return {"fit_tier": "", "fit_score": 0, "fit_reasoning": "", "full_evaluation": ""}

        prompt = f"""You are evaluating potential freelance clients for an experienced A1 audio engineer based in Chicago, IL (near O'Hare — easy travel for national gigs).

ENGINEER'S RESUME:
{self.resume_text}

ADDITIONAL CONTEXT:
{self.candidate_context}

COMPANY TO EVALUATE:
Name: {company.name}
Category: {company.category}
Location: {company.city}, {company.state}
Website: {company.website}
Description: {company.description}
Relationship: {company.relationship}
Recent Activity: {company.recent_activity or "Not found"}
Scale Signals: {company.scale_signals or "Not found"}
Notable Clients: {company.notable_clients or "Not found"}
Gear Mentioned: {company.gear_mentioned or "Not found"}

EVALUATION TASK:
Evaluate this company as a potential freelance client for day calls and multi-day gigs. Consider:
1. Company type and event scale (local/regional/national)
2. Geographic fit — Chicago-based, but travel-ready via O'Hare
3. Scale fit — do they do events large enough to need an A1 of Eric's caliber?
4. Work-type fit — live corporate events, touring, AV rental, concert production?
5. Gear fit — do they use L-Acoustics, d&b, DiGiCo, or other gear Eric knows?
6. "Why They Would Want Eric" — cite specific resume bullets
7. Red flags (too small, wrong market, defunct, etc.)

If relationship is "known_partner" — this is a company Eric already works with. Rate as SKIP and note the existing relationship.
If relationship is "known_client" — this is a direct end client (corporate). Note the relationship and evaluate normally.
If the company's AV services appear to be managed or operated by Encore (formerly PSAV) — e.g., the contact is an Encore/PSAV employee, the website is encoreglobal.com or psav.com, or the description indicates Encore is the contracted AV provider — rate as SKIP. Encore/PSAV are contract-locked hotel AV operators with poor gear maintenance and are not viable freelance targets.

Format your response as:

## Company Assessment
[2-3 paragraph analysis]

## Why They Would Want Eric
- [bullet]
- [bullet]

## Potential Red Flags
- [bullet or "None identified"]

## Geographic Fit
[1-2 sentences on travel logistics]

## Gear Alignment
[1-2 sentences on known gear overlap]

ACTUAL_COMPANY_NAME: [the real company name — NOT a page title like "About Us", "Careers", "Contact", etc. Extract the real business name from the website/description]
FIT_TIER: [HOT|WARM|COLD|SKIP]
FIT_SCORE: [0-100]
FIT_SUMMARY: [1-2 sentence summary for the report]"""

        try:
            response = self._call_llm(prompt)
        except Exception as e:
            log.error(f"LLM error evaluating {company.name}: {e}")
            return {"fit_tier": "", "fit_score": 0, "fit_reasoning": "", "full_evaluation": ""}

        fit_tier = ""
        fit_score = 0
        fit_reasoning = ""
        actual_name = ""

        name_match = re.search(r'ACTUAL_COMPANY_NAME:\s*(.+?)(?:\n|$)', response)
        if name_match:
            actual_name = name_match.group(1).strip()

        tier_match = re.search(r'FIT_TIER:\s*(HOT|WARM|COLD|SKIP)', response)
        if tier_match:
            fit_tier = tier_match.group(1)

        score_match = re.search(r'FIT_SCORE:\s*(\d+)', response)
        if score_match:
            fit_score = int(score_match.group(1))

        summary_match = re.search(r'FIT_SUMMARY:\s*(.+?)(?:\n|$)', response)
        if summary_match:
            fit_reasoning = summary_match.group(1).strip()

        return {
            "fit_tier": fit_tier,
            "fit_score": fit_score,
            "fit_reasoning": fit_reasoning,
            "full_evaluation": response,
            "actual_name": actual_name,
        }

    def generate_outreach(self, company: CompanyProfile) -> dict:
        """Generate a personalized cold outreach email for HOT/WARM companies."""
        if not self.client:
            return {"outreach_draft": "", "outreach_subject": ""}

        prompt = f"""Write a cold outreach email from Eric Weiss (freelance A1 audio engineer, Chicago) to {company.name}.

COMPANY INFO:
Name: {company.name}
Category: {company.category}
Location: {company.city}, {company.state}
Website: {company.website}
Description: {company.description}
Recent Activity: {company.recent_activity or "N/A"}
Gear Mentioned: {company.gear_mentioned or "N/A"}

ERIC'S BACKGROUND (for tone/content):
- Chicago-based A1 / RF Coordinator, O'Hare adjacent — easy travel for national gigs
- 10+ years live corporate events (JP Morgan, AbbVie, Nike, Goldman Sachs, etc.)
- L-Acoustics certified, Yamaha/Allen & Heath console specialist
- RF coordination expertise (Shure/Sennheiser IEM and wireless mic systems)
- Familiar with Dante/AVB networked audio
- Available for day calls, multi-day corporate events, and touring

EMAIL REQUIREMENTS:
- 4-6 sentences ONLY — peer-to-peer tone, not applicant-sounding
- MUST reference 1 specific thing about this company (their gear, a recent event they did, their specialty, their market)
- Do NOT say "I came across your company" or "I noticed" — be direct
- Do NOT sound like a job application — this is one professional reaching out to another
- End with: "— Eric"
- After the em dash, add the full signature block on a new line:
  Eric Weiss | A1 / RF Coordinator | Chicago, IL (O'Hare adjacent — easy travel)
  edweiss412@gmail.com | 508-404-4496 | linkedin.com/in/edweiss412

Format your response as:
[Email body here]

SUBJECT: [subject line here]"""

        try:
            response = self._call_llm(prompt)
        except Exception as e:
            log.error(f"LLM error generating outreach for {company.name}: {e}")
            return {"outreach_draft": "", "outreach_subject": ""}

        subject = ""
        subject_match = re.search(r'SUBJECT:\s*(.+?)(?:\n|$)', response)
        if subject_match:
            subject = subject_match.group(1).strip()
            email_body = response[:response.rfind("SUBJECT:")].strip()
        else:
            email_body = response

        return {"outreach_draft": email_body, "outreach_subject": subject}

    def evaluate_batch(
        self,
        companies: list[CompanyProfile],
        generate_outreach: bool = True,
        outreach_min_tier: str = "warm",
        max_workers: int = 8,
    ) -> list[CompanyProfile]:
        """Evaluate companies concurrently with persistent caching."""
        # Load cache
        cache: dict = {}
        if FREELANCE_CACHE_PATH.exists():
            try:
                with open(FREELANCE_CACHE_PATH) as f:
                    cache = json.load(f)
            except Exception as e:
                log.warning(f"Failed to load freelance cache: {e}")

        cached_cos = []
        new_cos = []
        for co in companies:
            if co.company_id in cache:
                cached = cache[co.company_id]
                co.fit_tier = cached.get("fit_tier", "")
                co.fit_score = cached.get("fit_score", 0)
                co.fit_reasoning = cached.get("fit_reasoning", "")
                co.full_evaluation = cached.get("full_evaluation", "")
                co.outreach_draft = cached.get("outreach_draft", "")
                co.outreach_subject = cached.get("outreach_subject", "")
                cached_cos.append(co)
            else:
                new_cos.append(co)

        total_new = len(new_cos)
        total_cached = len(cached_cos)
        console.print(f"\n[bold]Evaluating {total_new} new companies...[/bold]")
        if total_cached:
            console.print(f"[dim]Skipping {total_cached} previously evaluated (cached)[/dim]")
        console.print(f"[dim]Provider: {self.provider} | Model: {self.model}[/dim]")

        tier_style = {"HOT": "red bold", "WARM": "yellow", "COLD": "dim", "SKIP": "dim"}
        tier_order = {"hot": 0, "warm": 1, "cold": 2, "skip": 3}
        min_tier_val = tier_order.get(outreach_min_tier.lower(), 1)

        def _evaluate_one(co: CompanyProfile) -> CompanyProfile:
            # Known partners are auto-tagged SKIP — no LLM call needed
            if co.relationship == "known_partner":
                co.fit_tier = "SKIP"
                co.fit_score = 0
                co.fit_reasoning = "Existing partner — already in rotation"
                co.full_evaluation = "Known partner — no cold outreach needed."
                return co

            result = self.evaluate_company(co)
            co.fit_tier = result["fit_tier"]
            co.fit_score = result["fit_score"]
            co.fit_reasoning = result["fit_reasoning"]
            co.full_evaluation = result["full_evaluation"]

            # Apply corrected company name from LLM if it differs
            actual_name = result.get("actual_name", "")
            if actual_name and actual_name.lower() != co.name.lower():
                old_name = co.name
                co.name = actual_name
                raw = f"{_normalize_company(co.name)}|{co.city.lower().strip()}"
                co.company_id = hashlib.md5(raw.encode()).hexdigest()[:12]
                log.info(f"Name corrected: '{old_name}' → '{co.name}'")

            # Generate outreach if tier qualifies
            if generate_outreach and co.fit_tier and co.fit_tier != "SKIP":
                co_tier_val = tier_order.get(co.fit_tier.lower(), 3)
                if co_tier_val <= min_tier_val:
                    outreach = self.generate_outreach(co)
                    co.outreach_draft = outreach["outreach_draft"]
                    co.outreach_subject = outreach["outreach_subject"]

            return co

        completed = 0
        if new_cos:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_co = {executor.submit(_evaluate_one, co): co for co in new_cos}
                for future in as_completed(future_to_co):
                    completed += 1
                    try:
                        co = future.result()
                        style = tier_style.get(co.fit_tier, "white")
                        console.print(
                            f"  [{completed}/{total_new}] {co.name} ({co.city})... "
                            f"[{style}]{co.fit_tier} ({co.fit_score})[/{style}]"
                        )
                    except Exception as e:
                        co = future_to_co[future]
                        log.error(f"Evaluation failed for {co.name}: {e}")

        # Save updated cache
        for co in new_cos:
            if co.fit_tier:
                cache[co.company_id] = {
                    "fit_tier": co.fit_tier,
                    "fit_score": co.fit_score,
                    "fit_reasoning": co.fit_reasoning,
                    "full_evaluation": co.full_evaluation,
                    "outreach_draft": co.outreach_draft,
                    "outreach_subject": co.outreach_subject,
                }
        with open(FREELANCE_CACHE_PATH, "w") as f:
            json.dump(cache, f, separators=(",", ":"))
        log.info(f"Freelance cache saved: {len(cache)} entries")

        return cached_cos + new_cos


# ---------------------------------------------------------------------------
# Output and reporting
# ---------------------------------------------------------------------------
def save_freelance_results(companies: list[CompanyProfile]):
    """Save results to JSON snapshot, CSV, and per-tier markdown files."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    run_dir = FREELANCE_DIR / date_str
    run_dir.mkdir(parents=True, exist_ok=True)

    # Raw JSON snapshot
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = FREELANCE_DIR / "data" / f"freelance_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump([asdict(co) for co in companies], f, indent=2, default=str)
    log.info(f"Saved {len(companies)} companies to {json_path}")

    # CSV
    csv_path = run_dir / "summary.csv"
    with open(csv_path, "w") as f:
        headers = [
            "fit_tier", "fit_score", "name", "city", "state", "category",
            "relationship", "website", "fit_reasoning", "gear_mentioned",
        ]
        f.write(",".join(headers) + "\n")
        for co in sorted(companies, key=lambda c: c.fit_score, reverse=True):
            row = [
                f'"{co.fit_tier}"',
                str(co.fit_score),
                f'"{co.name}"',
                f'"{co.city}"',
                f'"{co.state}"',
                f'"{co.category}"',
                f'"{co.relationship}"',
                co.website,
                f'"{co.fit_reasoning[:200] if co.fit_reasoning else ""}"',
                f'"{co.gear_mentioned[:100] if co.gear_mentioned else ""}"',
            ]
            f.write(",".join(row) + "\n")
    log.info(f"Saved CSV to {csv_path}")

    # Per-company markdown files organized by tier
    tier_dirs = {
        "HOT": run_dir / "hot",
        "WARM": run_dir / "warm",
        "COLD": run_dir / "cold",
    }
    evaluated = [co for co in companies if co.fit_tier and co.fit_tier != "SKIP"]
    for tier_name, tier_dir in tier_dirs.items():
        tier_cos = [co for co in evaluated if co.fit_tier == tier_name]
        if tier_cos:
            tier_dir.mkdir(exist_ok=True)
            for co in tier_cos:
                safe_name = re.sub(r'[^\w\-]', '_', f"{co.name}_{co.city}")[:80]
                md_path = tier_dir / f"{safe_name}.md"
                with open(md_path, "w") as f:
                    f.write(f"# {co.name} — {co.city}, {co.state}\n\n")
                    f.write(
                        f"**Category:** {co.category.replace('_', ' ').title()} | "
                        f"**Website:** {co.website}\n"
                    )
                    f.write(
                        f"**Relationship:** {co.relationship} | "
                        f"**Discovered:** {co.date_discovered}\n"
                    )
                    if co.gear_mentioned:
                        f.write(f"**Gear:** {co.gear_mentioned}\n")
                    f.write("\n---\n\n")
                    if co.full_evaluation:
                        f.write("## Company Evaluation\n\n")
                        f.write(co.full_evaluation + "\n\n")
                    if co.outreach_draft:
                        f.write("---\n\n## Cold Outreach Draft\n\n")
                        if co.outreach_subject:
                            f.write(f"**SUBJECT:** {co.outreach_subject}\n\n")
                        f.write(co.outreach_draft + "\n")
            log.info(f"Saved {len(tier_cos)} {tier_name} company files to {tier_dir}/")

    # Summary markdown
    md_path = run_dir / "summary.md"
    generate_freelance_report(companies, md_path)

    return json_path, csv_path, md_path


def generate_freelance_report(companies: list[CompanyProfile], path: Path):
    """Generate a ranked summary markdown report."""
    sorted_cos = sorted(companies, key=lambda c: c.fit_score, reverse=True)
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    hot = [c for c in sorted_cos if c.fit_tier == "HOT"]
    warm = [c for c in sorted_cos if c.fit_tier == "WARM"]
    cold = [c for c in sorted_cos if c.fit_tier == "COLD"]
    known_partners = [c for c in sorted_cos if c.relationship == "known_partner"]

    lines = [
        f"# Freelance Prospect Report — {timestamp}",
        f"\n**Total companies:** {len(companies)} | "
        f"**HOT:** {len(hot)} | **WARM:** {len(warm)} | **COLD:** {len(cold)}",
        "",
    ]

    if hot:
        lines.append(f"## HOT PROSPECTS ({len(hot)})\n")
        for co in hot:
            lines.append(f"### {co.name} — {co.city}, {co.state}")
            lines.append(f"**Category:** {co.category} | **Score:** {co.fit_score}/100")
            lines.append(f"Website: {co.website}")
            if co.gear_mentioned:
                lines.append(f"**Gear:** {co.gear_mentioned}")
            if co.fit_reasoning:
                lines.append(f"\n> {co.fit_reasoning}")
            if co.outreach_subject:
                lines.append(f"\n**Draft subject:** {co.outreach_subject}")
            lines.append("---")

    if warm:
        lines.append(f"\n## WARM PROSPECTS ({len(warm)})\n")
        for co in warm:
            lines.append(f"### {co.name} — {co.city}, {co.state}")
            lines.append(f"**Category:** {co.category} | **Score:** {co.fit_score}/100")
            lines.append(f"Website: {co.website}")
            if co.fit_reasoning:
                lines.append(f"\n> {co.fit_reasoning}")
            lines.append("---")

    if cold:
        lines.append(f"\n## COLD ({len(cold)})\n")
        for co in cold:
            lines.append(
                f"- **{co.name}** ({co.city}, {co.state}) — "
                f"{co.category} — {co.website}"
            )

    if known_partners:
        lines.append(f"\n## Known Partners ({len(known_partners)}) — Already in Rotation\n")
        for co in known_partners:
            notes = f" — {co.relationship_notes}" if co.relationship_notes else ""
            lines.append(f"- **{co.name}** ({co.city}, {co.state}){notes}")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    log.info(f"Saved summary report to {path}")


def load_previous_companies() -> list[CompanyProfile]:
    """Load the most recent freelance JSON snapshot."""
    data_dir = FREELANCE_DIR / "data"
    json_files = sorted(data_dir.glob("freelance_*.json"), reverse=True)
    if not json_files:
        return []
    with open(json_files[0]) as f:
        data = json.load(f)
    return [CompanyProfile(**d) for d in data]


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
def run_discover(
    config: dict,
    category_filter: Optional[str] = None,
    max_companies: int = 100,
) -> list[CompanyProfile]:
    """Discover companies via SerpAPI → BrightData fallback."""
    serpapi_key = config.get("serpapi_key", "")
    brightdata_token = config.get("brightdata_api_token", "")
    brightdata_zone = config.get("brightdata_zone", "serp_api1")
    use_brightdata = False
    all_companies = []

    if serpapi_key:
        searcher = SerpAPIWebSearcher(api_key=serpapi_key)
        companies = searcher.run_all_queries(config, category_filter, max_companies)
        if searcher._rate_limited and brightdata_token:
            console.print("[yellow]⚠ SerpAPI quota exhausted — falling back to BrightData[/yellow]")
            use_brightdata = True
        else:
            all_companies.extend(companies)

    if (not serpapi_key or use_brightdata) and brightdata_token:
        searcher = BrightDataWebSearcher(
            api_token=brightdata_token,
            zone=brightdata_zone,
        )
        all_companies.extend(
            searcher.run_all_queries(config, category_filter, max_companies)
        )
    elif not serpapi_key and not brightdata_token:
        console.print("[yellow]⚠ No search API key — skipping company discovery[/yellow]")
        console.print("  Set SERPAPI_KEY or BRIGHTDATA_API_TOKEN env var")

    console.print(f"\n[bold]Discovered {len(all_companies)} companies before deduplication[/bold]")
    return all_companies


def run_verify(companies: list[CompanyProfile], config: dict) -> list[CompanyProfile]:
    """Run activity verification for all companies."""
    verifier = ActivityVerifier(
        api_key=config.get("serpapi_key", ""),
        brightdata_token=config.get("brightdata_api_token", ""),
        brightdata_zone=config.get("brightdata_zone", "serp_api1"),
    )
    return verifier.verify_batch(companies)


def run_evaluate_companies(
    companies: list[CompanyProfile],
    config: dict,
    resume_text: str,
    no_outreach: bool = False,
    outreach_min_tier: str = "warm",
) -> list[CompanyProfile]:
    """Run LLM evaluation on all companies."""
    evaluator = CompanyEvaluator(config=config, resume_text=resume_text)
    if not evaluator.client:
        console.print("[red]No LLM client configured — skipping evaluation[/red]")
        return companies
    return evaluator.evaluate_batch(
        companies,
        generate_outreach=not no_outreach,
        outreach_min_tier=outreach_min_tier,
    )


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------
def print_freelance_summary(companies: list[CompanyProfile]):
    """Print a ranked summary table."""
    sorted_cos = sorted(companies, key=lambda c: c.fit_score, reverse=True)

    table = Table(title="Freelance Prospects", show_lines=True)
    table.add_column("Tier", style="bold", width=6)
    table.add_column("Score", width=6)
    table.add_column("Company", width=28)
    table.add_column("Location", width=20)
    table.add_column("Category", width=16)
    table.add_column("Relationship", width=14)

    tier_style = {"HOT": "red bold", "WARM": "yellow", "COLD": "dim", "SKIP": "dim"}
    for co in sorted_cos[:40]:
        style = tier_style.get(co.fit_tier, "white")
        table.add_row(
            f"[{style}]{co.fit_tier or '—'}[/{style}]",
            str(co.fit_score) if co.fit_score else "—",
            co.name[:28],
            f"{co.city}, {co.state}"[:20] if co.city else co.state,
            co.category[:16],
            co.relationship[:14],
        )

    console.print(table)

    hot = sum(1 for c in companies if c.fit_tier == "HOT")
    warm = sum(1 for c in companies if c.fit_tier == "WARM")
    cold = sum(1 for c in companies if c.fit_tier == "COLD")
    skip = sum(1 for c in companies if c.fit_tier == "SKIP")
    console.print(f"\n  HOT:           {hot}")
    console.print(f"  WARM:          {warm}")
    console.print(f"  COLD:          {cold}")
    console.print(f"  SKIP (known):  {skip}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Freelance Prospect Finder — discovers AV companies and generates cold outreach"
    )
    parser.add_argument(
        "--discover-only", action="store_true",
        help="Skip verification and LLM evaluation",
    )
    parser.add_argument(
        "--evaluate-only", action="store_true",
        help="Re-run LLM on cached companies (no new discovery)",
    )
    parser.add_argument(
        "--no-outreach", action="store_true",
        help="Evaluate companies but skip email draft generation",
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip activity verification searches",
    )
    parser.add_argument(
        "--category",
        help="Only search one category: av_rental, production_co, venue, touring, corporate_av, university",
    )
    parser.add_argument(
        "--relationship", default="new_prospect",
        help="Filter by relationship: new_prospect, known_partner, known_client, all",
    )
    parser.add_argument(
        "--min-tier", default="warm",
        help="Minimum fit tier to generate outreach for: hot, warm (default: warm)",
    )
    parser.add_argument(
        "--max-companies", type=int, default=0,
        help="Cap total companies discovered (default: from config)",
    )
    args = parser.parse_args()

    config = load_config()
    freelance_cfg = config.get("freelance_search", {})
    resume_text = load_resume(config)
    clients_lookup = ClientsLookup(CLIENTS_YAML_PATH)

    max_companies = args.max_companies or freelance_cfg.get("max_companies", 100)

    # --- Discover or load previous ---
    if args.evaluate_only:
        console.print("[bold]Loading previous results for re-evaluation...[/bold]")
        companies = load_previous_companies()
        if not companies:
            console.print("[red]No previous results found. Run without --evaluate-only first.[/red]")
            sys.exit(1)
        console.print(f"  Loaded {len(companies)} companies from last snapshot")
    else:
        console.print("[bold]Starting company discovery...[/bold]")
        companies = run_discover(config, args.category, max_companies)
        companies = deduplicate_companies(companies)

        # Apply relationship lookup
        for co in companies:
            relationship, notes = clients_lookup.lookup(co.name, co.city)
            co.relationship = relationship
            co.relationship_notes = notes

        # Filter by relationship flag
        if args.relationship and args.relationship != "all":
            if args.relationship == "new_prospect":
                companies = [c for c in companies if c.relationship == "new_prospect"]
            else:
                companies = [c for c in companies if c.relationship == args.relationship]

        console.print(
            f"[bold]{len(companies)} companies after dedup + relationship filter[/bold]"
        )

    if args.discover_only:
        save_freelance_results(companies)
        print_freelance_summary(companies)
        console.print(f"\n[bold]Discovery complete.[/bold] Results in freelance/{datetime.now().strftime('%Y-%m-%d')}/")
        return

    # --- Verify ---
    verify_activity = freelance_cfg.get("verify_activity", True) and not args.no_verify
    if verify_activity and not args.evaluate_only:
        companies = run_verify(companies, config)

    # --- Evaluate ---
    outreach_min_tier = args.min_tier or freelance_cfg.get("outreach_min_tier", "warm")
    companies = run_evaluate_companies(
        companies, config, resume_text,
        no_outreach=args.no_outreach,
        outreach_min_tier=outreach_min_tier,
    )

    # --- Save & report ---
    json_path, csv_path, md_path = save_freelance_results(companies)
    print_freelance_summary(companies)
    console.print(f"\n[bold green]Done![/bold green]")
    console.print(f"  Summary: {md_path}")
    console.print(f"  CSV:     {csv_path}")
    console.print(f"  JSON:    {json_path}")


if __name__ == "__main__":
    main()
