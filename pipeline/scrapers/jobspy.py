"""JobSpy scraper (free direct scraping of Indeed, Glassdoor, Google, ZipRecruiter)."""

import time

from pipeline.config import log
from pipeline.models import JobListing, _normalize_date_posted


class JobSpyScraper:
    """
    Uses the python-jobspy library to scrape job listings directly from
    Indeed, LinkedIn, Glassdoor, Google Jobs, and ZipRecruiter.
    No API key needed. Indeed has no rate limiting.
    """

    def search(self, query: str, location: str, config: dict) -> list[JobListing]:
        try:
            from jobspy import scrape_jobs  # type: ignore
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
                date_posted=_normalize_date_posted(str(row.get("date_posted", "")) if str(row.get("date_posted", "")) != "nan" else ""),
                source_query=query,
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
                jobs = self.search(query, location, config)
                all_jobs.extend(jobs)
                time.sleep(2)  # Be polite between queries

        return all_jobs
