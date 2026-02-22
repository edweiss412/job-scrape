"""Indeed RSS feed scraper."""

import time
from urllib.parse import urlencode

import feedparser
from bs4 import BeautifulSoup

from pipeline.config import log
from pipeline.models import JobListing, _normalize_date_posted


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
                date_posted=_normalize_date_posted(entry.get("published", "")),
                source_query=query,
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict) -> list[JobListing]:
        if not config.get("indeed", {}).get("enabled", True):
            return []

        all_jobs = []
        queries = config.get("indeed", {}).get("queries", [])
        locations = list(config["search"]["locations"])
        # Merge user-derived locations, deduplicating with normalization
        from pipeline.orchestrator import _normalize_location_str
        existing_norm = {_normalize_location_str(l).lower() for l in locations}
        for loc in config.get("_user_locations", []):
            norm = _normalize_location_str(loc).lower()
            if norm not in existing_norm:
                locations.append(loc)
                existing_norm.add(norm)

        for query in queries:
            for location in locations:
                jobs = self.search(query, location)
                all_jobs.extend(jobs)
                time.sleep(0.5)

        return all_jobs
