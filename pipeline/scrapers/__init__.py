"""Scraper classes, description fetching, and the run_scrape() orchestrator."""

from pipeline.config import console, log
from pipeline.dedup import deduplicate_jobs

from pipeline.scrapers.serpapi import SerpAPIScraper
from pipeline.scrapers.brightdata import BrightDataScraper
from pipeline.scrapers.indeed import IndeedRSSScraper
from pipeline.scrapers.avixa import AVIXAScraper
from pipeline.scrapers.career_pages import CareerPageScraper
from pipeline.scrapers.jobspy import JobSpyScraper
from pipeline.scrapers.descriptions import (
    fetch_job_description,
    fetch_descriptions_batch,
    backfill_missing_descriptions,
)


def run_scrape(config: dict, quick: bool = False):
    """Run the scraping pipeline."""
    from pipeline.models import JobListing  # noqa: F401 — used by callers

    all_jobs = []

    # Source 1: Google Jobs (SerpAPI -> BrightData fallback)
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


__all__ = [
    "SerpAPIScraper",
    "BrightDataScraper",
    "IndeedRSSScraper",
    "AVIXAScraper",
    "CareerPageScraper",
    "JobSpyScraper",
    "run_scrape",
    "fetch_job_description",
    "fetch_descriptions_batch",
    "backfill_missing_descriptions",
]
