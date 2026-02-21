"""AVIXA Career Center scraper."""

import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from pipeline.config import log
from pipeline.models import JobListing


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
                source_query=keyword,
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
