"""Tests for JobListing data model and date normalization."""
from job_scraper import JobListing, _normalize_date_posted


class TestJobListing:
    def test_job_id_generated_from_title_company_location(self):
        job = JobListing(title="AV Tech", company="ACME", location="Dallas, TX", url="http://x.com", source="test")
        assert job.job_id
        assert len(job.job_id) == 12

    def test_same_inputs_produce_same_job_id(self):
        a = JobListing(title="AV Tech", company="ACME", location="Dallas, TX", url="http://a.com", source="test")
        b = JobListing(title="AV Tech", company="ACME", location="Dallas, TX", url="http://b.com", source="test")
        assert a.job_id == b.job_id

    def test_different_titles_produce_different_job_ids(self):
        a = JobListing(title="AV Tech", company="ACME", location="Dallas, TX", url="http://x.com", source="test")
        b = JobListing(title="Sound Engineer", company="ACME", location="Dallas, TX", url="http://x.com", source="test")
        assert a.job_id != b.job_id

    def test_normalize_location_strips_country(self):
        assert JobListing._normalize_location("Dallas, TX, United States") == "Dallas, TX"
        assert JobListing._normalize_location("Dallas, TX, USA") == "Dallas, TX"

    def test_normalize_location_collapses_whitespace(self):
        assert JobListing._normalize_location("Dallas,  TX") == "Dallas, TX"

    def test_explicit_job_id_not_overwritten(self):
        job = JobListing(title="X", company="Y", location="Z", url="http://x.com", source="test", job_id="custom123")
        assert job.job_id == "custom123"


class TestNormalizeDatePosted:
    def test_empty_string(self):
        assert _normalize_date_posted("") == ""

    def test_already_iso(self):
        assert _normalize_date_posted("2026-02-20") == "2026-02-20"

    def test_relative_days_ago(self):
        result = _normalize_date_posted("3 days ago")
        assert len(result) == 10 and result[4] == "-"

    def test_today(self):
        from datetime import datetime
        result = _normalize_date_posted("today")
        assert result == datetime.now().strftime("%Y-%m-%d")

    def test_rfc_2822(self):
        result = _normalize_date_posted("Thu, 20 Feb 2026 12:00:00 GMT")
        assert result == "2026-02-20"

    def test_month_day_year(self):
        assert _normalize_date_posted("February 20, 2026") == "2026-02-20"

    def test_unparseable_returned_as_is(self):
        assert _normalize_date_posted("sometime soon") == "sometime soon"
