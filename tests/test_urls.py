"""Tests for URL scoring and resolution helpers."""
from job_scraper import _url_domain_score, _pick_best_apply_url, _is_indirect_url


class TestUrlDomainScore:
    def test_ats_domain_scores_100(self):
        assert _url_domain_score("https://boards.greenhouse.io/company/jobs/123") == 100

    def test_aggregator_scores_10(self):
        assert _url_domain_score("https://www.indeed.com/viewjob?jk=abc") == 10

    def test_unknown_domain_scores_50(self):
        assert _url_domain_score("https://company.com/careers/123") == 50

    def test_empty_url_scores_50(self):
        # Empty URL parses with hostname=None, no domain match, falls through to 50
        assert _url_domain_score("") == 50


class TestPickBestApplyUrl:
    def test_prefers_ats_over_aggregator(self):
        options = [
            {"link": "https://www.indeed.com/viewjob?jk=abc", "title": "Indeed"},
            {"link": "https://boards.greenhouse.io/co/jobs/1", "title": "Greenhouse"},
        ]
        assert "greenhouse.io" in _pick_best_apply_url(options)

    def test_returns_fallback_when_empty(self):
        assert _pick_best_apply_url([], fallback="http://fallback.com") == "http://fallback.com"


class TestIsIndirectUrl:
    def test_google_jobs_deep_link(self):
        assert _is_indirect_url("https://www.google.com/search?ibp=htl;jobs&q=av+tech") is True

    def test_indeed_is_indirect(self):
        assert _is_indirect_url("https://www.indeed.com/viewjob?jk=abc") is True

    def test_direct_employer_not_indirect(self):
        assert _is_indirect_url("https://company.com/careers/123") is False

    def test_empty_url(self):
        assert _is_indirect_url("") is False
