"""Job Search Automation Pipeline -- modular package."""
from pipeline.config import (
    console, log, SCRIPT_DIR, CONFIG_PATH, DATA_DIR, RESULTS_DIR,
    load_config, resolve_model, load_resume,
)
from pipeline.models import JobListing, _normalize_date_posted
from pipeline.urls import (
    ATS_DOMAINS, AGGREGATOR_DOMAINS,
    _url_domain_score, _pick_best_apply_url, _is_indirect_url, _resolve_apply_url,
)
from pipeline.dedup import (
    deduplicate_jobs, _url_dedup_key, _normalize_company,
    _normalize_title_words, _location_specificity_str,
)
from pipeline.scrapers import (
    SerpAPIScraper, BrightDataScraper, IndeedRSSScraper,
    AVIXAScraper, CareerPageScraper, JobSpyScraper,
    run_scrape, fetch_job_description, fetch_descriptions_batch,
    backfill_missing_descriptions,
)
from pipeline.evaluation import (
    ResumeEvaluator, run_pre_filter, user_prefilter, _keyword_score_job,
    run_benchmark, ROLE_EXPANSIONS, refilter_backfilled_jobs,
    RELEVANT_TITLE_KEYWORDS, IRRELEVANT_TITLE_KEYWORDS,
    AV_DESCRIPTION_TERMS, TARGET_COMPANY_KEYWORDS,
)
