"""Tests for deduplication logic."""
from job_scraper import (
    JobListing, deduplicate_jobs,
    _url_dedup_key, _normalize_company, _normalize_title_words,
    _location_specificity_str,
)


def _job(title="AV Tech", company="ACME", location="Dallas, TX",
         url="http://example.com/1", source="test", description="", salary=""):
    return JobListing(title=title, company=company, location=location,
                      url=url, source=source, description=description, salary=salary)


class TestUrlDedupKey:
    def test_indeed_extracts_jk_param(self):
        assert _url_dedup_key("https://www.indeed.com/viewjob?jk=abc123&from=rss") == "indeed:abc123"

    def test_linkedin_extracts_path(self):
        key = _url_dedup_key("https://www.linkedin.com/jobs/view/12345/?refId=abc")
        assert key == "linkedin:/jobs/view/12345"

    def test_generic_strips_query_params(self):
        key = _url_dedup_key("https://company.com/jobs/123?utm_source=google")
        assert key == "https://company.com/jobs/123"

    def test_empty_url(self):
        assert _url_dedup_key("") == ""


class TestNormalizeCompany:
    def test_strips_inc(self):
        assert _normalize_company("ACME, Inc.") == "acme"

    def test_strips_llc(self):
        assert _normalize_company("Company LLC") == "company"

    def test_strips_careers(self):
        assert _normalize_company("Company Careers") == "company"


class TestNormalizeTitleWords:
    def test_extracts_meaningful_words(self):
        words = _normalize_title_words("Senior AV Technician")
        assert "av" in words
        assert "tech" in words
        assert "senior" not in words

    def test_normalizes_audiovisual(self):
        words = _normalize_title_words("Audiovisual Engineer")
        assert "av" in words


class TestLocationSpecificity:
    def test_city_state_scores_2(self):
        assert _location_specificity_str("Dallas, TX") == 2

    def test_country_only_scores_0(self):
        assert _location_specificity_str("United States") == 0

    def test_remote_scores_0(self):
        assert _location_specificity_str("Remote") == 0


class TestDeduplicateJobs:
    def test_removes_exact_duplicates(self):
        jobs = [_job(), _job()]
        result = deduplicate_jobs(jobs)
        assert len(result) == 1

    def test_keeps_version_with_longer_description(self):
        a = _job(description="short")
        b = _job(description="this is a much longer description of the role")
        result = deduplicate_jobs([a, b])
        assert len(result) == 1
        assert result[0].description == b.description

    def test_url_dedup_across_locations(self):
        a = _job(location="United States", url="https://co.com/jobs/1")
        b = _job(location="Dallas, TX", url="https://co.com/jobs/1")
        result = deduplicate_jobs([a, b])
        assert len(result) == 1
        assert result[0].location == "Dallas, TX"

    def test_different_jobs_preserved(self):
        a = _job(title="AV Tech", company="ACME")
        b = _job(title="Sound Engineer", company="Other Corp", url="http://example.com/2")
        result = deduplicate_jobs([a, b])
        assert len(result) == 2
