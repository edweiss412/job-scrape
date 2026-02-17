# Job Search Automation Pipeline

Scrapes AV/audio engineering job listings from multiple sources, deduplicates them, and uses Claude to score each listing against your resume.

## Sources

| Source | API Key Needed? | Coverage |
|---|---|---|
| **SerpAPI (Google Jobs)** | Yes (free tier: 100/mo) | Best — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter, company pages |
| **Indeed RSS** | No | Good — free, ~25 results per query |
| **AVIXA Career Center** | No | Niche — AV-industry-specific, high signal |
| **Company Career Pages** | No | Targeted — scrapes your Tier 1-5 target companies directly |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
#    Edit config.yaml:
#    - Add your SerpAPI key (free at serpapi.com)
#    - Add your OpenRouter key (openrouter.ai/keys), or Google AI Studio key (aistudio.google.com/apikey), or Anthropic key, or local endpoint
#    - Set llm_provider in config.yaml: "openrouter", "google_aistudio", "anthropic", or "openai_compatible"
#    - Adjust locations, queries, target companies

# 3. Place your resume
cp /path/to/your/resume.txt ./resume.txt
#    (Also supports .pdf and .docx — install pdfplumber or python-docx)

# 4. Run
python job_scraper.py            # Full scan, all sources
python job_scraper.py --quick    # SerpAPI + Indeed only
python job_scraper.py --no-evaluate  # Scrape only, skip LLM scoring
python job_scraper.py --evaluate-only  # Re-score last results
python job_scraper.py --schedule  # Run daily on auto
```

## Output

Each run produces three files in `results/`:

- **CSV** — Import into Excel/Sheets, sort by score, filter by company
- **Markdown** — Readable report with top matches, reasoning, and apply links
- **JSON** (in `data/`) — Raw data for programmatic use

## How Evaluation Works

Each listing is sent to the configured LLM along with your resume and candidate context. The evaluator acts as a senior technical recruiter and produces a **7-section structured evaluation**:

1. **Role Summary** — Translates disguised titles, identifies role type, vertical, on-site requirements
2. **Match Score** — 🟢 STRONG / 🟡 MODERATE / 🟠 STRETCH / 🔴 WEAK
3. **Requirements Already Met** — Cited against specific resume content
4. **Experience Not Highlighted** — Things you can do but haven't surfaced; tailoring suggestions
5. **True Gaps** — Honest assessment with dealbreaker vs. nice-to-have classification
6. **Red Flags & Logistics** — Location, salary, seniority, missing ATS keywords, posting quality
7. **Verdict** — Should you apply? Tailor your resume? What's the single most important change?

For STRONG and MODERATE matches, individual evaluation files are saved to `results/<run>_evaluations/` so you can review each one and act on the tailoring advice.

### Output Structure

```
results/
├── jobs_20260216.csv              # All results, sortable
├── jobs_20260216.md               # Full report with collapsible evaluations
└── jobs_20260216_evaluations/     # Individual files for actionable matches
    ├── Goldman_Sachs_AV_Engineer.md
    ├── BlackRock_Broadcast_Engineer.md
    └── ...
```

## API Costs

- **SerpAPI**: Free tier = 100 searches/month. A full scan with all queries × all locations uses ~70 searches. One full + a few quick scans per month fits in free tier.
- **Anthropic API**: ~$0.003–0.01 per job evaluation (Sonnet). Evaluating 100 jobs ≈ $0.30–1.00.
- **OpenRouter**: Same models available, comparable pricing. See openrouter.ai/models for per-model costs. Evaluating 100 jobs with Claude Sonnet ≈ $3–8 (evaluations are detailed, ~1500 tokens output each).
- **Google AI Studio**: Generous free tier for Gemini models (1,500 requests/day for Flash). Set `llm_provider: google_aistudio`. Best value if you're using Gemini anyway.
- **Local models**: Free via LM Studio/Ollama — set `llm_provider: openai_compatible` in config. Quality depends on model; 7B+ recommended for structured evaluation.

## Customization

### Adding companies
Add entries under `career_pages` in `config.yaml`. You need the company name, base careers URL, and a search URL with your keywords.

### Changing search queries
Edit the `queries` section in `config.yaml`. These are used by SerpAPI for Google Jobs searches.

### Adjusting the evaluation
- **Candidate context**: Edit the `candidate_context` block in `config.yaml` — this tells the evaluator about your situation, strengths, and limitations beyond what's in the resume.
- **Evaluation prompt**: The full recruiter prompt is in `job_scraper.py` → `ResumeEvaluator.evaluate()`. You can adjust sections, add criteria, or change the evaluation format.

## Limitations

- **Career page scraping is fragile.** Company career sites change their HTML frequently. If a scraper stops returning results, the HTML selectors in `CareerPageScraper.JOB_SELECTORS` may need updating.
- **Indeed RSS** is limited to ~25 results per query and may not always return salary data.
- **LinkedIn** cannot be scraped directly. SerpAPI/Google Jobs picks up many LinkedIn postings, but not all. For complete LinkedIn coverage, use the manual alert setup in your reference guide.
- **Rate limiting.** The script includes delays between requests. If you hit rate limits, increase the `time.sleep()` values.
