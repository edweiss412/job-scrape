"""SerpAPI Google Jobs scraper."""

import time

import requests

from pipeline.config import log
from pipeline.models import JobListing, _normalize_date_posted
from pipeline.urls import _pick_best_apply_url, _is_indirect_url, _resolve_apply_url


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
            source="external", category="search_api", pipeline="job_scraper", operation="serpapi_search",
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
                date_posted=_normalize_date_posted(item.get("detected_extensions", {}).get("posted_at", "")),
                source_query=query,
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict) -> list[JobListing]:
        all_jobs = []
        default_locations = config["search"]["locations"]
        query_groups = config["queries"]

        for group_name, group_data in query_groups.items():
            # Skip user-derived groups — these run via BrightData only (budget protection)
            if group_name.startswith("user_derived_"):
                continue
            # Support per-group location overrides and new dict format
            if isinstance(group_data, dict):
                queries = group_data.get("queries", [])
                group_locations = group_data.get("locations") or default_locations
            else:
                queries = group_data  # backward compat: bare list
                group_locations = default_locations
            for query in queries:
                for location in group_locations:
                    if self._rate_limited:
                        log.warning("SerpAPI rate-limited — stopping queries")
                        return all_jobs
                    jobs = self.search(query, location)
                    all_jobs.extend(jobs)
                    time.sleep(1)  # Rate limiting

        return all_jobs
