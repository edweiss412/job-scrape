"""Tests for keyword scoring in the pre-filter system."""
from job_scraper import JobListing, _keyword_score_job


def _job(title="AV Tech", company="ACME", description=""):
    return JobListing(title=title, company=company, location="Dallas, TX",
                      url="http://x.com", source="test", description=description)


class TestKeywordScoreJob:
    def test_relevant_title_scores_positive(self):
        score, matched = _keyword_score_job(_job(title="Audio Visual Technician"))
        assert score > 0
        assert len(matched) > 0

    def test_irrelevant_title_scores_negative(self):
        score, matched = _keyword_score_job(_job(
            title="Software Engineer",
            description="Build web applications with React and Node.js"
        ))
        assert score == -1.0

    def test_target_company_auto_passes(self):
        score, matched = _keyword_score_job(_job(title="Technician", company="AVI-SPL"))
        assert score == 1.0

    def test_no_signal_scores_zero(self):
        score, matched = _keyword_score_job(_job(title="Manager", company="Unknown Co"))
        assert score == 0.0

    def test_description_av_terms_boost_score(self):
        desc = "Experience with Crestron, Dante, and QSC audio systems required"
        score, _ = _keyword_score_job(_job(title="Technician", description=desc))
        assert score > 0

    def test_irrelevant_title_rescued_by_av_description(self):
        desc = "Must know Dante, Crestron, and Extron systems for AV installation"
        score, matched = _keyword_score_job(_job(title="Software Engineer", description=desc))
        assert score == 0.3
        assert any("ambiguous" in m for m in matched)
