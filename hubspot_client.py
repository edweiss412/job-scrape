"""HubSpot CRM client for company enrichment, upsert, and outreach logging."""

import logging
import time

import hubspot
import requests
from hubspot.crm.companies import (
    SimplePublicObjectInput,
    SimplePublicObjectInputForCreate,
    PublicObjectSearchRequest,
    FilterGroup,
    Filter,
    ApiException,
)
from hubspot.crm.objects.notes import (
    SimplePublicObjectInputForCreate as NoteInputForCreate,
)

log = logging.getLogger(__name__)


class HubSpotClient:
    """Wrapper around the HubSpot SDK for company enrichment and CRM sync."""

    def __init__(self, access_token: str):
        self._access_token = access_token
        self._client = hubspot.Client.create(access_token=access_token)

    # ── Internal helpers ──────────────────────────────────────────────

    def _search_by_domain(self, domain: str):
        """Search companies by domain property. Return first match or None."""
        search_request = PublicObjectSearchRequest(
            filter_groups=[
                FilterGroup(
                    filters=[
                        Filter(
                            property_name="domain",
                            operator="EQ",
                            value=domain,
                        )
                    ]
                )
            ],
            properties=[
                "domain",
                "name",
                "numberofemployees",
                "annualrevenue",
                "industry",
                "linkedin_company_page",
            ],
        )
        response = self._client.crm.companies.search_api.do_search(
            public_object_search_request=search_request
        )
        if response.results:
            return response.results[0]
        return None

    def _create_company(self, properties: dict):
        """Create a new company in HubSpot. Return the created object."""
        obj = SimplePublicObjectInputForCreate(properties=properties, associations=[])
        return self._client.crm.companies.basic_api.create(
            simple_public_object_input_for_create=obj
        )

    def _update_company(self, company_id: str, properties: dict):
        """Update an existing company in HubSpot. Return the updated object."""
        obj = SimplePublicObjectInput(properties=properties)
        return self._client.crm.companies.basic_api.update(
            company_id=company_id,
            simple_public_object_input=obj,
        )

    def _create_engagement(self, company_id: str, subject: str, body: str):
        """Create a note on a company with outreach content."""
        note_body = f"<strong>{subject}</strong><br><br>{body}"
        note_input = NoteInputForCreate(
            properties={
                "hs_timestamp": str(int(time.time() * 1000)),
                "hs_note_body": note_body,
            },
            associations=[],
        )
        note = self._client.crm.objects.notes.basic_api.create(
            simple_public_object_input_for_create=note_input
        )
        # Associate the note with the company via v4 REST API.
        # Using requests directly because the HubSpot SDK's v4 association
        # typed API has unreliable parameter handling across SDK versions.
        # Association type ID 190 = note-to-company (HUBSPOT_DEFINED).
        # Source: https://developers.hubspot.com/docs/api/crm/associations
        resp = requests.put(
            f"https://api.hubapi.com/crm/v4/objects/notes/{note.id}"
            f"/associations/companies/{company_id}",
            json=[
                {
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": 190,
                }
            ],
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return note

    # ── Public API ────────────────────────────────────────────────────

    def enrich(self, domain: str) -> dict:
        """Look up a company by domain and return enrichment data.

        Returns dict with keys: hubspot_employees, hubspot_revenue,
        hubspot_industry, hubspot_linkedin_url, hubspot_company_id.
        Returns empty dict if not found or on any error. Never raises.
        """
        try:
            company = self._search_by_domain(domain)
            if company is None:
                return {}

            props = company.properties or {}
            employees_raw = props.get("numberofemployees")
            employees = int(float(employees_raw)) if employees_raw is not None else None

            return {
                "hubspot_employees": employees,
                "hubspot_revenue": props.get("annualrevenue"),
                "hubspot_industry": props.get("industry"),
                "hubspot_linkedin_url": props.get("linkedin_company_page"),
                "hubspot_company_id": str(company.id),
            }
        except Exception:
            return {}

    def upsert_company(
        self,
        domain: str,
        name: str,
        city: str,
        state: str,
        category: str,
        fit_tier: str,
        fit_score: int,
        lifecycle_stage: str = "lead",
    ) -> str:
        """Search by domain; create or update. Return company ID."""
        properties = {
            "domain": domain,
            "name": name,
            "city": city,
            "state": state,
            "industry": category,
            "lifecyclestage": lifecycle_stage,
            "description": f"Freelance pipeline: {fit_tier} (score: {fit_score})",
        }

        existing = self._search_by_domain(domain)
        if existing:
            result = self._update_company(existing.id, properties)
            return str(result.id)
        else:
            result = self._create_company(properties)
            return str(result.id)

    def log_outreach(self, company_id: str, subject: str, body: str):
        """Create a note on the company with the outreach draft content."""
        try:
            self._create_engagement(company_id, subject, body)
        except Exception:
            log.warning("Failed to log outreach for company %s", company_id, exc_info=True)
