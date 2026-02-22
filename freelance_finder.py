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
from urllib.parse import urlparse

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
        "google_aistudio": ("google_aistudio_model", "gemini-3-flash"),
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
    website_about: str = ""

    # Logo
    logo_url: str = ""

    # -- Enrichment: HubSpot --
    hubspot_employees: Optional[int] = None
    hubspot_revenue: Optional[str] = None
    hubspot_industry: Optional[str] = None
    hubspot_linkedin_url: Optional[str] = None
    hubspot_company_id: Optional[str] = None

    # -- Enrichment: LinkedIn (BrightData) --
    linkedin_employees: Optional[int] = None
    linkedin_industry: Optional[str] = None
    linkedin_specialties: Optional[list] = None

    # -- Enrichment: Structured data --
    schema_org_data: Optional[dict] = None
    event_mentions: Optional[list] = None

    # LLM evaluation
    fit_tier: str = ""            # "HOT"|"WARM"|"COLD"|"SKIP"
    fit_score: int = 0            # 0-100
    fit_reasoning: str = ""
    full_evaluation: str = ""
    outreach_draft: str = ""
    outreach_subject: str = ""

    # Dimensional scores (1-5 each)
    geographic_fit: int = 0
    scale_gear: int = 0
    work_type: int = 0
    relationship_potential: int = 0
    credibility: int = 0

    # Dimensional rationales (one sentence each)
    geographic_fit_rationale: str = ""
    scale_gear_rationale: str = ""
    work_type_rationale: str = ""
    relationship_potential_rationale: str = ""
    credibility_rationale: str = ""

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
    # Forums, marketplaces, directories — not actual companies
    "reddit.com", "freelancer.com", "guru.com", "fiverr.com", "upwork.com",
    "soundgirls.org", "productionhub.com", "audiovisualnation.com",
    "rentforevent.com", "bark.com", "eventective.com", "gigsalad.com",
    "thecreativefinder.com", "sortlist.com", "clutch.co",
    "wikipedia.org", "quora.com",
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
    # Strip trailing ": Home", ": About Us", ": Careers", etc.
    title = re.sub(r":\s*(Home|About Us?|Careers?|Contact|Services)\s*$", "", title, flags=re.IGNORECASE)
    # Strip trailing "| " remnants (e.g., "AV Rentals in Los Angeles |")
    title = title.rstrip(" |")
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

        from pipeline_utils import log_api_usage
        log_api_usage(
            source="external", category="search_api", pipeline="freelance_finder", operation="freelance_serpapi",
            provider="serpapi", cost_usd=0.01, success=True,
            http_status=resp.status_code,
        )

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
            if not title:
                continue
            combined_text = (title + " " + snippet + " " + url).lower()
            if any(kw in combined_text for kw in BLOCKED_OPERATOR_KEYWORDS):
                log.debug(f"Skipping Encore/PSAV managed result: {title}")
                continue
            city, state = _extract_location(snippet + " " + item.get("title", ""))
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

        from pipeline_utils import log_api_usage
        log_api_usage(
            source="external", category="search_api", pipeline="freelance_finder", operation="freelance_brightdata",
            provider="brightdata", cost_usd=0.003, success=True,
            http_status=resp.status_code,
        )

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
            if not title:
                continue
            combined_text = (title + " " + snippet + " " + url).lower()
            if any(kw in combined_text for kw in BLOCKED_OPERATOR_KEYWORDS):
                log.debug(f"Skipping Encore/PSAV managed result: {title}")
                continue
            city, state = _extract_location(snippet + " " + title)
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

    @staticmethod
    def _extract_logo_url(soup: BeautifulSoup, base_url: str) -> str:
        """Extract the best logo URL from a parsed homepage.

        Priority: og:image > apple-touch-icon > largest <link rel="icon">.
        Returns an absolute URL or empty string.
        """
        from urllib.parse import urljoin

        # 1. Open Graph image (usually the highest quality logo/brand image)
        og = soup.find('meta', property='og:image')
        if og and og.get('content'):
            return urljoin(base_url, og['content'])

        # 2. Apple touch icon (typically a clean square logo)
        apple = soup.find('link', rel=lambda r: r and 'apple-touch-icon' in r)
        if apple and apple.get('href'):
            return urljoin(base_url, apple['href'])

        # 3. Largest <link rel="icon"> by sizes attribute
        icons = soup.find_all('link', rel=lambda r: r and 'icon' in r)
        best_icon = ''
        best_size = 0
        for icon in icons:
            href = icon.get('href', '')
            if not href:
                continue
            sizes = icon.get('sizes', '')
            if sizes and 'x' in sizes.lower():
                try:
                    w = int(sizes.lower().split('x')[0])
                    if w > best_size:
                        best_size = w
                        best_icon = href
                except (ValueError, IndexError):
                    pass
            elif not best_icon:
                best_icon = href
        if best_icon:
            return urljoin(base_url, best_icon)

        return ''

    @staticmethod
    def _extract_schema_org(html: str) -> Optional[dict]:
        """Extract Organization data from JSON-LD schema.org markup."""
        import json as _json
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Organization", "LocalBusiness",
                                              "Corporation", "PerformingGroup"):
                        result = {}
                        emp = item.get("numberOfEmployees")
                        if isinstance(emp, dict):
                            result["employee_count"] = int(emp.get("value", 0)) or None
                        elif isinstance(emp, (int, str)):
                            try:
                                result["employee_count"] = int(emp)
                            except ValueError:
                                pass
                        if item.get("foundingDate"):
                            result["founding_date"] = str(item["foundingDate"])
                        addr = item.get("address", {})
                        if isinstance(addr, dict):
                            if addr.get("addressLocality"):
                                result["city"] = addr["addressLocality"]
                            if addr.get("addressRegion"):
                                result["state"] = addr["addressRegion"]
                        if result:
                            return result
            except (ValueError, TypeError, KeyError):
                continue
        return None

    def _find_subpage_urls(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Scan homepage links for common subpages like /about, /equipment, /services."""
        subpage_patterns = [
            r'/about', r'/equipment', r'/gear', r'/inventory',
            r'/services', r'/portfolio', r'/clients', r'/our-work', r'/projects',
        ]
        found: list[str] = []
        base = base_url.rstrip('/')
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Normalize relative URLs
            if href.startswith('/'):
                href = base + href
            elif not href.startswith('http'):
                continue
            # Only follow links on the same domain
            if not href.startswith(base):
                continue
            path = href[len(base):].split('?')[0].split('#')[0].rstrip('/')
            for pattern in subpage_patterns:
                if re.search(pattern, path, re.IGNORECASE):
                    if href not in found:
                        found.append(href)
                    break
            if len(found) >= 2:
                break
        return found

    def _scrape_website(self, url: str) -> tuple[str, str, Optional[dict]]:
        """Fetch homepage and key subpages, return (combined_clean_text, logo_url, schema_org_data)."""
        if not url or not url.startswith('http'):
            return "", "", None

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }

        def _fetch_clean_text(page_url: str) -> str:
            try:
                resp = requests.get(page_url, headers=headers, timeout=10, allow_redirects=True)
                if resp.status_code != 200:
                    return ""
                soup = BeautifulSoup(resp.text, 'html.parser')
                # Remove non-content elements
                for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'noscript', 'iframe']):
                    tag.decompose()
                # Prefer <main> content, fall back to <body>
                content = soup.find('main') or soup.find('body')
                if not content:
                    return ""
                return content.get_text(' ', strip=True)
            except Exception:
                return ""

        # Fetch homepage
        try:
            resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code != 200:
                return "", "", None
            homepage_soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception:
            return "", "", None

        # Extract logo URL before decomposing tags
        logo_url = self._extract_logo_url(homepage_soup, url)

        # Extract schema.org data from raw HTML before any tag decomposition
        schema_org_data = self._extract_schema_org(resp.text)

        # Re-parse for text extraction (we need a fresh soup since extract may read tags we'd decompose)
        text_soup = BeautifulSoup(resp.text, 'html.parser')

        # Extract homepage text
        for tag in text_soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'noscript', 'iframe']):
            tag.decompose()
        main_el = text_soup.find('main') or text_soup.find('body')
        homepage_text = main_el.get_text(' ', strip=True) if main_el else ""

        # Re-parse for link scanning
        try:
            link_soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception:
            link_soup = text_soup

        # Find and fetch subpages
        base_url_clean = url.rstrip('/')
        subpage_urls = self._find_subpage_urls(link_soup, base_url_clean)
        subpage_texts = []
        for sub_url in subpage_urls:
            text = _fetch_clean_text(sub_url)
            if text:
                subpage_texts.append(text)

        combined = homepage_text
        for st in subpage_texts:
            combined += "\n\n" + st

        # Truncate to ~3000 chars
        if len(combined) > 3000:
            combined = combined[:3000] + "..."
        return combined.strip(), logo_url, schema_org_data

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

    def _extract_scale_signals(self, results: list[dict], website_text: str = "") -> str:
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
        # Also search website text
        if website_text:
            for kw in scale_keywords:
                if kw.lower() in website_text.lower():
                    for s in website_text.split("."):
                        if kw.lower() in s.lower() and s.strip() not in found:
                            found.append(s.strip()[:200])
                            break
        return " | ".join(found[:3])

    def _extract_notable_clients(self, results: list[dict], website_text: str = "") -> str:
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
        # Also search website text
        if website_text:
            for kw in client_keywords:
                if kw.lower() in website_text.lower():
                    for s in website_text.split("."):
                        if kw.lower() in s.lower() and s.strip() not in found:
                            found.append(s.strip()[:200])
                            break
        return " | ".join(found[:2])

    def _extract_gear(self, results: list[dict], website_text: str = "") -> str:
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
        # Also search website text
        if website_text:
            wt_lower = website_text.lower()
            for brand in gear_brands:
                if brand.lower() in wt_lower:
                    found.add(brand)
        return ", ".join(sorted(found))

    def _enrich_linkedin(self, company_name: str, website: str) -> dict:
        """Fetch LinkedIn company data via BrightData dataset API.
        Returns dict with linkedin_employees, linkedin_industry, linkedin_specialties or empty dict."""
        if not self.brightdata_token:
            return {}
        # Extract domain from website URL for LinkedIn search
        domain = urlparse(website).netloc.removeprefix("www.").split(".")[0]
        try:
            trigger_resp = requests.post(
                "https://api.brightdata.com/datasets/v3/trigger",
                headers={"Authorization": f"Bearer {self.brightdata_token}",
                         "Content-Type": "application/json"},
                params={"dataset_id": "gd_l1viktl72bvl7bjuj0",
                        "include_errors": "true", "type": "discover_new",
                        "discover_by": "url"},
                json=[{"url": f"https://www.linkedin.com/company/{domain}/"}],
                timeout=30,
            )
            if trigger_resp.status_code != 200:
                log.debug(f"BrightData LinkedIn trigger failed for {company_name}: {trigger_resp.status_code}")
                return {}
            snapshot_id = trigger_resp.json().get("snapshot_id")
            if not snapshot_id:
                return {}
            # Poll for completion (max 60s)
            for _ in range(12):
                time.sleep(5)
                status_resp = requests.get(
                    f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}",
                    headers={"Authorization": f"Bearer {self.brightdata_token}"},
                    params={"format": "json"},
                    timeout=15,
                )
                if status_resp.status_code == 200:
                    data = status_resp.json()
                    if isinstance(data, list) and data:
                        record = data[0]
                        employees = record.get("company_size_on_linkedin") or record.get("num_employees")
                        return {
                            "linkedin_employees": int(employees) if employees else None,
                            "linkedin_industry": record.get("industry"),
                            "linkedin_specialties": record.get("specialities") or record.get("specialties"),
                        }
                elif status_resp.status_code == 202:
                    continue
                else:
                    break
            return {}
        except Exception as e:
            log.debug(f"LinkedIn enrichment failed for {company_name}: {e}")
            return {}

    def _check_event_presence(self, name: str, city: str, state: str) -> Optional[list]:
        """Search for recent event/venue mentions of this company."""
        year = datetime.now().year
        query = f'"{name}" ({city} OR {state}) (event OR festival OR concert OR production OR install) {year}'
        results = self._search(query)
        if not results:
            return None
        events = []
        for r in results[:5]:
            text = r.get("snippet", r.get("description", ""))
            if text:
                events.append(text)
        return events if events else None

    def verify(self, company: CompanyProfile) -> CompanyProfile:
        """Run a verification search for one company and populate research fields."""
        # Scrape the company website first (no API cost)
        website_text, logo_url, schema_org_data = self._scrape_website(company.website)
        if website_text:
            company.website_about = website_text
        if logo_url:
            company.logo_url = logo_url
        if schema_org_data:
            company.schema_org_data = schema_org_data

        current_year = datetime.now().year
        year_range = f"{current_year - 1} OR {current_year}"
        query = f'"{company.name}" {company.city} events audio {year_range}'
        results = self._search(query)
        company.recent_activity = self._extract_activity(results)
        company.scale_signals = self._extract_scale_signals(results, website_text)
        company.notable_clients = self._extract_notable_clients(results, website_text)
        company.gear_mentioned = self._extract_gear(results, website_text)
        company.event_mentions = self._check_event_presence(company.name, company.city, company.state)
        linkedin_data = self._enrich_linkedin(company.name, company.website)
        if linkedin_data:
            company.linkedin_employees = linkedin_data.get("linkedin_employees")
            company.linkedin_industry = linkedin_data.get("linkedin_industry")
            company.linkedin_specialties = linkedin_data.get("linkedin_specialties")
        return company

    def verify_batch(
        self, companies: list[CompanyProfile], max_workers: int = 8,
    ) -> list[CompanyProfile]:
        """Verify companies concurrently. Website scraping runs even without search API keys."""

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
def _root_domain(url: str) -> str:
    """Extract root domain from URL for dedup (e.g., 'meetingtomorrow.com')."""
    if not url:
        return ""
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if m:
        host = m.group(1)
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:]).lower()
    return ""


def deduplicate_companies(companies: list[CompanyProfile]) -> list[CompanyProfile]:
    """Remove duplicate companies: exact company_id, fuzzy name+state, then URL domain."""
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

    pass2 = []
    fuzzy_merged = 0
    for key, group in fuzzy_groups.items():
        if len(group) == 1 or not key[0]:
            pass2.extend(group)
            continue
        # Keep the entry with the longest description
        best = max(group, key=lambda c: len(c.description))
        pass2.append(best)
        fuzzy_merged += len(group) - 1

    # Pass 3: URL-domain-based dedup — collapse entries sharing the same root domain
    # (catches meetingtomorrow.com/chicago vs meetingtomorrow.com/av-rentals)
    domain_groups: dict[str, list[CompanyProfile]] = {}
    no_domain: list[CompanyProfile] = []
    for co in pass2:
        domain = _root_domain(co.website)
        if domain:
            domain_groups.setdefault(domain, []).append(co)
        else:
            no_domain.append(co)

    final = list(no_domain)
    domain_merged = 0
    for domain, group in domain_groups.items():
        if len(group) == 1:
            final.extend(group)
            continue
        best = max(group, key=lambda c: len(c.description))
        final.append(best)
        domain_merged += len(group) - 1

    log.info(
        f"Deduplicated: {len(companies)} → {len(final)} unique companies "
        f"({exact_count} exact, {fuzzy_merged} fuzzy, {domain_merged} domain)"
    )
    return final


# ---------------------------------------------------------------------------
# LLM evaluation
# ---------------------------------------------------------------------------
class CompanyEvaluator:
    """
    Uses an LLM to evaluate each company's fit and generate cold outreach emails.
    Supports OpenRouter, Anthropic, Google AI Studio, OpenAI-compatible endpoints.
    Defaults to google_aistudio / gemini-3-flash for cost efficiency.
    """

    def __init__(self, config: dict, resume_text: str):
        self.resume_text = resume_text
        self.candidate_context = config.get("candidate_context", "")
        self.client = None

        # Profile fields for parameterized prompts
        self.full_name = config.get("full_name", "")
        self.professional_title = config.get("professional_title", "")
        self.home_city = config.get("home_city", "")
        self.phone = config.get("phone", "")
        self.linkedin_url = config.get("linkedin_url", "")
        self.notify_email = config.get("notify_email", "")
        self.first_name = self.full_name.split()[0] if self.full_name else ""

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
        import time as _time
        from pipeline_utils import log_api_usage
        if not self.client:
            return ""
        _start = _time.time()
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            _latency = int((_time.time() - _start) * 1000)
            _pt = getattr(response.usage, "input_tokens", 0)
            _ct = getattr(response.usage, "output_tokens", 0)
            log_api_usage(
                source="pipeline", category="llm", pipeline="freelance_finder", operation="freelance_eval",
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                latency_ms=_latency, success=True,
            )
            return response.content[0].text.strip()
        elif self.provider == "google_aistudio":
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"max_output_tokens": 4000, "temperature": 0.5},
            )
            _latency = int((_time.time() - _start) * 1000)
            um = getattr(response, "usage_metadata", None)
            _pt = getattr(um, "prompt_token_count", 0) if um else 0
            _ct = getattr(um, "candidates_token_count", 0) if um else 0
            log_api_usage(
                source="pipeline", category="llm", pipeline="freelance_finder", operation="freelance_eval",
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
                    "X-Title": "Freelance Finder",
                }
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
                extra_headers=extra_headers,
            )
            _latency = int((_time.time() - _start) * 1000)
            _pt = response.usage.prompt_tokens or 0 if response.usage else 0
            _ct = response.usage.completion_tokens or 0 if response.usage else 0
            _cost = getattr(response.usage, "cost", None) if response.usage else None
            log_api_usage(
                source="pipeline", category="llm", pipeline="freelance_finder", operation="freelance_eval",
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                cost_usd=_cost, latency_ms=_latency, success=True,
            )
            return response.choices[0].message.content.strip()

    # Composite scoring weights and tier thresholds
    DIMENSION_WEIGHTS = {
        "geographic_fit": 2,
        "scale_gear": 2,
        "work_type": 1,
        "relationship_potential": 1,
        "credibility": 1,
    }
    TIER_THRESHOLDS = [
        (3.8, "HOT"),
        (2.6, "WARM"),
        (1.6, "COLD"),
        (0.0, "SKIP"),
    ]

    @staticmethod
    def _compute_composite(dims: dict[str, int]) -> float:
        """Weighted composite: (2*Geo + 2*ScaleGear + WorkType + Relationship + Credibility) / 7"""
        w = CompanyEvaluator.DIMENSION_WEIGHTS
        total = sum(dims.get(k, 3) * v for k, v in w.items())
        return total / sum(w.values())

    @staticmethod
    def _composite_to_tier(composite: float) -> str:
        for threshold, tier in CompanyEvaluator.TIER_THRESHOLDS:
            if composite >= threshold:
                return tier
        return "SKIP"

    @staticmethod
    def _composite_to_score(composite: float) -> int:
        """Map 1.0-5.0 composite to 0-100 score."""
        return max(0, min(100, int((composite - 1.0) * 25)))

    @staticmethod
    def _apply_gating_rules(dims: dict[str, int], tier: str) -> str:
        """Apply hard gating rules that override the composite tier."""
        cred = dims.get("credibility", 3)
        scale = dims.get("scale_gear", 3)
        if cred <= 1:
            return "SKIP"
        if cred <= 2 and tier in ("HOT", "WARM"):
            return "COLD"
        if scale <= 1 and tier in ("HOT", "WARM"):
            return "COLD"
        return tier

    def _is_blocked_operator(self, company: CompanyProfile) -> bool:
        """Pre-LLM check: return True if company is a known blocked operator."""
        combined = (
            f"{company.name} {company.website} {company.description} "
            f"{company.website_about}"
        ).lower()
        domain = _domain_from_url(company.website) if company.website else ""
        for kw in BLOCKED_OPERATOR_KEYWORDS:
            if kw in combined or kw in domain:
                return True
        return False

    def evaluate_company(self, company: CompanyProfile) -> dict:
        """Evaluate a company's fit for freelance work using dimensional scoring."""
        empty_result = {
            "fit_tier": "", "fit_score": 0, "fit_reasoning": "", "full_evaluation": "",
            "dimensions": {}, "actual_name": "", "is_real_company": True,
        }
        if not self.client or not self.resume_text:
            return empty_result

        # Pre-LLM blocked operator check — save LLM cost
        if self._is_blocked_operator(company):
            log.info(f"Blocked operator detected pre-LLM: {company.name}")
            return {
                "fit_tier": "SKIP", "fit_score": 0,
                "fit_reasoning": "Blocked operator (Encore/PSAV/ON Services)",
                "full_evaluation": "Blocked operator — skipped without LLM evaluation.",
                "dimensions": {"geographic_fit": 1, "scale_gear": 1, "work_type": 1,
                               "relationship_potential": 1, "credibility": 1},
                "actual_name": company.name, "is_real_company": True,
            }

        # Build candidate description
        title_desc = self.professional_title or "A1 audio engineer"
        candidate_name = self.first_name or "the candidate"
        home_city = self.home_city or "a major US city"

        # Build enrichment data section
        enrichment_lines = []
        if company.hubspot_employees or company.linkedin_employees:
            employees = company.linkedin_employees or company.hubspot_employees
            source = "LinkedIn" if company.linkedin_employees else "HubSpot"
            enrichment_lines.append(f"Employee Count ({source}): {employees}")
        if company.hubspot_revenue:
            enrichment_lines.append(f"Annual Revenue (HubSpot): ${company.hubspot_revenue}")
        if company.hubspot_industry or company.linkedin_industry:
            industry = company.linkedin_industry or company.hubspot_industry
            source = "LinkedIn" if company.linkedin_industry else "HubSpot"
            enrichment_lines.append(f"Industry ({source}): {industry}")
        if company.linkedin_specialties:
            enrichment_lines.append(f"Specialties (LinkedIn): {', '.join(company.linkedin_specialties)}")
        if company.schema_org_data:
            sod = company.schema_org_data
            if sod.get("employee_count"):
                enrichment_lines.append(f"Employee Count (website schema): {sod['employee_count']}")
            if sod.get("founding_date"):
                enrichment_lines.append(f"Founded: {sod['founding_date']}")
        if company.event_mentions:
            enrichment_lines.append(f"Recent Event Mentions: {'; '.join(company.event_mentions[:3])}")

        enrichment_section = ""
        if enrichment_lines:
            enrichment_section = "\nENRICHMENT DATA (structured sources — more reliable than web scraping):\n" + "\n".join(enrichment_lines)

        prompt = f"""You are evaluating potential freelance clients for an experienced {title_desc} based in {home_city}.

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
Website Content: {company.website_about or "Not available"}
{enrichment_section}

EVALUATION TASK:
Score this company on 5 dimensions (each 1-5) as a potential freelance client for day calls and multi-day gigs.

DIMENSION 1 — GEOGRAPHIC FIT (weight: 2x)
How close is this company to {home_city}? Consider travel logistics and day-rate feasibility.
  5 = In {home_city} or within 1 hour drive
  4 = Same region / 2-3 hour drive, easy day trip
  3 = Domestic flight required but reasonable (2-3 hour flight)
  2 = Far domestic / awkward routing
  1 = International or impractical travel

DIMENSION 2 — SCALE & GEAR ALIGNMENT (weight: 2x)
Does this company work at a scale that matches the resume, and do they use gear the candidate knows?
Check the resume for specific gear brands (L-Acoustics, DiGiCo, Shure Axient, Dante, etc.) and compare.
  5 = Large-scale events with matching pro audio gear (L-Acoustics, DiGiCo, etc.)
  4 = Mid-to-large scale with some gear overlap
  3 = Decent scale but limited gear info or partial overlap
  2 = Small scale or consumer/prosumer gear (QSC K-series, basic Yamaha mixers)
  1 = Residential, DJ, or no relevant gear at all

DIMENSION 3 — WORK-TYPE FIT (weight: 1x)
Does the company hire freelance audio engineers for the right kind of work?
  5 = Corporate events, concerts, festivals — classic A1 freelance day-call work
  4 = AV rental / production company that regularly crews up freelancers
  3 = Mixed work, some relevant, some not (e.g., 50% lighting, 50% audio)
  2 = Mostly permanent/install/residential work, rarely hires freelancers
  1 = Not relevant work type (DJ, wedding band, home theater, retail)

DIMENSION 4 — RELATIONSHIP POTENTIAL (weight: 1x)
Could this become a recurring freelance relationship?
  5 = High volume, multiple events per month, clear need for freelance A1s
  4 = Regular events, likely repeat bookings
  3 = Seasonal or moderate event volume
  2 = Occasional events, unlikely to become regular
  1 = One-off or very infrequent

DIMENSION 5 — CREDIBILITY & SIGNAL QUALITY (weight: 1x)
Is this a real, operating company that could actually be contacted?
  5 = Established company with clear website, events, and contact info
  4 = Real company, some online presence, contactable
  3 = Exists but limited info, hard to verify scale
  2 = Questionable — might be a directory page, aggregator, or defunct
  1 = NOT a real company — this is a directory listing, blog post, job board, marketplace page, Reddit thread, or aggregator (e.g., PartySlate, The Bash, EventUp, Peerspace, WeddingWire)

CALIBRATION ANCHORS — use these as reference points:
  HOT (composite 3.8-5.0):
    - Production company in {home_city} with gear matching the resume, corporate events
    - National AV integrator with {home_city} office, uses gear the candidate knows
  WARM (composite 2.6-3.7):
    - Regional company, decent gear but mostly lighting/video focused
    - National company, good scale but no presence near {home_city}
  COLD (composite 1.6-2.5):
    - Small residential AV installer, no live event work
    - DJ/wedding company, consumer-grade gear
  SKIP (composite 1.0-1.5):
    - Job aggregator/directory page (PartySlate, The Bash, GigSalad, etc.)
    - Blocked operator (Encore/PSAV) or staffing agency

SPECIAL RULES:
- If relationship is "known_partner": rate SKIP (already in rotation)
- If Encore/PSAV-managed (website, contacts, or description): rate SKIP
- If NOT a real company (directory, blog, marketplace): Credibility = 1

Respond with ONLY these fields, one per line:

GEOGRAPHIC_FIT: <1-5>
GEOGRAPHIC_FIT_RATIONALE: <one sentence explaining the geographic score>
SCALE_GEAR: <1-5>
SCALE_GEAR_RATIONALE: <one sentence explaining the gear/scale score>
WORK_TYPE: <1-5>
WORK_TYPE_RATIONALE: <one sentence explaining the work-type score>
RELATIONSHIP: <1-5>
RELATIONSHIP_RATIONALE: <one sentence explaining the relationship potential score>
CREDIBILITY: <1-5>
CREDIBILITY_RATIONALE: <one sentence explaining the credibility score>
FIT_TIER: <HOT|WARM|COLD|SKIP>
FIT_SCORE: <1-100>
FIT_SUMMARY: <one sentence explaining the rating>
ACTUAL_COMPANY_NAME: <the real company name, NOT a page title like "About Us" or "Careers">
IS_REAL_COMPANY: <YES|NO>

## Company Assessment
[2-3 paragraph analysis]

## Why They Would Want {candidate_name}
- [bullet]
- [bullet]

## Potential Red Flags
- [bullet or "None identified"]"""

        try:
            response = self._call_llm(prompt)
        except Exception as e:
            log.error(f"LLM error evaluating {company.name}: {e}")
            return empty_result

        # --- Parse dimensional scores and rationales ---
        dims: dict[str, int] = {}
        dim_rationales: dict[str, str] = {}
        dim_patterns = {
            "geographic_fit": (r'GEOGRAPHIC_FIT:\s*(\d)', r'GEOGRAPHIC_FIT_RATIONALE:\s*(.+?)(?:\n|$)'),
            "scale_gear": (r'SCALE_GEAR:\s*(\d)', r'SCALE_GEAR_RATIONALE:\s*(.+?)(?:\n|$)'),
            "work_type": (r'WORK_TYPE:\s*(\d)', r'WORK_TYPE_RATIONALE:\s*(.+?)(?:\n|$)'),
            "relationship_potential": (r'RELATIONSHIP:\s*(\d)', r'RELATIONSHIP_RATIONALE:\s*(.+?)(?:\n|$)'),
            "credibility": (r'CREDIBILITY:\s*(\d)', r'CREDIBILITY_RATIONALE:\s*(.+?)(?:\n|$)'),
        }
        for dim_key, (score_pat, rationale_pat) in dim_patterns.items():
            m = re.search(score_pat, response)
            if m:
                dims[dim_key] = max(1, min(5, int(m.group(1))))
            else:
                dims[dim_key] = 3  # default to mid if LLM doesn't output
            rm = re.search(rationale_pat, response)
            if rm:
                dim_rationales[dim_key] = rm.group(1).strip()

        # --- Parse other fields ---
        actual_name = ""
        name_match = re.search(r'ACTUAL_COMPANY_NAME:\s*(.+?)(?:\n|$)', response)
        if name_match:
            actual_name = name_match.group(1).strip()

        is_real = True
        real_match = re.search(r'IS_REAL_COMPANY:\s*(YES|NO)', response, re.IGNORECASE)
        if real_match and real_match.group(1).upper() == "NO":
            is_real = False

        fit_reasoning = ""
        summary_match = re.search(r'FIT_SUMMARY:\s*(.+?)(?:\n|$)', response)
        if summary_match:
            fit_reasoning = summary_match.group(1).strip()

        # --- Server-side recalculation (override LLM tier/score) ---
        if not is_real:
            dims["credibility"] = 1

        composite = self._compute_composite(dims)
        fit_tier = self._composite_to_tier(composite)
        fit_tier = self._apply_gating_rules(dims, fit_tier)
        fit_score = self._composite_to_score(composite)

        # Post-LLM blocked operator check on ACTUAL_COMPANY_NAME
        if actual_name:
            actual_lower = actual_name.lower()
            for kw in BLOCKED_OPERATOR_KEYWORDS:
                if kw in actual_lower:
                    fit_tier = "SKIP"
                    fit_score = 0
                    fit_reasoning = f"Blocked operator ({actual_name})"
                    break

        if not is_real:
            fit_tier = "SKIP"
            fit_score = 0
            fit_reasoning = f"Not a real company — {fit_reasoning}" if fit_reasoning else "Not a real company"

        return {
            "fit_tier": fit_tier,
            "fit_score": fit_score,
            "fit_reasoning": fit_reasoning,
            "full_evaluation": response,
            "dimensions": dims,
            "dim_rationales": dim_rationales,
            "actual_name": actual_name,
            "is_real_company": is_real,
        }

    def generate_outreach(self, company: CompanyProfile) -> dict:
        """Generate a personalized cold outreach email for HOT/WARM companies."""
        if not self.client:
            return {"outreach_draft": "", "outreach_subject": ""}

        # Build sender description and signature
        sender_name = self.full_name or "the candidate"
        title_desc = self.professional_title or "freelance audio engineer"
        location_tag = f", {self.home_city}" if self.home_city else ""

        # Build signature parts dynamically (omit empty fields)
        sig_parts = []
        if self.full_name:
            sig_parts.append(self.full_name)
        if self.professional_title:
            sig_parts.append(self.professional_title)
        if self.home_city:
            sig_parts.append(self.home_city)
        sig_line1 = " | ".join(sig_parts) if sig_parts else ""

        contact_parts = []
        if self.notify_email:
            contact_parts.append(self.notify_email)
        if self.phone:
            contact_parts.append(self.phone)
        if self.linkedin_url:
            contact_parts.append(self.linkedin_url)
        sig_line2 = " | ".join(contact_parts) if contact_parts else ""

        signature_block = ""
        if sig_line1:
            signature_block = f"\n  {sig_line1}"
        if sig_line2:
            signature_block += f"\n  {sig_line2}"

        sign_off = f"— {self.first_name}" if self.first_name else "— [Your name]"

        prompt = f"""Write a cold outreach email from {sender_name} (freelance {title_desc}{location_tag}) to {company.name}.

COMPANY INFO:
Name: {company.name}
Category: {company.category}
Location: {company.city}, {company.state}
Website: {company.website}
Description: {company.description}
Recent Activity: {company.recent_activity or "N/A"}
Gear Mentioned: {company.gear_mentioned or "N/A"}
Website Content: {company.website_about or "N/A"}
{enrichment_section}

SENDER'S RESUME:
{self.resume_text}

ADDITIONAL CONTEXT:
{self.candidate_context}

WRITING STYLE RULES (follow strictly):
- 4-6 sentences ONLY. Short paragraphs. No walls of text.
- Peer-to-peer tone. This is one working professional emailing another, not a job application.
- Use contractions (I'm, don't, I've). Uncontracted prose sounds stiff.
- Vary sentence length. A five-word sentence is fine next to a longer one.
- Do NOT use em dashes. Use commas or periods instead.
- Do NOT use semicolons for style.
- Do NOT restate what the recipient already knows about their own company (no "you have a strong reputation", no "you handle everything from X to Y").
- Do NOT use transition phrases like "That aligns well with", "This lines up with", "Given your work in".
- Do NOT hedge the ask. Say what you want directly.
- Do NOT use forced-casual filler like "that's where I live", "right in my wheelhouse", "that's my bread and butter". If the connection is obvious, let the reader make it.
- Do NOT use any of these words or phrases: delve, tapestry, landscape, testament, vital role, furthermore, moreover, innovative, leverage, utilize, cutting-edge, robust, seamless, groundbreaking, pivotal, realm, harness, game-changer, ever-evolving, exciting, powerful, journey, foster, lasting impact, I came across your company, I noticed, I was impressed.
- Reference 1 specific detail about this company (a piece of gear they use, an event they did, their market niche) but work it in naturally, don't frame it as flattery.
- Lead with who you are and a concrete credential (a specific gig, a specific client, a specific number).
- Frame the ask as offering to "lend my experience" on a specific type of gig, not generic "be on your list/radar" language.
- End with: "{sign_off}"
- After the sign-off, add the full signature block on a new line:{signature_block}

GOOD EXAMPLE (for tone/structure only, do not copy content):
Hi,

Eric Weiss here, freelance A1 and RF coordinator in Chicago. I do a lot of corporate general sessions and galas around town, mostly with TC Furlong and Black Oak. Biggest recent RF job was a 128-channel wireless coordination at the WNBA All-Star Game at Gainbridge Fieldhouse.

I saw you guys do a good amount of multi-room hotel production. If you ever need an extra A1 or dedicated RF tech on a busy show, I'd love to lend my experience.

BAD EXAMPLE (do not write like this):
Enhance Productions' work in the corporate and special event space is right in my wheelhouse: I'm regularly running audio for general sessions, galas, charity events, and high-stakes corporate gatherings across the Chicago market, and I manage RF deployments up to 128-130 channels, which I know gets complicated fast in hotel and multi-room environments. Given your focus on virtual, hybrid, and in-person corporate production, I'd be a useful hand to have in your roster.

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
                co.geographic_fit = cached.get("geographic_fit", 0)
                co.scale_gear = cached.get("scale_gear", 0)
                co.work_type = cached.get("work_type", 0)
                co.relationship_potential = cached.get("relationship_potential", 0)
                co.credibility = cached.get("credibility", 0)
                co.geographic_fit_rationale = cached.get("geographic_fit_rationale", "")
                co.scale_gear_rationale = cached.get("scale_gear_rationale", "")
                co.work_type_rationale = cached.get("work_type_rationale", "")
                co.relationship_potential_rationale = cached.get("relationship_potential_rationale", "")
                co.credibility_rationale = cached.get("credibility_rationale", "")
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

            # Store dimensional scores and rationales
            dims = result.get("dimensions", {})
            co.geographic_fit = dims.get("geographic_fit", 0)
            co.scale_gear = dims.get("scale_gear", 0)
            co.work_type = dims.get("work_type", 0)
            co.relationship_potential = dims.get("relationship_potential", 0)
            co.credibility = dims.get("credibility", 0)
            rats = result.get("dim_rationales", {})
            co.geographic_fit_rationale = rats.get("geographic_fit", "")
            co.scale_gear_rationale = rats.get("scale_gear", "")
            co.work_type_rationale = rats.get("work_type", "")
            co.relationship_potential_rationale = rats.get("relationship_potential", "")
            co.credibility_rationale = rats.get("credibility", "")

            # LLM flagged this as not a real company (blog, directory, Reddit, etc.)
            if not result.get("is_real_company", True):
                log.info(f"Not a real company, skipping: '{co.name}' ({co.website})")
                return co

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
                    "geographic_fit": co.geographic_fit,
                    "scale_gear": co.scale_gear,
                    "work_type": co.work_type,
                    "relationship_potential": co.relationship_potential,
                    "credibility": co.credibility,
                    "geographic_fit_rationale": co.geographic_fit_rationale,
                    "scale_gear_rationale": co.scale_gear_rationale,
                    "work_type_rationale": co.work_type_rationale,
                    "relationship_potential_rationale": co.relationship_potential_rationale,
                    "credibility_rationale": co.credibility_rationale,
                }
        with open(FREELANCE_CACHE_PATH, "w") as f:
            json.dump(cache, f, separators=(",", ":"))
        log.info(f"Freelance cache saved: {len(cache)} entries")

        return cached_cos + new_cos


# ---------------------------------------------------------------------------
# Supabase sync
# ---------------------------------------------------------------------------
def _supabase_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def sync_freelance_to_supabase(
    config: dict,
    companies: list[CompanyProfile],
    user_id: str = "",
):
    """
    Upsert freelance companies into Supabase.

    Catalog data (name, city, website, gear, etc.) → freelance_companies table.
    Per-user evaluation data (tier, score, dimensions, outreach) → user_freelance_evaluations table.

    During the transition period, evaluation fields are also written to freelance_companies
    for backward compatibility.

    Args:
        config: App configuration dict.
        companies: Evaluated company profiles.
        user_id: The user whose evaluations these belong to. If empty, attempts to
                 look up the admin user (edweiss412@gmail.com).
    """
    # NOTE: Requires Supabase migration — see docs/plans/2026-02-21-hubspot-enrichment-design.md
    # ALTER TABLE freelance_companies
    #   ADD COLUMN IF NOT EXISTS hubspot_employees integer,
    #   ADD COLUMN IF NOT EXISTS hubspot_revenue text,
    #   ADD COLUMN IF NOT EXISTS hubspot_industry text,
    #   ADD COLUMN IF NOT EXISTS hubspot_linkedin_url text,
    #   ADD COLUMN IF NOT EXISTS hubspot_company_id text,
    #   ADD COLUMN IF NOT EXISTS linkedin_employees integer,
    #   ADD COLUMN IF NOT EXISTS linkedin_industry text,
    #   ADD COLUMN IF NOT EXISTS linkedin_specialties jsonb,
    #   ADD COLUMN IF NOT EXISTS schema_org_data jsonb,
    #   ADD COLUMN IF NOT EXISTS event_mentions jsonb,
    #   ADD COLUMN IF NOT EXISTS hubspot_synced_at timestamptz;
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        log.info("Supabase: not configured — skipping freelance sync")
        return

    headers = _supabase_headers(supabase_key)

    # Only sync evaluated companies (exclude SKIP and unevaluated)
    to_sync = [co for co in companies if co.fit_tier and co.fit_tier != "SKIP"]
    # Defensive dedup: LLM name corrections can produce company_id collisions
    seen: dict[str, CompanyProfile] = {}
    for co in to_sync:
        seen[co.company_id] = co
    to_sync = list(seen.values())
    if not to_sync:
        log.info("Supabase: no evaluated freelance companies to sync")
        return

    # Resolve user_id if not provided (default to admin)
    if not user_id:
        try:
            resp = requests.get(
                f"{supabase_url}/auth/v1/admin/users",
                headers=headers, timeout=30,
            )
            if resp.ok:
                for u in resp.json().get("users", []):
                    if u.get("email") == "edweiss412@gmail.com":
                        user_id = u["id"]
                        break
        except Exception:
            pass
        if not user_id:
            log.warning("Supabase: could not resolve admin user_id — skipping per-user eval sync")

    try:
        BATCH = 100

        # --- 1. Catalog data → freelance_companies (includes eval fields for backward compat) ---
        for i in range(0, len(to_sync), BATCH):
            batch = to_sync[i:i + BATCH]
            records = [{
                "company_id": co.company_id,
                "name": co.name,
                "city": co.city,
                "state": co.state or None,
                "website": co.website or None,
                "category": co.category or None,
                "relationship": co.relationship or None,
                "relationship_notes": co.relationship_notes or None,
                "fit_tier": co.fit_tier,
                "fit_score": co.fit_score,
                "fit_reasoning": co.fit_reasoning or None,
                "full_evaluation": co.full_evaluation or None,
                "outreach_draft": co.outreach_draft or None,
                "outreach_subject": co.outreach_subject or None,
                "recent_activity": co.recent_activity or None,
                "scale_signals": co.scale_signals or None,
                "notable_clients": co.notable_clients or None,
                "gear_mentioned": co.gear_mentioned or None,
                "website_about": co.website_about or None,
                "logo_url": co.logo_url or None,
                "hubspot_employees": co.hubspot_employees,
                "hubspot_revenue": co.hubspot_revenue or None,
                "hubspot_industry": co.hubspot_industry or None,
                "hubspot_linkedin_url": co.hubspot_linkedin_url or None,
                "hubspot_company_id": co.hubspot_company_id or None,
                "linkedin_employees": co.linkedin_employees,
                "linkedin_industry": co.linkedin_industry or None,
                "linkedin_specialties": co.linkedin_specialties,
                "schema_org_data": co.schema_org_data,
                "event_mentions": co.event_mentions,
                "first_seen_date": co.date_discovered,
                "last_seen_date": co.date_discovered,
            } for co in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/freelance_companies?on_conflict=company_id",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=records, timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Supabase: upserted {len(to_sync)} freelance companies (catalog)")

        # --- 2. Per-user evaluation data → user_freelance_evaluations ---
        if user_id:
            for i in range(0, len(to_sync), BATCH):
                batch = to_sync[i:i + BATCH]
                eval_records = [{
                    "user_id": user_id,
                    "company_id": co.company_id,
                    "fit_tier": co.fit_tier,
                    "fit_score": co.fit_score,
                    "geographic_fit": co.geographic_fit or None,
                    "scale_gear": co.scale_gear or None,
                    "work_type": co.work_type or None,
                    "relationship_potential": co.relationship_potential or None,
                    "credibility": co.credibility or None,
                    "geographic_fit_rationale": co.geographic_fit_rationale or None,
                    "scale_gear_rationale": co.scale_gear_rationale or None,
                    "work_type_rationale": co.work_type_rationale or None,
                    "relationship_potential_rationale": co.relationship_potential_rationale or None,
                    "credibility_rationale": co.credibility_rationale or None,
                    "fit_reasoning": co.fit_reasoning or None,
                    "full_evaluation": co.full_evaluation or None,
                    "outreach_draft": co.outreach_draft or None,
                    "outreach_subject": co.outreach_subject or None,
                    "relationship": co.relationship or None,
                    "relationship_notes": co.relationship_notes or None,
                    "updated_at": datetime.now().isoformat(),
                } for co in batch]
                resp = requests.post(
                    f"{supabase_url}/rest/v1/user_freelance_evaluations"
                    f"?on_conflict=user_id,company_id",
                    headers={**headers, "Prefer": "resolution=merge-duplicates"},
                    json=eval_records, timeout=60,
                )
                resp.raise_for_status()

            log.info(f"Supabase: upserted {len(to_sync)} user freelance evaluations (user_id={user_id[:8]}...)")

    except Exception as e:
        log.error(f"Supabase freelance sync failed: {e}")
        # Non-fatal — file-based results are already saved


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
# Benchmark infrastructure
# ---------------------------------------------------------------------------
def _get_freelance_benchmark_samples() -> list[tuple[CompanyProfile, str]]:
    """Return 8 synthetic companies with expected tiers for benchmark testing."""
    samples = [
        (CompanyProfile(
            name="Midwest Pro Audio",
            city="Chicago", state="IL",
            website="https://midwestproaudio.com",
            category="production_co",
            source="benchmark",
            description="Full-service live event production company specializing in corporate events, galas, and conferences. L-Acoustics K2/K3 certified, DiGiCo SD-range consoles, Shure Axient Digital wireless. 15 full-time staff, 40+ freelance crew. Based in Chicago with warehouse in Elk Grove Village.",
            recent_activity="[2026] Provided audio for Chicago Auto Show, multiple Fortune 500 product launches",
            scale_signals="L-Acoustics K2, K3, KS28 inventory, DiGiCo SD12, SD7, 40+ freelancers",
            notable_clients="Fortune 500 corporate events, Chicago Auto Show, major hotel ballrooms",
            gear_mentioned="L-Acoustics, DiGiCo, Shure Axient, Dante, KS28",
            website_about="Midwest Pro Audio is Chicago's premier live event production company. We provide full-service audio, video, and lighting for corporate events, galas, conferences, and concerts throughout the Midwest. Our inventory includes L-Acoustics K2 and K3 line arrays, DiGiCo SD-series consoles, and Shure Axient Digital wireless systems.",
        ), "HOT"),
        (CompanyProfile(
            name="National AV Partners",
            city="Chicago", state="IL",
            website="https://nationalavpartners.com",
            category="corporate_av",
            source="benchmark",
            description="National AV integrator with offices in 12 cities including Chicago. Provides managed AV services for Fortune 500 corporate campuses, hotel conference centers, and convention venues. Shure Axient, Crestron, Dante-networked systems.",
            recent_activity="[2026] Opened new Chicago office, hired 20 AV techs, expanding hotel portfolio",
            scale_signals="12 offices nationwide, 200+ employees, hotel and convention center contracts",
            notable_clients="Fortune 500 corporate campuses, major hotel chains, convention centers",
            gear_mentioned="Shure Axient, Crestron, Dante, QSC Q-Sys",
            website_about="National AV Partners delivers managed audiovisual services across the country. Our Chicago office serves corporate clients, hotels, and convention centers with Shure Axient Digital wireless, Crestron control, and Dante-networked audio systems.",
        ), "HOT"),
        (CompanyProfile(
            name="Heartland Sound & Light",
            city="Milwaukee", state="WI",
            website="https://heartlandsoundlight.com",
            category="av_rental",
            source="benchmark",
            description="Regional AV rental and production company serving Wisconsin and northern Illinois. Focus on lighting design and video production with some audio capability. JBL VTX, Yamaha CL5, basic Shure wireless.",
            recent_activity="[2025] Provided AV for several Milwaukee corporate events and wedding venues",
            scale_signals="JBL VTX line arrays, Yamaha CL5, 10 employees",
            notable_clients="Regional corporate events, Milwaukee venues",
            gear_mentioned="JBL VTX, Yamaha CL5, Shure ULXD",
            website_about="Heartland Sound & Light provides lighting, video, and audio rental services for events across Wisconsin and northern Illinois. We specialize in lighting design and video production.",
        ), "WARM"),
        (CompanyProfile(
            name="Pacific Event Productions",
            city="Los Angeles", state="CA",
            website="https://pacificeventprod.com",
            category="production_co",
            source="benchmark",
            description="Full-service event production company in Los Angeles. Large-scale corporate events, award shows, and concerts. L-Acoustics, DiGiCo, Shure Axient. 25 staff, extensive freelance crew.",
            recent_activity="[2026] Grammy after-parties, corporate product launches, tech conferences",
            scale_signals="L-Acoustics K1/K2, DiGiCo SD7/SD12, 25 staff, extensive crew",
            notable_clients="Grammy events, tech conferences, award shows",
            gear_mentioned="L-Acoustics, DiGiCo, Shure Axient, Waves",
            website_about="Pacific Event Productions is a Los Angeles-based full-service production company providing audio, video, and lighting for corporate events, award shows, and concerts. We carry L-Acoustics K1 and K2 line arrays, DiGiCo consoles, and Shure Axient Digital wireless.",
        ), "WARM"),
        (CompanyProfile(
            name="Home Theater Pros",
            city="Naperville", state="IL",
            website="https://hometheaterpros.com",
            category="corporate_av",
            source="benchmark",
            description="Residential AV integration company serving Chicago suburbs. Home theater installations, whole-home audio, smart home automation. Sonos, Control4, Samsung displays.",
            recent_activity="[2025] Installed home theaters in several luxury homes",
            scale_signals="5 employees, residential focus, Sonos, Control4",
            notable_clients="Residential homeowners",
            gear_mentioned="Sonos, Control4, Samsung",
            website_about="Home Theater Pros designs and installs custom home theater systems, whole-home audio, and smart home automation for residential clients in the Chicago suburbs. We are certified Sonos, Control4, and Samsung dealers.",
        ), "COLD"),
        (CompanyProfile(
            name="DJ Mike's Mobile Entertainment",
            city="Schaumburg", state="IL",
            website="https://djmikesmobile.com",
            category="production_co",
            source="benchmark",
            description="Mobile DJ and entertainment company for weddings, bar mitzvahs, and private parties. QSC K-series speakers, Pioneer DJ controller, basic Shure wireless mics.",
            recent_activity="[2025] DJ'd 40+ weddings, corporate holiday parties",
            scale_signals="1-person operation, QSC K-series, Pioneer DJ",
            notable_clients="Weddings, private parties",
            gear_mentioned="QSC K-series, Pioneer DJ, Shure BLX",
            website_about="DJ Mike's Mobile Entertainment provides DJ services and entertainment for weddings, bar mitzvahs, corporate parties, and private events in the Chicago suburbs.",
        ), "COLD"),
        (CompanyProfile(
            name="The Event Vendor Directory",
            city="", state="",
            website="https://eventvendordirectory.com",
            category="av_rental",
            source="benchmark",
            description="Find the best event vendors in your area. Browse AV rental companies, DJs, photographers, and caterers. Compare quotes and read reviews from verified clients.",
            recent_activity="",
            scale_signals="",
            notable_clients="",
            gear_mentioned="",
            website_about="The Event Vendor Directory is the #1 resource for finding event vendors. Browse categories including AV rental, DJ services, photography, catering, and more. Read reviews and compare quotes from verified vendors in your area.",
        ), "SKIP"),
        (CompanyProfile(
            name="Encore Global",
            city="Chicago", state="IL",
            website="https://encoreglobal.com",
            category="corporate_av",
            source="benchmark",
            description="Encore is the world's largest provider of event technology and production services, serving hotels and convention centers worldwide. Formerly PSAV.",
            recent_activity="[2026] Renewed contracts with major hotel chains, continued national expansion",
            scale_signals="5000+ employees, contracts in 1500+ hotels worldwide",
            notable_clients="Marriott, Hilton, Hyatt, convention centers",
            gear_mentioned="Mixed inventory, varies by venue",
            website_about="Encore, formerly PSAV, is the global leader in event technology and production services. We partner with premier hotels, resorts, and convention centers to deliver audiovisual solutions for meetings and events.",
        ), "SKIP"),
    ]
    return samples


def run_freelance_benchmark(config: dict, resume_text: str):
    """Run evaluation benchmark across multiple models using synthetic test companies."""
    samples = _get_freelance_benchmark_samples()
    candidate_models = [
        ("google_aistudio", "google/gemini-3-flash-preview"),
        ("openrouter", "qwen/qwen3.5-plus"),
        ("openrouter", "deepseek/deepseek-chat-v3-0324"),
        ("openrouter", "anthropic/claude-sonnet-4.6"),
    ]

    tier_order = {"HOT": 0, "WARM": 1, "COLD": 2, "SKIP": 3}

    def _tier_distance(actual: str, expected: str) -> float:
        """1.0 = exact match, 0.5 = adjacent tier, 0.0 = wrong."""
        a = tier_order.get(actual, -1)
        e = tier_order.get(expected, -1)
        if a == -1 or e == -1:
            return 0.0
        diff = abs(a - e)
        if diff == 0:
            return 1.0
        if diff == 1:
            return 0.5
        return 0.0

    console.print("\n[bold]Freelance Evaluation Benchmark[/bold]")
    console.print(f"  {len(samples)} synthetic companies × {len(candidate_models)} models\n")

    results_by_model: dict[str, list[dict]] = {}

    for provider, model_id in candidate_models:
        model_key = f"{provider}/{model_id}" if "/" not in model_id else model_id
        console.print(f"\n[bold cyan]Model: {model_key}[/bold cyan]")

        bench_config = dict(config)
        bench_config["llm_provider"] = provider
        bench_config["models"] = dict(config.get("models", {}))
        bench_config["models"]["freelance_eval"] = {"provider": provider, "model": model_id}

        evaluator = CompanyEvaluator(config=bench_config, resume_text=resume_text)
        if not evaluator.client:
            console.print(f"  [red]Could not initialize client for {model_key}[/red]")
            continue

        model_results = []
        for company, expected_tier in samples:
            try:
                result = evaluator.evaluate_company(company)
                actual_tier = result.get("fit_tier", "")
                score = _tier_distance(actual_tier, expected_tier)
                dims = result.get("dimensions", {})

                model_results.append({
                    "company": company.name,
                    "expected": expected_tier,
                    "actual": actual_tier,
                    "fit_score": result.get("fit_score", 0),
                    "score": score,
                    "dimensions": dims,
                    "reasoning": result.get("fit_reasoning", ""),
                })

                marker = "✓" if score == 1.0 else ("~" if score == 0.5 else "✗")
                style = "green" if score == 1.0 else ("yellow" if score == 0.5 else "red")
                console.print(
                    f"  [{style}]{marker}[/{style}] {company.name}: "
                    f"expected {expected_tier}, got {actual_tier} "
                    f"(geo={dims.get('geographic_fit', '?')} gear={dims.get('scale_gear', '?')} "
                    f"cred={dims.get('credibility', '?')})"
                )
            except Exception as e:
                log.error(f"Benchmark error for {company.name} on {model_key}: {e}")
                model_results.append({
                    "company": company.name, "expected": expected_tier,
                    "actual": "ERROR", "fit_score": 0, "score": 0.0,
                    "dimensions": {}, "reasoning": str(e),
                })

        results_by_model[model_key] = model_results

    # --- Generate markdown report ---
    report_lines = [
        "# Freelance Evaluation Benchmark Report",
        f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n## Summary\n",
    ]

    # Scorecard table
    report_lines.append("| Model | Score | Exact | Adjacent | Wrong |")
    report_lines.append("|-------|-------|-------|----------|-------|")

    for model_key, results in results_by_model.items():
        total_score = sum(r["score"] for r in results)
        exact = sum(1 for r in results if r["score"] == 1.0)
        adjacent = sum(1 for r in results if r["score"] == 0.5)
        wrong = sum(1 for r in results if r["score"] == 0.0)
        report_lines.append(
            f"| {model_key} | {total_score:.1f}/{len(results)} | {exact} | {adjacent} | {wrong} |"
        )

    # Per-model detail
    for model_key, results in results_by_model.items():
        total_score = sum(r["score"] for r in results)
        report_lines.append(f"\n## {model_key} ({total_score:.1f}/{len(results)})\n")
        report_lines.append("| Company | Expected | Actual | Score | Geo | Gear | Work | Rel | Cred |")
        report_lines.append("|---------|----------|--------|-------|-----|------|------|-----|------|")
        for r in results:
            d = r["dimensions"]
            marker = "✓" if r["score"] == 1.0 else ("~" if r["score"] == 0.5 else "✗")
            report_lines.append(
                f"| {r['company']} | {r['expected']} | {r['actual']} | {marker} | "
                f"{d.get('geographic_fit', '-')} | {d.get('scale_gear', '-')} | "
                f"{d.get('work_type', '-')} | {d.get('relationship_potential', '-')} | "
                f"{d.get('credibility', '-')} |"
            )

    # Distribution analysis on real companies from cache
    if FREELANCE_CACHE_PATH.exists():
        try:
            with open(FREELANCE_CACHE_PATH) as f:
                cache = json.load(f)
            tier_counts = {"HOT": 0, "WARM": 0, "COLD": 0, "SKIP": 0}
            for entry in cache.values():
                t = entry.get("fit_tier", "")
                if t in tier_counts:
                    tier_counts[t] += 1
            total_cached = sum(tier_counts.values())
            if total_cached > 0:
                report_lines.append(f"\n## Current Cache Distribution ({total_cached} companies)\n")
                for tier, count in tier_counts.items():
                    pct = count / total_cached * 100
                    report_lines.append(f"- **{tier}**: {count} ({pct:.0f}%)")
        except Exception:
            pass

    report_path = FREELANCE_DIR / "benchmark_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))

    console.print(f"\n[bold green]Benchmark report saved to {report_path}[/bold green]")

    # Print summary table
    table = Table(title="Benchmark Results")
    table.add_column("Model", width=40)
    table.add_column("Score", width=10)
    table.add_column("Exact", width=8)
    table.add_column("Adjacent", width=10)
    table.add_column("Wrong", width=8)

    for model_key, results in results_by_model.items():
        total_score = sum(r["score"] for r in results)
        exact = sum(1 for r in results if r["score"] == 1.0)
        adjacent = sum(1 for r in results if r["score"] == 0.5)
        wrong = sum(1 for r in results if r["score"] == 0.0)
        style = "green" if total_score >= 7 else ("yellow" if total_score >= 5 else "red")
        table.add_row(
            model_key,
            f"[{style}]{total_score:.1f}/{len(results)}[/{style}]",
            str(exact), str(adjacent), str(wrong),
        )
    console.print(table)


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
    parser.add_argument(
        "--benchmark", action="store_true",
        help="Run evaluation benchmark across multiple models using synthetic test companies",
    )
    args = parser.parse_args()

    config = load_config()
    freelance_cfg = config.get("freelance_search", {})
    resume_text = load_resume(config)

    if args.benchmark:
        run_freelance_benchmark(config, resume_text)
        return

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

        # Enforce max_companies cap after dedup + filtering
        if max_companies and len(companies) > max_companies:
            log.info(f"Capping {len(companies)} companies to max_companies={max_companies}")
            companies = companies[:max_companies]

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

    # --- HubSpot enrichment (optional, non-blocking) ---
    hs_client = None
    hubspot_config = freelance_cfg.get("hubspot", {})
    if hubspot_config.get("enabled"):
        hs_token = hubspot_config.get("access_token") or os.environ.get("HUBSPOT_ACCESS_TOKEN")
        if hs_token:
            from hubspot_client import HubSpotClient
            hs_client = HubSpotClient(access_token=hs_token)
            console.print("\n[bold]Enriching companies via HubSpot...[/bold]")
            enriched = 0
            for co in companies:
                domain = urlparse(co.website).netloc.removeprefix("www.") if co.website else ""
                if not domain:
                    continue
                hs_data = hs_client.enrich(domain)
                if hs_data:
                    co.hubspot_employees = hs_data.get("hubspot_employees")
                    co.hubspot_revenue = hs_data.get("hubspot_revenue")
                    co.hubspot_industry = hs_data.get("hubspot_industry")
                    co.hubspot_linkedin_url = hs_data.get("hubspot_linkedin_url")
                    co.hubspot_company_id = hs_data.get("hubspot_company_id")
                    enriched += 1
            console.print(f"  HubSpot enriched {enriched}/{len(companies)} companies")

    # --- Evaluate ---
    outreach_min_tier = args.min_tier or freelance_cfg.get("outreach_min_tier", "warm")
    companies = run_evaluate_companies(
        companies, config, resume_text,
        no_outreach=args.no_outreach,
        outreach_min_tier=outreach_min_tier,
    )

    # Post-evaluation dedup: LLM name corrections can create company_id collisions
    seen_ids: dict[str, CompanyProfile] = {}
    for co in companies:
        seen_ids[co.company_id] = co  # last wins
    if len(seen_ids) < len(companies):
        log.info(f"Post-eval dedup: {len(companies)} → {len(seen_ids)} (removed {len(companies) - len(seen_ids)} collisions)")
        companies = list(seen_ids.values())

    # --- Save & report ---
    json_path, csv_path, md_path = save_freelance_results(companies)
    sync_freelance_to_supabase(config, companies)

    # --- HubSpot CRM sync (after evaluation) ---
    if hs_client and hubspot_config.get("sync_to_crm", True):
        console.print("\n[bold]Syncing to HubSpot CRM...[/bold]")
        synced = 0
        for co in companies:
            if co.fit_tier in ("SKIP", None):
                continue
            try:
                domain = urlparse(co.website).netloc.removeprefix("www.") if co.website else ""
                if not domain:
                    continue
                lifecycle = "customer" if co.relationship in ("known_partner", "known_client") else "lead"
                hs_id = hs_client.upsert_company(
                    domain=domain, name=co.name, city=co.city, state=co.state,
                    category=co.category, fit_tier=co.fit_tier,
                    fit_score=co.fit_score, lifecycle_stage=lifecycle,
                )
                co.hubspot_company_id = hs_id
                # Log outreach draft as a note if one was generated
                if co.outreach_draft and co.fit_tier in ("HOT", "WARM"):
                    hs_client.log_outreach(
                        hs_id,
                        subject=co.outreach_subject or "Intro",
                        body=co.outreach_draft,
                    )
                synced += 1
            except Exception as e:
                log.warning(f"HubSpot CRM sync failed for {co.name}: {e}")
        console.print(f"  Synced {synced} companies to HubSpot CRM")

    print_freelance_summary(companies)
    console.print(f"\n[bold green]Done![/bold green]")
    console.print(f"  Summary: {md_path}")
    console.print(f"  CSV:     {csv_path}")
    console.print(f"  JSON:    {json_path}")


if __name__ == "__main__":
    main()
