"""Tests for schema.org extraction."""
from freelance_finder import ActivityVerifier


class TestSchemaOrgExtraction:
    def test_extracts_organization_data(self):
        html = '<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"ACME AV","numberOfEmployees":{"@type":"QuantitativeValue","value":30},"foundingDate":"2005","address":{"@type":"PostalAddress","addressLocality":"Austin","addressRegion":"TX"}}</script></head><body></body></html>'
        result = ActivityVerifier._extract_schema_org(html)
        assert result["employee_count"] == 30
        assert result["founding_date"] == "2005"
        assert result["city"] == "Austin"

    def test_returns_none_when_no_schema(self):
        assert ActivityVerifier._extract_schema_org("<html><body>No data</body></html>") is None

    def test_handles_malformed_json_ld(self):
        assert ActivityVerifier._extract_schema_org('<html><head><script type="application/ld+json">{broken</script></head></html>') is None

    def test_handles_array_of_schemas(self):
        html = '<html><head><script type="application/ld+json">[{"@type":"WebSite"},{"@type":"Organization","numberOfEmployees":15}]</script></head><body></body></html>'
        result = ActivityVerifier._extract_schema_org(html)
        assert result["employee_count"] == 15
