"""Tests for HubSpot client module."""
import pytest
from unittest.mock import patch, MagicMock
from hubspot.crm.companies import ApiException

from hubspot_client import HubSpotClient


@pytest.fixture
def client():
    """Create a HubSpotClient with a fake token."""
    with patch("hubspot_client.hubspot.Client.create") as mock_create:
        mock_create.return_value = MagicMock()
        c = HubSpotClient(access_token="fake-token")
    return c


# --- enrich() tests ---


class TestEnrich:
    def test_returns_data_when_company_found(self, client):
        """enrich returns enrichment dict when company exists in HubSpot."""
        mock_company = MagicMock()
        mock_company.id = "12345"
        mock_company.properties = {
            "numberofemployees": "150",
            "annualrevenue": "5000000",
            "industry": "Audio Visual",
            "linkedin_company_page": "https://linkedin.com/company/acme",
        }
        with patch.object(client, "_search_by_domain", return_value=mock_company):
            result = client.enrich("acme.com")

        assert result == {
            "hubspot_employees": 150,
            "hubspot_revenue": "5000000",
            "hubspot_industry": "Audio Visual",
            "hubspot_linkedin_url": "https://linkedin.com/company/acme",
            "hubspot_company_id": "12345",
        }

    def test_returns_empty_dict_when_not_found(self, client):
        """enrich returns {} when domain not in HubSpot."""
        with patch.object(client, "_search_by_domain", return_value=None):
            result = client.enrich("unknown-domain.com")

        assert result == {}

    def test_returns_empty_dict_on_api_error(self, client):
        """enrich returns {} on any exception (never raises)."""
        with patch.object(
            client, "_search_by_domain", side_effect=ApiException(status=500)
        ):
            result = client.enrich("error-domain.com")

        assert result == {}

    def test_handles_none_employee_count(self, client):
        """enrich handles None/missing employee count gracefully."""
        mock_company = MagicMock()
        mock_company.id = "99999"
        mock_company.properties = {
            "numberofemployees": None,
            "annualrevenue": None,
            "industry": "Technology",
            "linkedin_company_page": None,
        }
        with patch.object(client, "_search_by_domain", return_value=mock_company):
            result = client.enrich("nullco.com")

        assert result["hubspot_employees"] is None
        assert result["hubspot_revenue"] is None
        assert result["hubspot_linkedin_url"] is None
        assert result["hubspot_industry"] == "Technology"
        assert result["hubspot_company_id"] == "99999"


# --- upsert_company() tests ---


class TestUpsertCompany:
    def test_creates_new_when_not_found(self, client):
        """upsert_company creates a new company when domain not found."""
        mock_created = MagicMock()
        mock_created.id = "new-id-123"

        with (
            patch.object(client, "_search_by_domain", return_value=None),
            patch.object(client, "_create_company", return_value=mock_created) as mock_create,
        ):
            result = client.upsert_company(
                domain="newco.com",
                name="NewCo",
                city="Nashville",
                state="TN",
                category="av_integrator",
                fit_tier="HOT",
                fit_score=88,
            )

        assert result == "new-id-123"
        mock_create.assert_called_once()
        call_props = mock_create.call_args[0][0]
        assert call_props["domain"] == "newco.com"
        assert call_props["name"] == "NewCo"
        assert call_props["city"] == "Nashville"
        assert call_props["state"] == "TN"
        assert call_props["industry"] == "av_integrator"
        assert call_props["lifecyclestage"] == "lead"
        assert "HOT" in call_props["description"]
        assert "88" in call_props["description"]

    def test_updates_existing_when_found(self, client):
        """upsert_company updates existing company when domain found."""
        mock_existing = MagicMock()
        mock_existing.id = "existing-456"

        mock_updated = MagicMock()
        mock_updated.id = "existing-456"

        with (
            patch.object(client, "_search_by_domain", return_value=mock_existing),
            patch.object(client, "_update_company", return_value=mock_updated) as mock_update,
        ):
            result = client.upsert_company(
                domain="existingco.com",
                name="ExistingCo",
                city="Austin",
                state="TX",
                category="av_rental",
                fit_tier="WARM",
                fit_score=65,
            )

        assert result == "existing-456"
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        assert call_args[0] == "existing-456"  # company_id
        assert call_args[1]["domain"] == "existingco.com"


# --- log_outreach() tests ---


class TestLogOutreach:
    def test_calls_create_engagement(self, client):
        """log_outreach creates a note engagement on the company."""
        with patch.object(client, "_create_engagement") as mock_engage:
            client.log_outreach(
                company_id="comp-789",
                subject="Intro email",
                body="Hi, I'd love to work with you...",
            )

        mock_engage.assert_called_once_with(
            "comp-789", "Intro email", "Hi, I'd love to work with you..."
        )
