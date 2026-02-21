"""Tests for config resolution logic."""
from job_scraper import resolve_model


class TestResolveModel:
    def test_reads_from_models_section(self):
        config = {
            "models": {
                "job_eval": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}
            }
        }
        provider, model = resolve_model(config, "job_eval")
        assert provider == "openrouter"
        assert model == "anthropic/claude-sonnet-4"

    def test_falls_back_to_legacy_deep_eval(self):
        config = {
            "deep_eval": {"provider": "openrouter", "model": "anthropic/claude-opus-4"}
        }
        provider, model = resolve_model(config, "deep_eval")
        assert provider == "openrouter"
        assert model == "anthropic/claude-opus-4"

    def test_falls_back_to_generic_provider_key(self):
        config = {
            "llm_provider": "google_aistudio",
            "google_aistudio_model": "gemini-2.5-flash"
        }
        provider, model = resolve_model(config, "job_eval")
        assert provider == "google_aistudio"
        assert model == "gemini-2.5-flash"

    def test_default_when_no_config(self):
        provider, model = resolve_model({}, "job_eval")
        assert provider == "openrouter"
        assert "claude" in model or "anthropic" in model
