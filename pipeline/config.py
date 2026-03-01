"""Shared state, paths, and configuration loaders for the job-search pipeline."""

import logging
import os
import sys
from pathlib import Path

import yaml
from rich.console import Console

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
console = Console(force_terminal=False, no_color=True) if os.environ.get("CI") else Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("job_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("job_scraper")

# SCRIPT_DIR must point to the project root (parent of pipeline/), not the
# pipeline/ directory itself, because all existing code depends on that.
SCRIPT_DIR = Path(__file__).parent.parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = SCRIPT_DIR / "results"

DATA_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found: {CONFIG_PATH}[/red]")
        console.print("Copy config.yaml.example to config.yaml and fill in your API keys.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Allow env vars to override config values (for CI / GitHub Actions secrets)
    env_overrides = {
        "serpapi_key": "SERPAPI_KEY",
        "brightdata_api_token": "BRIGHTDATA_API_TOKEN",
        "brightdata_zone": "BRIGHTDATA_ZONE",
        "openrouter_key": "OPENROUTER_KEY",
        "google_aistudio_key": "GOOGLE_AISTUDIO_KEY",
    }
    for config_key, env_var in env_overrides.items():
        val = os.environ.get(env_var)
        if val:
            config[config_key] = val

    # Multi-key support: GOOGLE_AISTUDIO_KEYS (comma-separated) supplements the single key
    extra_keys_env = os.environ.get("GOOGLE_AISTUDIO_KEYS", "")
    if extra_keys_env:
        keys = [k.strip() for k in extra_keys_env.split(",") if k.strip()]
        # Merge with single key (if set and not already in list)
        single = config.get("google_aistudio_key", "")
        if single and single not in keys:
            keys.insert(0, single)
        config["google_aistudio_keys"] = keys
    elif config.get("google_aistudio_key"):
        config["google_aistudio_keys"] = [config["google_aistudio_key"]]

    return config


def resolve_model(config: dict, role: str) -> tuple[str, str]:
    """Return (provider, model_id) for *role* from the centralized models section.

    Falls back to legacy per-provider keys so existing configs still work.
    """
    models = config.get("models", {})
    entry = models.get(role, {})
    if entry.get("model"):
        provider = entry.get("provider", config.get("llm_provider", "openrouter"))
        return provider, entry["model"]

    # Role-specific legacy fallbacks
    if role == "deep_eval":
        deep_cfg = config.get("deep_eval", {})
        if deep_cfg.get("model"):
            return deep_cfg.get("provider", "openrouter"), deep_cfg["model"]
    elif role == "freelance_eval":
        fl_cfg = config.get("freelance_search", {})
        if fl_cfg.get("llm_model"):
            provider = fl_cfg.get("llm_provider", config.get("llm_provider", "google_aistudio"))
            return provider, fl_cfg["llm_model"]

    # Generic legacy fallback -- derive from the active provider's top-level key
    provider = config.get("llm_provider", "openrouter")
    legacy_map = {
        "openrouter": ("openrouter_model", "anthropic/claude-sonnet-4"),
        "anthropic": ("anthropic_model", "claude-sonnet-4-20250514"),
        "google_aistudio": ("google_aistudio_model", "gemini-2.5-flash"),
        "openai_compatible": ("openai_compatible_model", "local-model"),
    }
    key, default = legacy_map.get(provider, ("openrouter_model", "anthropic/claude-sonnet-4"))
    return provider, config.get(key, default)


def load_resume(config: dict) -> str:
    """Load resume text from file."""
    resume_path = Path(config.get("resume_path", "resume.txt"))
    if not resume_path.is_absolute():
        resume_path = SCRIPT_DIR / resume_path

    if not resume_path.exists():
        console.print(f"[yellow]Resume not found at {resume_path}[/yellow]")
        console.print("Place your resume as resume.txt in the job-scraper directory.")
        return ""

    suffix = resume_path.suffix.lower()
    if suffix == ".txt" or suffix == ".md":
        return resume_path.read_text()
    elif suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(resume_path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            log.warning("Install pdfplumber to read PDF resumes: pip install pdfplumber")
            return ""
    elif suffix == ".docx":
        try:
            import docx
            doc = docx.Document(resume_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            log.warning("Install python-docx to read DOCX resumes: pip install python-docx")
            return ""
    else:
        return resume_path.read_text()
