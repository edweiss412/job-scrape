"""Deduplication logic for scraped job listings."""

import re
from urllib.parse import urlparse, parse_qs, urlunparse

from pipeline.config import log
from pipeline.models import JobListing
from pipeline.urls import _is_indirect_url


def _url_dedup_key(url: str) -> str:
    """Strip tracking params to get a canonical URL for dedup."""
    if not url:
        return ""
    try:
        p = urlparse(url.lower().rstrip('/'))
        # For Indeed, the jk param is the unique job key
        if 'indeed.com' in (p.hostname or ''):
            qs = parse_qs(p.query)
            if 'jk' in qs:
                return f"indeed:{qs['jk'][0]}"
        # For LinkedIn, the job ID is in the path
        if 'linkedin.com' in (p.hostname or '') and '/jobs/view/' in p.path:
            return f"linkedin:{p.path.rstrip('/')}"
        # Generic: scheme + host + path (drop all query params)
        return urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
    except Exception:
        return url.lower().strip()


def _location_specificity_str(loc: str) -> int:
    """More specific locations (city, state) score higher than generic ones."""
    loc = loc.lower().strip()
    if not loc or loc in ('united states', 'usa', 'us', 'remote'):
        return 0
    parts = [p.strip() for p in loc.replace(';', ',').split(',') if p.strip()]
    return len(parts)


def _normalize_company(name: str) -> str:
    """Normalize company name for fuzzy dedup."""
    name = name.lower().strip()
    # Strip common suffixes
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc",
                   ", ltd", " ltd", " corp.", " corp", " corporation",
                   " company", " co.", " co", " careers", " jobs"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _normalize_title_words(title: str) -> set[str]:
    """Extract meaningful words from a title for fuzzy comparison."""
    title = re.sub(r'[^\w\s]', ' ', title.lower())
    stopwords = {
        'a', 'an', 'the', 'and', 'or', 'of', 'for', 'in', 'at', 'to',
        'is', 'with', 'on', 'by', '-', '\u2013', '\u2014', '&', 'i', 'ii', 'iii',
        'sr', 'senior', 'jr', 'junior', 'lead', 'principal', 'staff',
        'associate', 'level', 'new', 'open',
    }
    # Normalize AV-industry synonyms before splitting
    synonyms = {
        'audiovisual': 'av', 'audio visual': 'av', 'a v': 'av',
        'technician': 'tech', 'specialist': 'spec',
        'information technology': 'it',
    }
    for old, new in synonyms.items():
        title = title.replace(old, new)
    return {w for w in title.split() if w and w not in stopwords and len(w) > 1}


def deduplicate_jobs(jobs: list[JobListing]) -> list[JobListing]:
    """Remove duplicate listings using exact hash, then fuzzy matching for aggregator echoes."""
    # Pass 1: exact job_id dedup
    seen = {}
    for job in jobs:
        if job.job_id not in seen:
            seen[job.job_id] = job
        else:
            existing = seen[job.job_id]
            if len(job.description) > len(existing.description):
                seen[job.job_id] = job
            elif len(job.description) == len(existing.description) and _is_indirect_url(existing.url) and not _is_indirect_url(job.url):
                seen[job.job_id] = job
            elif job.tier and not existing.tier:
                seen[job.job_id] = job

    exact_deduped = list(seen.values())
    exact_count = len(jobs) - len(exact_deduped)

    # Pass 2: URL dedup -- identical normalized URLs are the same posting regardless
    # of location text differences (e.g. "United States" vs "San Francisco, CA").
    url_groups: dict[str, list[JobListing]] = {}
    for job in exact_deduped:
        uk = _url_dedup_key(job.url)
        if uk:
            url_groups.setdefault(uk, []).append(job)
        else:
            url_groups.setdefault(f"__no_url_{id(job)}", []).append(job)

    url_deduped = []
    url_count = 0
    for group in url_groups.values():
        if len(group) == 1:
            url_deduped.append(group[0])
            continue
        # Keep the version with: most specific location > longest description > direct URL
        group.sort(key=lambda j: (
            _location_specificity_str(j.location),
            len(j.description),
            0 if _is_indirect_url(j.url) else 1,
        ), reverse=True)
        url_deduped.append(group[0])
        url_count += len(group) - 1

    # Pass 3: fuzzy dedup -- catch aggregator rewrites (same company + location + salary,
    # with overlapping title words). Keep the version with the longest description.
    fuzzy_groups = {}  # (norm_company, norm_location, salary) -> list of jobs
    for job in url_deduped:
        norm_company = _normalize_company(job.company)
        norm_loc = JobListing._normalize_location(job.location).lower()
        # Use salary as an additional signal (aggregators preserve salary)
        salary_key = re.sub(r'[^\d]', '', job.salary)[:6] if job.salary else ""
        key = (norm_company, norm_loc, salary_key)
        fuzzy_groups.setdefault(key, []).append(job)

    final = []
    fuzzy_merged = 0
    for key, group in fuzzy_groups.items():
        if len(group) == 1 or not key[0]:  # single job or no company name
            final.extend(group)
            continue

        # Within each group, check title word overlap
        merged_indices = set()
        for i, job_a in enumerate(group):
            if i in merged_indices:
                continue
            words_a = _normalize_title_words(job_a.title)
            for j in range(i + 1, len(group)):
                if j in merged_indices:
                    continue
                words_b = _normalize_title_words(group[j].title)
                # If titles share 70%+ of meaningful words and have 2+ words, likely same role
                if words_a and words_b:
                    overlap = len(words_a & words_b)
                    min_words = min(len(words_a), len(words_b))
                    if min_words >= 2 and overlap / min_words > 0.7:
                        # Keep the one with more description, or better URL
                        merged_indices.add(j)
                        if len(group[j].description) > len(job_a.description):
                            group[i] = group[j]
                            job_a = group[i]
                            words_a = _normalize_title_words(job_a.title)
                        elif len(group[j].description) == len(job_a.description) and _is_indirect_url(job_a.url) and not _is_indirect_url(group[j].url):
                            group[i] = group[j]
                            job_a = group[i]
                            words_a = _normalize_title_words(job_a.title)
                        fuzzy_merged += 1

        for i, job in enumerate(group):
            if i not in merged_indices:
                final.append(job)

    log.info(
        f"Deduplicated: {len(jobs)} \u2192 {len(final)} unique listings "
        f"({exact_count} exact, {url_count} url, {fuzzy_merged} fuzzy)"
    )
    return final
