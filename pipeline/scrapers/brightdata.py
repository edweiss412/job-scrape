"""BrightData SERP API Google Jobs scraper."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from pipeline.config import log
from pipeline.models import JobListing, _normalize_date_posted
from pipeline.urls import _pick_best_apply_url, _is_indirect_url, _resolve_apply_url


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

        from pipeline_utils import log_api_usage
        log_api_usage(
            source="external", category="search_api", pipeline="job_scraper", operation="brightdata_serp",
            provider="brightdata", cost_usd=0.003, success=True,
            http_status=resp.status_code,
        )

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
                date_posted=_normalize_date_posted(posted_at),
                source_query=query,
            )
            jobs.append(job)

        log.info(f"  → Found {len(jobs)} results")
        return jobs

    def run_all_queries(self, config: dict, max_workers: int = 6) -> list[JobListing]:
        default_locations = config["search"]["locations"]
        query_groups = config["queries"]

        # Build list of (query, location) pairs — support per-group location overrides
        tasks = []
        for group_name, group_data in query_groups.items():
            if isinstance(group_data, dict):
                queries = group_data.get("queries", [])
                group_locations = group_data.get("locations") or default_locations
            else:
                queries = group_data  # backward compat: bare list
                group_locations = default_locations
            for query in queries:
                for location in group_locations:
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
