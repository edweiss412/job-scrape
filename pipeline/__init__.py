"""Job Search Automation Pipeline -- modular package."""
from pipeline.config import (
    console, log, SCRIPT_DIR, CONFIG_PATH, DATA_DIR, RESULTS_DIR,
    load_config, resolve_model, load_resume,
)
from pipeline.models import JobListing, _normalize_date_posted
