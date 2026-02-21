"""Data models for the job-search pipeline."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    url: str
    source: str  # serpapi, indeed_rss, avixa, career_page
    description: str = ""
    salary: str = ""
    date_posted: str = ""
    date_scraped: str = field(default_factory=lambda: datetime.now().isoformat())
    job_id: str = ""  # dedupe hash
    match_score: int = 0
    match_reasoning: str = ""
    match_verdict: str = ""  # STRONG / MODERATE / STRETCH / WEAK
    full_evaluation: str = ""  # Full structured evaluation text
    tier: str = ""  # From target company list
    job_summary: str = ""  # 2-sentence summary of the role itself
    source_query: str = ""  # Search query that found this result (not in job_id hash)

    @staticmethod
    def _normalize_location(loc: str) -> str:
        """Normalize location for dedup — strip country suffixes, translations, extra whitespace."""
        import re as _re
        # Remove common country suffixes (English, Spanish, Portuguese, etc.)
        loc = _re.sub(
            r',?\s*(United States|USA|US|Estados Unidos|Est\w+\s+Uni\w+)$',
            '', loc, flags=_re.IGNORECASE,
        ).strip().rstrip(',').strip()
        # Collapse whitespace
        loc = _re.sub(r'\s+', ' ', loc)
        return loc

    def __post_init__(self):
        if not self.job_id:
            norm_loc = self._normalize_location(self.location)
            raw = f"{self.title}|{self.company}|{norm_loc}".lower().strip()
            self.job_id = hashlib.md5(raw.encode()).hexdigest()[:12]


def _normalize_date_posted(raw: str) -> str:
    """Convert date_posted from various formats to YYYY-MM-DD."""
    if not raw:
        return ""
    raw = raw.strip()
    raw_lower = raw.lower()

    # Relative: "3 days ago", "1 week ago", "just posted", "today"
    if "ago" in raw_lower or raw_lower in ("today", "just posted", "just now"):
        days = 0
        m = re.search(r'(\d+)\s*(day|hour|minute)', raw_lower)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if unit == "day":
                days = n
            # hours/minutes = today
        elif "week" in raw_lower:
            m2 = re.search(r'(\d+)', raw_lower)
            days = int(m2.group(1)) * 7 if m2 else 7
        elif "month" in raw_lower:
            m2 = re.search(r'(\d+)', raw_lower)
            days = int(m2.group(1)) * 30 if m2 else 30
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Already ISO format
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw

    # Try common date formats
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw[:30], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # RFC 2822 (Indeed RSS: "Thu, 20 Feb 2026 12:00:00 GMT")
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except Exception:
        pass

    return raw  # return as-is if unparseable
