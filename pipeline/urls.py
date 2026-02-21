"""URL scoring, selection, and resolution helpers for the job-search pipeline."""

from urllib.parse import urlparse

import requests


# Direct employer ATS platforms -- highest quality apply links
ATS_DOMAINS = {"greenhouse.io", "lever.co", "myworkdayjobs.com", "icims.com",
               "smartrecruiters.com", "ashbyhq.com", "breezy.hr", "jobvite.com"}

# Aggregator / recruiter intermediaries -- deprioritized
AGGREGATOR_DOMAINS = {"indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
                      "dice.com", "monster.com", "careerbuilder.com", "simplyhired.com",
                      "teal.com", "adzuna.com", "talent.com", "jooble.org"}


def _url_domain_score(url: str) -> int:
    """Score a URL by its domain: ATS -> 100, unknown -> 50, aggregator -> 10."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return 0
    host = host.lower()
    for domain in ATS_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return 100
    for domain in AGGREGATOR_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return 10
    return 50


def _pick_best_apply_url(options: list[dict], fallback: str = "") -> str:
    """Pick the best apply URL from a list of {link, title} dicts."""
    if not options:
        return fallback
    best_url = fallback
    best_score = -1
    for opt in options:
        link = opt.get("link", "")
        if not link:
            continue
        score = _url_domain_score(link)
        if score > best_score:
            best_score = score
            best_url = link
    return best_url or fallback


def _is_indirect_url(url: str) -> bool:
    """Check if a URL is a Google search link or aggregator that likely redirects."""
    if not url:
        return False
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    # Google Jobs deep links
    if ("google.com" in host or "google.co" in host) and "ibp=htl" in url:
        return True
    for domain in AGGREGATOR_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _resolve_apply_url(url: str) -> str:
    """Follow redirects via HEAD request to get the final employer URL."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5,
                             headers={"User-Agent": "Mozilla/5.0"})
        final = resp.url
        # Only use the resolved URL if it looks better than what we started with
        if final and _url_domain_score(final) >= _url_domain_score(url):
            return final
    except Exception:
        pass
    return url
