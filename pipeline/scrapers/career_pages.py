"""Direct career page scraper for target companies."""

import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from pipeline.config import log
from pipeline.models import JobListing


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
                    "lighting", "show control", "stage", "rigging",
                    "projection", "projectionist", "technical director", "live event",
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
                    source_query=name,
                )
                jobs.append(job)

        log.info(f"  → Found {len(jobs)} AV-relevant results")
        return jobs

    def run_all_pages(self, config: dict) -> list[JobListing]:
        all_jobs = []
        zero_result_companies = []
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
                if not jobs:
                    zero_result_companies.append(company["name"])
                all_jobs.extend(jobs)
                time.sleep(1)  # Be polite

        if zero_result_companies:
            log.warning(
                f"Career page scraper: {len(zero_result_companies)} companies returned 0 results "
                f"(may need selector updates): {', '.join(zero_result_companies)}"
            )
        # Store for inclusion in scrape_runs metadata
        self._zero_result_companies = zero_result_companies

        return all_jobs
