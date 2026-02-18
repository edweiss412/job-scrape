#!/usr/bin/env python3
"""
Build a modern static HTML dashboard from markdown evaluation results.
Outputs to docs/ for GitHub Pages deployment.

Features:
  - Dark-first design inspired by resend.com
  - Mobile-first responsive card layout
  - Filter by verdict, location, pay range
  - Search across job titles and companies
  - Individual evaluation pages with deep eval integration
  - Glassmorphic card aesthetic

Usage:
    python build_site.py
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import markdown
import yaml

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
SITE_DIR = SCRIPT_DIR / "docs"
FREELANCE_DIR = SCRIPT_DIR / "freelance"
FREELANCE_SITE_DIR = SITE_DIR / "freelance"

md_converter = markdown.Markdown(extensions=["tables", "fenced_code"])

def _get_google_maps_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_KEY", "")
    if not key:
        config_path = SCRIPT_DIR / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            key = cfg.get("google_maps_key", "")
    return key


def google_maps_head() -> str:
    key = _get_google_maps_key()
    if not key:
        return ""
    return f"""<script src="https://maps.googleapis.com/maps/api/js?key={key}" async defer></script>
<script src="https://unpkg.com/@googlemaps/markerclusterer@2.5.3/dist/index.min.js"></script>"""

# ---------------------------------------------------------------------------
# Markdown parsing helpers
# ---------------------------------------------------------------------------

def parse_eval_file(md_path: Path, verdict: str) -> dict:
    """Extract structured data from an evaluation markdown file."""
    text = md_path.read_text()
    lines = text.split("\n")

    info = {
        "filename": md_path.stem,
        "verdict": verdict,
        "title": "",
        "company": "",
        "location": "",
        "salary": "",
        "tier": "",
        "url": "",
        "summary": "",
        "job_summary": "",
        "verdict_line": "",
    }

    for line in lines:
        if line.startswith("# "):
            parts = line[2:].split(" — ", 1)
            info["title"] = parts[0].strip()
            if len(parts) > 1:
                info["company"] = parts[1].strip()
            break

    for line in lines:
        if line.startswith("**Location:**"):
            info["location"] = line.split("**Location:**")[1].strip()
        elif line.startswith("**Salary:**"):
            info["salary"] = line.split("**Salary:**")[1].strip()
        elif line.startswith("**Tier:**"):
            info["tier"] = line.split("**Tier:**")[1].strip()
        elif line.startswith("**URL:**"):
            info["url"] = line.split("**URL:**")[1].strip()
        elif line.startswith("**Job Summary:**"):
            info["job_summary"] = line.split("**Job Summary:**")[1].strip()

    in_section = False
    summary_lines = []
    for line in lines:
        if re.match(r"###\s*2\.", line):
            in_section = True
            continue
        if re.match(r"###\s*3\.", line):
            break
        if in_section and line.strip():
            clean = re.sub(r'\*\*[^*]+\*\*', '', line).strip()
            clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
            if clean:
                summary_lines.append(clean)

    if summary_lines:
        info["verdict_line"] = summary_lines[0]
        info["summary"] = " ".join(summary_lines[1:])[:250]
    if not info["summary"] and len(summary_lines) > 0:
        info["summary"] = " ".join(summary_lines)[:250]

    if not info["location"]:
        for line in lines:
            if "**Location:**" in line and "Role Summary" not in line:
                loc = line.split("**Location:**")[1].strip()
                if loc:
                    info["location"] = loc
                    break

    return info


TARGET_CITIES = {
    "new york": "NYC", "nyc": "NYC", "manhattan": "NYC", "brooklyn": "NYC",
    "queens": "NYC", "astoria": "NYC", "bronx": "NYC",
    "chicago": "Chicago", "evanston": "Chicago", "waukegan": "Chicago",
    "san francisco": "SF", "sf": "SF",
    "seattle": "Seattle", "bellevue": "Seattle", "redmond": "Seattle",
    "boston": "Boston", "somerville": "Boston", "cambridge": "Boston",
    "los angeles": "LA", "la ": "LA", "burbank": "LA", "culver city": "LA",
    "santa monica": "LA", "hollywood": "LA",
    "washington": "DC", "dc": "DC", "arlington": "DC", "mclean": "DC",
    "san jose": "Bay Area", "cupertino": "Bay Area", "sunnyvale": "Bay Area",
    "mountain view": "Bay Area", "palo alto": "Bay Area", "menlo park": "Bay Area",
    "remote": "Remote", "anywhere": "Remote", "hybrid": "Other",
}


def normalize_city(location: str) -> str:
    if not location:
        return "Other"
    loc_lower = location.lower().strip()
    for pattern, city in TARGET_CITIES.items():
        if pattern in loc_lower:
            return city
    return "Other"


def parse_salary_number(salary: str) -> int:
    if not salary:
        return 0
    nums = re.findall(r'\$?([\d,]+)\s*[kK]', salary)
    if nums:
        return int(nums[0].replace(",", "")) * 1000
    nums = re.findall(r'\$?([\d,]+)', salary)
    if nums:
        val = int(nums[0].replace(",", ""))
        return val if val > 1000 else val * 1000
    return 0


VERDICT_ORDER = {"strong": 0, "moderate": 1, "stretch": 2, "weak": 3}

CITY_COORDS = {
    "NYC": [40.7128, -74.0060],
    "Chicago": [41.8781, -87.6298],
    "SF": [37.7749, -122.4194],
    "Seattle": [47.6062, -122.3321],
    "Boston": [42.3601, -71.0589],
    "LA": [34.0522, -118.2437],
    "DC": [38.9072, -77.0369],
    "Bay Area": [37.4419, -122.1430],
    "Other": [39.8283, -98.5795],
}

# ---------------------------------------------------------------------------
# SVG Logo — radar/scan motif
# ---------------------------------------------------------------------------
SVG_LOGO = """\
<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="14" cy="14" r="12" stroke="#10b981" stroke-opacity=".18" stroke-width="1"/>
  <circle cx="14" cy="14" r="8" stroke="#10b981" stroke-opacity=".3" stroke-width="1"/>
  <circle cx="14" cy="14" r="4" stroke="#10b981" stroke-opacity=".5" stroke-width="1"/>
  <circle cx="14" cy="14" r="1.5" fill="#10b981"/>
  <line x1="14" y1="14" x2="24" y2="6" stroke="#10b981" stroke-width="1.5" stroke-linecap="round" stroke-opacity=".7"/>
</svg>"""


def get_run_dates() -> list[str]:
    dates = []
    for item in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if item.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", item.name):
            dates.append(item.name)
    return dates


def strip_utm(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    clean = {k: v for k, v in params.items() if not k.startswith("utm_")}
    cleaned_query = urlencode(clean, doseq=True)
    return urlunparse(parsed._replace(query=cleaned_query))


# ---------------------------------------------------------------------------
# CSS — "Intelligence Briefing" aesthetic
# Syne (display) + DM Sans (body) + JetBrains Mono (labels/badges)
# Deep navy gradient mesh, staggered card reveals, verdict glow accents
# ---------------------------------------------------------------------------

SHARED_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@500;600;700&display=swap');

:root {
  --bg: #000000;
  --bg-card: rgba(253,253,253,.04);
  --bg-nav: rgba(0,0,0,.88);
  --bg-hover: rgba(255,255,255,.05);
  --bg-surface: rgba(253,253,253,.03);
  --text: #ADADAD; --text-bright: #FDFDFD; --text-muted: #737373; --text-dim: #535353;
  --text-link: #E5E5E5;
  --border: rgba(255,255,255,.05); --border-hover: rgba(255,255,255,.12);
  --radius: 14px; --radius-sm: 8px;
  --strong: #10b981; --strong-bg: rgba(16,185,129,.07); --strong-border: rgba(16,185,129,.18);
  --strong-glow: rgba(16,185,129,.12);
  --moderate: #f59e0b; --moderate-bg: rgba(245,158,11,.07); --moderate-border: rgba(245,158,11,.18);
  --moderate-glow: rgba(245,158,11,.08);
  --stretch: #7a8499; --stretch-bg: rgba(122,132,153,.06); --stretch-border: rgba(122,132,153,.12);
  --weak: #4a5568; --weak-bg: rgba(74,85,104,.05); --weak-border: rgba(74,85,104,.1);
  --font-display: 'Syne', sans-serif;
  --font-body: 'DM Sans', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-body);
  background: var(--bg); color: var(--text); line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
  background-image:
    radial-gradient(ellipse 80% 60% at 10% 20%, rgba(16,185,129,.025) 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 90% 80%, rgba(99,102,241,.025) 0%, transparent 55%),
    radial-gradient(ellipse 40% 40% at 50% 10%, rgba(245,158,11,.015) 0%, transparent 50%);
  background-attachment: fixed;
}

/* Grain overlay */
body::before {
  content: ''; position: fixed; inset: 0; z-index: 9999; pointer-events: none;
  opacity: .25;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.04'/%3E%3C/svg%3E");
}

a { color: var(--text-link); text-decoration: none; transition: color .15s; }
a:hover { color: var(--text-bright); }

/* ---- Nav ---- */
.topnav {
  position: sticky; top: 0; z-index: 200;
  background: var(--bg-nav); backdrop-filter: blur(20px) saturate(1.4); -webkit-backdrop-filter: blur(20px) saturate(1.4);
  border-bottom: 1px solid var(--border);
  padding: .65rem 1.5rem;
  display: flex; align-items: center; gap: .75rem;
}
.topnav .brand {
  font-family: var(--font-mono); font-weight: 600; font-size: .8rem;
  color: var(--text-muted); letter-spacing: -.01em; transition: color .15s;
}
.topnav .brand:hover { color: var(--text-bright); text-decoration: none; }
.topnav .spacer { flex: 1; }
.topnav .nav-date { font-family: var(--font-mono); font-size: .7rem; color: var(--text-dim); letter-spacing: .02em; }

/* ---- Container ---- */
.container { max-width: 1240px; margin: 0 auto; padding: 2rem 1.5rem; }
@media (max-width: 640px) { .container { padding: 1.25rem 1rem; } }

/* ---- Filters ---- */
.filter-row {
  display: flex; gap: .35rem; flex-wrap: wrap; margin-bottom: .5rem; align-items: center;
}
.filter-row label {
  font-family: var(--font-mono); font-size: .6rem; font-weight: 600; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: .1em; margin-right: .4rem;
  white-space: nowrap;
}
.search-box {
  flex: 1; min-width: 200px; padding: .55rem 1rem;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); color: var(--text); font-size: .85rem;
  font-family: var(--font-body); transition: all .2s;
}
.search-box:focus { outline: none; border-color: rgba(255,255,255,.15); box-shadow: 0 0 0 3px rgba(255,255,255,.03); }
.search-box::placeholder { color: var(--text-dim); }

/* ---- Pills ---- */
.filter-btn, .loc-btn, .pay-btn {
  padding: .3rem .7rem; border: 1px solid var(--border);
  border-radius: 20px; background: transparent; color: var(--text-muted);
  font-family: var(--font-mono); font-size: .65rem; font-weight: 500;
  cursor: pointer; transition: all .2s; white-space: nowrap;
}
.filter-btn:hover, .loc-btn:hover, .pay-btn:hover {
  border-color: var(--border-hover); color: var(--text); background: var(--bg-hover);
}
.filter-btn.active {
  background: var(--text-bright); color: var(--bg); border-color: var(--text-bright);
  box-shadow: 0 0 12px rgba(240,242,247,.08);
}
.loc-btn.active, .pay-btn.active {
  background: rgba(255,255,255,.08); color: var(--text-bright); border-color: rgba(255,255,255,.15);
}

/* ---- Dropdowns ---- */
.filter-select {
  padding: .35rem .65rem; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); color: var(--text); font-size: .75rem;
  font-family: var(--font-mono); cursor: pointer;
}
.filter-select:focus { outline: none; border-color: rgba(255,255,255,.15); }

/* ---- Stats ---- */
.stats { display: flex; gap: .5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
.stat-chip {
  padding: .3rem .75rem; border-radius: 20px; font-family: var(--font-mono);
  font-size: .7rem; font-weight: 600; letter-spacing: .02em;
}
.stat-strong { background: var(--strong-bg); color: var(--strong); border: 1px solid var(--strong-border); }
.stat-moderate { background: var(--moderate-bg); color: var(--moderate); border: 1px solid var(--moderate-border); }
.stat-stretch { background: var(--stretch-bg); color: var(--stretch); border: 1px solid var(--stretch-border); }
.stat-weak { background: var(--weak-bg); color: var(--weak); border: 1px solid var(--weak-border); }

.results-count { font-family: var(--font-mono); font-size: .65rem; color: var(--text-dim); margin-bottom: 1rem; letter-spacing: .04em; }

/* ---- Cards grid ---- */
.cards { display: grid; grid-template-columns: 1fr; gap: .65rem; }
@media (min-width: 640px) { .cards { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .cards { grid-template-columns: repeat(3, 1fr); } }

/* Staggered reveal animation — first load only */
@keyframes cardIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1.1rem 1.15rem;
  display: flex; flex-direction: column; gap: .45rem;
  animation: cardIn .4s ease both;
  border-left: 2px solid transparent;
  position: relative; cursor: pointer;
  transition: border-color .25s ease, background .25s ease, box-shadow .25s ease;
}

/* Filter/sort transition classes */
.card.card-hiding {
  opacity: 0; transform: scale(.95); pointer-events: none;
  transition: opacity .2s ease, transform .2s ease !important;
}
.card.card-hidden { display: none; }
.card.card-reveal {
  opacity: 0; transform: translateY(8px);
}
.card.card-reveal-go {
  opacity: 1; transform: translateY(0);
  transition: opacity .3s ease, transform .3s ease !important;
}
.cards.ready .card { animation: none; }
.cards.transitioning { pointer-events: none; }
.card:hover {
  border-color: var(--border-hover); background: var(--bg-hover);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,.3);
}
.card[data-verdict="strong"] { border-left-color: var(--strong); }
.card[data-verdict="strong"]:hover { box-shadow: 0 8px 24px var(--strong-glow); }
.card[data-verdict="moderate"] { border-left-color: var(--moderate); }
.card[data-verdict="moderate"]:hover { box-shadow: 0 8px 24px var(--moderate-glow); }
.card[data-verdict="stretch"] { border-left-color: var(--stretch); }
.card[data-verdict="weak"] { border-left-color: var(--weak); }

.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; }
.card-company { font-size: .7rem; color: var(--text-dim); font-weight: 500; font-family: var(--font-mono); letter-spacing: .02em; }
.card-title { font-family: var(--font-display); font-size: .95rem; font-weight: 700; line-height: 1.3; color: var(--text-bright); }
.card-meta { display: flex; gap: .5rem; flex-wrap: wrap; font-size: .7rem; color: var(--text-muted); }
.card-summary { font-size: .8rem; color: var(--text-muted); line-height: 1.6; flex: 1; }
.card-footer { display: flex; justify-content: space-between; align-items: center; margin-top: auto; padding-top: .5rem; }
.card-link {
  font-family: var(--font-mono); font-size: .65rem; font-weight: 500; color: var(--text-dim);
  transition: color .15s; letter-spacing: .02em;
}
.card-link:hover { color: var(--text-bright); text-decoration: none; }

/* Card tooltip — match reasoning on hover */
.card-tooltip {
  display: none; position: absolute; left: 0; right: 0; bottom: 100%; margin-bottom: 4px;
  background: rgba(0,0,0,.95); border: 1px solid var(--border-hover);
  border-radius: var(--radius-sm); padding: .65rem .85rem;
  font-size: .75rem; color: var(--text-muted); line-height: 1.6;
  z-index: 50; pointer-events: none; backdrop-filter: blur(12px);
  box-shadow: 0 8px 24px rgba(0,0,0,.4);
}
.card-tooltip-label {
  display: block; font-family: var(--font-mono); font-size: .55rem; font-weight: 600;
  color: var(--text-dim); text-transform: uppercase; letter-spacing: .1em; margin-bottom: .3rem;
}
.card:hover .card-tooltip { display: block; }

/* ---- Badge ---- */
.badge {
  display: inline-block; padding: .15rem .5rem; border-radius: 5px;
  font-family: var(--font-mono); font-size: .6rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: .06em;
}
.badge-strong { background: var(--strong-bg); color: var(--strong); border: 1px solid var(--strong-border); }
.badge-moderate { background: var(--moderate-bg); color: var(--moderate); border: 1px solid var(--moderate-border); }
.badge-stretch { background: var(--stretch-bg); color: var(--stretch); border: 1px solid var(--stretch-border); }
.badge-weak { background: var(--weak-bg); color: var(--weak); border: 1px solid var(--weak-border); }
.badge-hot  { background: rgba(239,68,68,.15);  color: #f87171; border: 1px solid rgba(239,68,68,.3); }
.badge-warm { background: rgba(245,158,11,.15); color: #fbbf24; border: 1px solid rgba(245,158,11,.3); }
.badge-cold { background: rgba(99,102,241,.15); color: #a5b4fc; border: 1px solid rgba(99,102,241,.3); }
.badge-skip { background: rgba(107,114,128,.12); color: #9ca3af; border: 1px solid rgba(107,114,128,.25); }
.stat-hot  { background: rgba(239,68,68,.15);  color: #f87171; border: 1px solid rgba(239,68,68,.25); }
.stat-warm { background: rgba(245,158,11,.15); color: #fbbf24; border: 1px solid rgba(245,158,11,.25); }
.stat-cold { background: rgba(99,102,241,.15); color: #a5b4fc; border: 1px solid rgba(99,102,241,.25); }
.card[data-tier="hot"]  { border-left: 3px solid #ef4444; }
.card[data-tier="warm"] { border-left: 3px solid #f59e0b; }
.card[data-tier="cold"] { border-left: 3px solid #6366f1; }
.outreach-subject {
  font-family: var(--font-mono); font-size: .75rem; color: var(--text-muted);
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: .35rem .75rem;
  margin-bottom: .75rem; display: inline-block;
}

/* ---- Eval page ---- */
.eval-wrap { max-width: 880px; margin: 0 auto; }
@media (min-width: 1200px) { .eval-wrap { max-width: 960px; } }

@keyframes heroIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.eval-hero {
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--bg-surface); padding: 2rem 2.25rem;
  margin-bottom: 2rem;
  animation: heroIn .5s ease both;
  position: relative;
}
.eval-hero::before {
  content: ''; position: absolute; inset: 0; border-radius: inherit;
  background: radial-gradient(ellipse at 80% 30%, rgba(16,185,129,.04) 0%, transparent 60%);
  pointer-events: none;
}
.eval-hero-title {
  font-family: var(--font-display); font-size: 1.6rem; font-weight: 800;
  color: var(--text-bright); line-height: 1.35; margin-bottom: .35rem; padding-bottom: .1em;
  position: relative; overflow: visible;
}
@media (min-width: 640px) { .eval-hero-title { font-size: 2rem; } }
.eval-hero-company { font-size: .9rem; color: var(--text-muted); margin-bottom: .85rem; }
.eval-hero-meta { display: flex; gap: .45rem; flex-wrap: wrap; margin-bottom: .75rem; }
.eval-chip {
  display: inline-flex; align-items: center; gap: .25rem;
  padding: .25rem .6rem; border-radius: 20px;
  font-family: var(--font-mono); font-size: .65rem; font-weight: 500;
  background: var(--bg-hover); border: 1px solid var(--border); color: var(--text-muted);
}
.eval-actions { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .85rem; }
.eval-btn {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .5rem 1.1rem; border-radius: var(--radius-sm);
  font-family: var(--font-mono); font-size: .75rem; font-weight: 600;
  text-decoration: none; transition: all .2s; border: 1px solid var(--border);
  letter-spacing: .01em;
}
.eval-btn:hover { text-decoration: none; }
.eval-btn-primary {
  background: var(--text-bright); color: var(--bg); border-color: var(--text-bright);
}
.eval-btn-primary:hover { background: #fff; box-shadow: 0 0 16px rgba(240,242,247,.1); }

/* ---- Tabs ---- */
.eval-tabs {
  display: flex; gap: 0; margin-bottom: 2rem;
  border-bottom: 1px solid var(--border);
  animation: heroIn .5s ease .1s both;
}
.eval-tab {
  padding: .6rem 1.1rem; font-family: var(--font-mono); font-size: .7rem; font-weight: 600;
  color: var(--text-dim); letter-spacing: .03em;
  cursor: pointer; border: none; background: none;
  border-bottom: 2px solid transparent; transition: all .2s; margin-bottom: -1px;
  text-transform: uppercase;
}
.eval-tab:hover { color: var(--text-muted); }
.eval-tab.active { color: var(--text-bright); border-bottom-color: var(--strong); }
.eval-tab-panel { display: none; animation: cardIn .35s ease both; }
.eval-tab-panel.active { display: block; }

/* ---- Eval content ---- */
.eval-content h1 { display: none; }
.eval-content h2 {
  font-family: var(--font-display); font-size: 1.1rem; font-weight: 700;
  margin-top: 2rem; margin-bottom: .6rem; color: var(--text-bright);
}
.eval-content h3 {
  font-family: var(--font-mono); font-size: .6rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: .1em;
  color: var(--text-dim); margin-top: 2.5rem; margin-bottom: 1rem;
  padding-bottom: .6rem; border-bottom: 1px solid var(--border);
}
.eval-content p { margin-bottom: .85rem; line-height: 1.8; font-size: .9rem; color: var(--text-muted); }
.eval-content ul, .eval-content ol { margin-bottom: .85rem; padding-left: 1.5rem; }
.eval-content li { margin-bottom: .6rem; line-height: 1.75; font-size: .9rem; color: var(--text-muted); }
.eval-content li::marker { color: var(--text-dim); }
.eval-content hr { display: none; }
.eval-content strong { color: var(--text-bright); font-weight: 600; }
.eval-content em { color: var(--text-dim); font-style: italic; }
.eval-content code {
  background: rgba(255,255,255,.04); padding: 2px 7px; border-radius: 4px;
  font-family: var(--font-mono); font-size: .8em;
  border: 1px solid var(--border);
}
.eval-content blockquote {
  border-left: 2px solid var(--strong); margin: 1rem 0; padding: .75rem 1.25rem;
  background: var(--bg-surface); border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.eval-content blockquote p { color: var(--text); }

/* ---- Run history ---- */
.run-list { list-style: none; }
.run-item {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1.1rem 1.25rem; margin-bottom: .65rem; transition: all .25s;
  animation: cardIn .4s ease both;
}
.run-item:hover {
  border-color: var(--border-hover); background: var(--bg-hover);
  transform: translateY(-1px); box-shadow: 0 4px 16px rgba(0,0,0,.25);
}
.run-item-header { display: flex; align-items: center; gap: .65rem; }
.run-item a { font-family: var(--font-display); font-weight: 700; font-size: 1rem; color: var(--text-bright); }
.run-item a:hover { text-decoration: none; }
.run-elapsed {
  font-family: var(--font-mono); font-size: .6rem; font-weight: 500; color: var(--text-dim);
  background: var(--bg-hover); padding: .15rem .45rem; border-radius: 4px;
}
.run-item .run-stats { margin-top: .5rem; display: flex; gap: .4rem; flex-wrap: wrap; }
.run-total { font-family: var(--font-mono); font-size: .6rem; color: var(--text-dim); margin-top: .35rem; }

.history-section { margin-bottom: 2rem; }
.history-section-title {
  font-family: var(--font-display); font-size: 1rem; font-weight: 700;
  color: var(--text-muted); margin-bottom: .75rem;
}

/* ---- Misc ---- */
.empty { text-align: center; padding: 4rem 1rem; color: var(--text-dim); }
.no-results { display: none; text-align: center; padding: 2.5rem; color: var(--text-dim); font-family: var(--font-mono); font-size: .8rem; }

.page-title {
  font-family: var(--font-display); font-size: 1.5rem; font-weight: 800;
  color: var(--text-bright); margin-bottom: .3rem;
}
.page-subtitle {
  font-family: var(--font-mono); font-size: .7rem; color: var(--text-dim);
  margin-bottom: 1.5rem; letter-spacing: .04em;
}

/* ---- View toggle ---- */
.view-toggle {
  display: inline-flex; gap: 0; margin-left: auto;
}
.view-btn {
  padding: .35rem .65rem; border: 1px solid var(--border); background: transparent;
  color: var(--text-muted); font-family: var(--font-mono); font-size: .65rem;
  cursor: pointer; transition: all .2s;
}
.view-btn:first-child { border-radius: var(--radius-sm) 0 0 var(--radius-sm); }
.view-btn:last-child { border-radius: 0 var(--radius-sm) var(--radius-sm) 0; border-left: none; }
.view-btn.active { background: rgba(255,255,255,.08); color: var(--text-bright); border-color: rgba(255,255,255,.15); }
.view-btn:hover { border-color: var(--border-hover); color: var(--text); }

#mapContainer {
  display: none; height: 480px; border-radius: var(--radius);
  border: 1px solid var(--border); margin-bottom: 1rem; overflow: hidden;
}
#mapContainer.active { display: block; }
.cards.map-hidden { display: none; }

/* Google Maps InfoWindow override */
.gm-style .gm-style-iw-c { background: rgba(0,0,0,.95) !important; border: 1px solid rgba(255,255,255,.06) !important; border-radius: 8px !important; padding: 4px !important; }
.gm-style .gm-style-iw-d { overflow: auto !important; }
.gm-style .gm-style-iw-tc::after { background: rgba(0,0,0,.95) !important; }
.gm-style .gm-ui-hover-effect>span { background-color: #6b7a99 !important; }

/* ---- Sidebar ---- */
.sidebar-toggle {
  background: none; border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text-muted); cursor: pointer; padding: .35rem .5rem;
  display: flex; align-items: center; justify-content: center;
  transition: all .2s; line-height: 1;
}
.sidebar-toggle:hover { border-color: var(--border-hover); color: var(--text-bright); background: var(--bg-hover); }

.sidebar-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.5); backdrop-filter: blur(4px);
  z-index: 299; opacity: 0; pointer-events: none; transition: opacity .25s;
}
.sidebar-overlay.open { opacity: 1; pointer-events: auto; }

.sidebar {
  position: fixed; top: 0; left: 0; bottom: 0; width: 240px; z-index: 300;
  background: rgba(0,0,0,.96); backdrop-filter: blur(20px);
  border-right: 1px solid var(--border);
  transform: translateX(-100%); transition: transform .25s ease;
  display: flex; flex-direction: column; padding: 1.25rem;
}
.sidebar.open { transform: translateX(0); }

.sidebar-brand {
  display: flex; align-items: center; gap: .6rem; margin-bottom: 2rem; padding: .25rem 0;
}
.sidebar-brand-text {
  font-family: var(--font-mono); font-weight: 700; font-size: .85rem;
  color: var(--text-bright); letter-spacing: -.01em;
}

.sidebar-nav { list-style: none; display: flex; flex-direction: column; gap: .2rem; }
.sidebar-nav a {
  display: flex; align-items: center; gap: .65rem;
  padding: .55rem .75rem; border-radius: var(--radius-sm);
  font-family: var(--font-body); font-size: .85rem; font-weight: 500;
  color: var(--text-muted); transition: all .15s; text-decoration: none;
}
.sidebar-nav a:hover { background: var(--bg-hover); color: var(--text-bright); }
.sidebar-nav a.active { background: rgba(16,185,129,.08); color: var(--strong); }
.sidebar-nav .nav-icon { font-size: .95rem; width: 1.2rem; text-align: center; }

.sidebar-section {
  font-family: var(--font-mono); font-size: .55rem; font-weight: 600;
  color: var(--text-dim); text-transform: uppercase; letter-spacing: .12em;
  margin-top: 1.5rem; margin-bottom: .5rem; padding-left: .75rem;
}

@media (min-width: 1024px) {
  body[data-sidebar="open"] .sidebar { transform: translateX(0); }
  body[data-sidebar="open"] .sidebar-overlay { display: none; }
  body[data-sidebar="open"] .topnav,
  body[data-sidebar="open"] .main-content { margin-left: 240px; transition: margin-left .25s; }
}
"""

SIDEBAR_TOGGLE = """\
<button class="sidebar-toggle" id="sidebarToggle" aria-label="Toggle sidebar">
  <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
</button>"""


def sidebar_html(active: str = "dashboard", date_str: str = "",
                 latest_date: str = "", root: str = "") -> str:
    """Generate overlay + sidebar nav (injected via wrap_page sidebar param).

    root: path prefix to docs/ root from the current page (e.g. '../').
          Auto-detected from date_str when omitted.
    """
    def nav_class(item):
        return ' class="active"' if item == active else ''

    # Auto-detect root from date_str (legacy callers don't pass root)
    if not root:
        root = "../" if date_str else "./"

    # Job scan links
    if date_str and active == "dashboard":
        job_dash_href = "./"
        job_hist_href = "../"
    else:
        job_dash_href = f"{root}{latest_date}/" if latest_date else root
        job_hist_href = root

    freelance_href = f"{root}freelance/"

    return f"""
<div class="sidebar-overlay" id="sidebarOverlay"></div>
<nav class="sidebar" id="sidebar">
  <div class="sidebar-brand">{SVG_LOGO}<span class="sidebar-brand-text">Job Scan</span></div>
  <div class="sidebar-section">Job Search</div>
  <ul class="sidebar-nav">
    <li><a href="{job_dash_href}"{nav_class('dashboard')}><span class="nav-icon">◎</span> Dashboard</a></li>
    <li><a href="{job_hist_href}"{nav_class('history')}><span class="nav-icon">◷</span> Scan History</a></li>
  </ul>
  <div class="sidebar-section">Freelance</div>
  <ul class="sidebar-nav">
    <li><a href="{freelance_href}"{nav_class('freelance')}><span class="nav-icon">⚡</span> Prospects</a></li>
  </ul>
</nav>"""


SIDEBAR_JS = """\
(function() {
  var toggle = document.getElementById('sidebarToggle');
  var sidebar = document.getElementById('sidebar');
  var overlay = document.getElementById('sidebarOverlay');
  if (!toggle || !sidebar) return;

  var isDesktop = window.matchMedia('(min-width: 1024px)').matches;
  var defaultState = document.body.dataset.sidebarDefault || 'closed';

  if (isDesktop && defaultState === 'open') {
    sidebar.classList.add('open');
    document.body.dataset.sidebar = 'open';
  }

  toggle.addEventListener('click', function() {
    var open = sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('open', open);
    if (isDesktop) document.body.dataset.sidebar = open ? 'open' : '';
  });

  if (overlay) overlay.addEventListener('click', function() {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
    if (isDesktop) document.body.dataset.sidebar = '';
  });
})();
"""


MAP_JS = """\
(function() {
  var mapEl = document.getElementById('mapContainer');
  var gridEl = document.getElementById('cardsGrid');
  var viewGrid = document.getElementById('viewGrid');
  var viewMap = document.getElementById('viewMap');
  if (!mapEl || !viewGrid || !viewMap) return;
  if (typeof google === 'undefined' || !google.maps) {
    // No Google Maps API — hide map toggle
    viewMap.style.display = 'none';
    return;
  }

  var COORDS = {
    'NYC': {lat:40.7128,lng:-74.006}, 'Chicago': {lat:41.8781,lng:-87.6298},
    'SF': {lat:37.7749,lng:-122.4194}, 'Seattle': {lat:47.6062,lng:-122.3321},
    'Boston': {lat:42.3601,lng:-71.0589}, 'LA': {lat:34.0522,lng:-118.2437},
    'DC': {lat:38.9072,lng:-77.0369}, 'Bay Area': {lat:37.4419,lng:-122.143},
    'Other': {lat:39.8283,lng:-98.5795}, 'Remote': {lat:39.8283,lng:-98.5795}
  };
  var VCOL = { strong: '#10b981', moderate: '#f59e0b', stretch: '#7a8499', weak: '#4a5568' };

  var map = null, gMarkers = [], clusterer = null, openInfo = null;

  function initMap() {
    if (map) return;
    map = new google.maps.Map(mapEl, {
      center: {lat: 39.5, lng: -98.35}, zoom: 4,
      mapId: 'job_scan_dark',
      styles: [
        {elementType:'geometry',stylers:[{color:'#000000'}]},
        {elementType:'labels.text.stroke',stylers:[{color:'#000000'}]},
        {elementType:'labels.text.fill',stylers:[{color:'#3d4a66'}]},
        {featureType:'road',elementType:'geometry',stylers:[{color:'rgba(255,255,255,.06)'}]},
        {featureType:'water',elementType:'geometry',stylers:[{color:'#000000'}]},
        {featureType:'poi',stylers:[{visibility:'off'}]},
        {featureType:'transit',stylers:[{visibility:'off'}]},
        {featureType:'administrative',elementType:'geometry.stroke',stylers:[{color:'rgba(255,255,255,.06)'}]}
      ],
      disableDefaultUI: true, zoomControl: true,
      backgroundColor: '#000000'
    });
  }

  function clearMarkers() {
    if (clusterer) clusterer.clearMarkers();
    gMarkers.forEach(function(m) { m.setMap(null); });
    gMarkers = [];
    if (openInfo) { openInfo.close(); openInfo = null; }
  }

  function updateMarkers() {
    if (!map) return;
    clearMarkers();
    var items = window._filteredCards || (typeof CARDS_DATA !== 'undefined' ? CARDS_DATA : []);

    // Group by city for slight offset so pins don't stack exactly
    var groups = {};
    items.forEach(function(d) {
      var c = d.ci || 'Other';
      if (!groups[c]) groups[c] = [];
      groups[c].push(d);
    });

    Object.keys(groups).forEach(function(city) {
      var co = COORDS[city] || COORDS['Other'];
      groups[city].forEach(function(d, i) {
        var jitter = (i - groups[city].length/2) * 0.02;
        var marker = new google.maps.Marker({
          position: {lat: co.lat + jitter * 0.5, lng: co.lng + jitter},
          icon: {
            path: google.maps.SymbolPath.CIRCLE, scale: 7,
            fillColor: VCOL[d.v] || '#4a5568', fillOpacity: .75,
            strokeColor: VCOL[d.v] || '#4a5568', strokeWeight: 1
          },
          title: d.t + ' — ' + d.c
        });
        marker._jobData = d;

        var content = '<div style="font-family:DM Sans,sans-serif;font-size:13px;max-width:260px;line-height:1.5;">' +
          '<strong style="color:#f0f2f7;">' + d.t + '</strong><br>' +
          '<span style="color:#6b7a99;">' + d.c + '</span>';
        if (d.s) content += '<br><span style="color:' + VCOL[d.v] + ';">' + d.s + '</span>';
        content += '<br><a href="' + d.v + '/' + d.f + '.html" style="color:#10b981;">View eval →</a></div>';

        var info = new google.maps.InfoWindow({ content: content });
        marker.addListener('click', function() {
          if (openInfo) openInfo.close();
          info.open(map, marker);
          openInfo = info;
        });

        gMarkers.push(marker);
      });
    });

    // Cluster markers
    if (typeof markerClusterer !== 'undefined' && markerClusterer.MarkerClusterer) {
      clusterer = new markerClusterer.MarkerClusterer({
        map: map, markers: gMarkers,
        renderer: {
          render: function(cluster, stats) {
            var count = cluster.count;
            var color = '#10b981';
            // Color based on best verdict in cluster
            var markers = cluster.markers;
            for (var i = 0; i < markers.length; i++) {
              var v = markers[i]._jobData && markers[i]._jobData.v;
              if (v === 'strong') { color = '#10b981'; break; }
              if (v === 'moderate') color = '#f59e0b';
            }
            return new google.maps.Marker({
              position: cluster.position,
              icon: {
                path: google.maps.SymbolPath.CIRCLE, scale: 16 + Math.min(count, 20),
                fillColor: color, fillOpacity: .2,
                strokeColor: color, strokeWeight: 2
              },
              label: { text: String(count), color: '#f0f2f7', fontSize: '11px', fontWeight: '700' },
              zIndex: Number(google.maps.Marker.MAX_ZINDEX) + count
            });
          }
        }
      });

      // Cluster click: show combined tooltip
      google.maps.event.addListener(clusterer, 'click', function(cluster) {
        var markers = cluster.markers || [];
        if (markers.length <= 5) {
          var html = '<div style="font-family:DM Sans,sans-serif;font-size:12px;max-width:300px;max-height:240px;overflow-y:auto;">';
          markers.forEach(function(m) {
            var d = m._jobData;
            if (!d) return;
            html += '<div style="padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06);">' +
              '<a href="' + d.v + '/' + d.f + '.html" style="color:#10b981;font-weight:600;">' + d.t + '</a>' +
              '<br><span style="color:#6b7a99;font-size:11px;">' + d.c + (d.s ? ' · ' + d.s : '') + '</span></div>';
          });
          html += '</div>';
          if (openInfo) openInfo.close();
          openInfo = new google.maps.InfoWindow({ content: html, position: cluster.position });
          openInfo.open(map);
        } else {
          map.fitBounds(cluster.bounds);
        }
      });
    } else {
      // Fallback: just add markers directly
      gMarkers.forEach(function(m) { m.setMap(map); });
    }
  }

  viewMap.addEventListener('click', function() {
    viewGrid.classList.remove('active');
    viewMap.classList.add('active');
    mapEl.classList.add('active');
    gridEl.classList.add('map-hidden');
    document.getElementById('loadMore').style.display = 'none';
    initMap();
    updateMarkers();
  });

  viewGrid.addEventListener('click', function() {
    viewMap.classList.remove('active');
    viewGrid.classList.add('active');
    mapEl.classList.remove('active');
    gridEl.classList.remove('map-hidden');
    document.getElementById('loadMore').style.display = '';
  });

  // Expose for applyFilters hook
  window._updateMapMarkers = updateMarkers;
})();
"""

DASHBOARD_JS = """\
(function() {
  var grid = document.getElementById('cardsGrid');
  var sentinel = document.getElementById('loadMore');
  if (!grid || typeof CARDS_DATA === 'undefined') return;

  var searchBox = document.getElementById('search');
  var verdictBtns = document.querySelectorAll('.filter-btn');
  var locBtns = document.querySelectorAll('.loc-btn');
  var payBtns = document.querySelectorAll('.pay-btn');
  var tierSelect = document.getElementById('tierFilter');
  var sortSelect = document.getElementById('sortSelect');
  var noResults = document.getElementById('noResults');
  var countEl = document.getElementById('resultsCount');

  var BATCH = 30;
  var allItems = CARDS_DATA;  // full dataset from JSON
  var filtered = [];          // items passing current filters
  var rendered = 0;           // how many of filtered[] are in the DOM
  var activeVerdict = 'recommended', activeCity = 'all', activePay = 'all';

  var payRanges = {
    'all': [0, Infinity], 'u100': [1, 99999],
    '100-130': [100000, 130000], '130-160': [130000, 160000],
    '160-200': [160000, 200000], '200+': [200000, Infinity],
    'unlisted': [0, 0]
  };

  // ---- Card rendering ----
  function makeCard(d) {
    var loc = d.l ? '📍 ' + d.l : '';
    var sal = d.s ? '💰 ' + d.s : '';
    var tier = d.r ? '🏢 ' + d.r : '';
    var meta = [loc, sal, tier].filter(Boolean).map(function(m) { return '<span>' + m + '</span>'; }).join(' ');
    var href = d.v + '/' + d.f + '.html';
    var el = document.createElement('div');
    el.className = 'card';
    el.setAttribute('data-verdict', d.v);
    el.setAttribute('data-href', href);
    var tooltip = d.mr ? '<div class="card-tooltip"><span class="card-tooltip-label">Match reasoning</span>' + d.mr + '</div>' : '';
    el.innerHTML =
      '<div class="card-header"><span class="card-company">' + d.c + '</span>' +
      '<span class="badge badge-' + d.v + '">' + d.v + '</span></div>' +
      '<div class="card-title">' + d.t + '</div>' +
      '<div class="card-meta">' + meta + '</div>' +
      '<div class="card-summary">' + d.u + '</div>' +
      tooltip +
      '<div class="card-footer"><a href="' + href + '" class="card-link">View evaluation →</a></div>';
    return el;
  }

  function renderBatch(count) {
    var end = Math.min(rendered + count, filtered.length);
    var frag = document.createDocumentFragment();
    for (var i = rendered; i < end; i++) {
      var card = makeCard(filtered[i]);
      card.style.animationDelay = ((i - rendered) * 0.025) + 's';
      frag.appendChild(card);
    }
    grid.appendChild(frag);
    rendered = end;
    // After entrance animation, clear delays
    setTimeout(function() {
      var cards = grid.querySelectorAll('.card');
      for (var j = 0; j < cards.length; j++) cards[j].style.animationDelay = '';
    }, 600);
  }

  // ---- Filtering ----
  function matchItem(d) {
    var q = (searchBox ? searchBox.value : '').toLowerCase();
    var tier = tierSelect ? tierSelect.value : 'all';
    if (activeVerdict === 'recommended' && d.v === 'weak') return false;
    if (activeVerdict !== 'all' && activeVerdict !== 'recommended' && d.v !== activeVerdict) return false;
    if (activeCity !== 'all' && d.ci !== activeCity) return false;
    if (activePay !== 'all') {
      var s = d.sn || 0;
      if (activePay === 'unlisted') { if (s !== 0) return false; }
      else {
        var range = payRanges[activePay];
        if (s < range[0] || s > range[1]) return false;
      }
    }
    if (tier !== 'all' && d.tk !== tier) return false;
    if (q) {
      var search = (d.t + ' ' + d.c + ' ' + d.l + ' ' + d.r).toLowerCase();
      if (search.indexOf(q) === -1) return false;
    }
    return true;
  }

  function passesOtherFilters(d, exclude) {
    var q = (searchBox ? searchBox.value : '').toLowerCase();
    var tier = tierSelect ? tierSelect.value : 'all';
    if (exclude !== 'verdict' && activeVerdict === 'recommended' && d.v === 'weak') return false;
    if (exclude !== 'verdict' && activeVerdict !== 'all' && activeVerdict !== 'recommended' && d.v !== activeVerdict) return false;
    if (exclude !== 'city' && activeCity !== 'all' && d.ci !== activeCity) return false;
    if (exclude !== 'pay' && activePay !== 'all') {
      var s = d.sn || 0;
      if (activePay === 'unlisted') { if (s !== 0) return false; }
      else { var range = payRanges[activePay]; if (s < range[0] || s > range[1]) return false; }
    }
    if (exclude !== 'tier' && tier !== 'all' && d.tk !== tier) return false;
    if (exclude !== 'search' && q) {
      var search = (d.t + ' ' + d.c + ' ' + d.l + ' ' + d.r).toLowerCase();
      if (search.indexOf(q) === -1) return false;
    }
    return true;
  }

  function updateCounts() {
    verdictBtns.forEach(function(btn) {
      var f = btn.dataset.filter;
      var ct = 0;
      allItems.forEach(function(d) {
        if (!passesOtherFilters(d, 'verdict')) return;
        if (f === 'all' || (f === 'recommended' && d.v !== 'weak') || d.v === f) ct++;
      });
      btn.textContent = btn.dataset.label + ' (' + ct + ')';
    });
    locBtns.forEach(function(btn) {
      var c = btn.dataset.city;
      var ct = 0;
      allItems.forEach(function(d) {
        if (passesOtherFilters(d, 'city') && (c === 'all' || d.ci === c)) ct++;
      });
      btn.textContent = btn.dataset.label + ' (' + ct + ')';
    });
    payBtns.forEach(function(btn) {
      var p = btn.dataset.pay;
      var ct = 0;
      allItems.forEach(function(d) {
        if (!passesOtherFilters(d, 'pay')) return;
        var s = d.sn || 0;
        if (p === 'all') { ct++; return; }
        if (p === 'unlisted') { if (s === 0) ct++; return; }
        var range = payRanges[p];
        if (s >= range[0] && s <= range[1]) ct++;
      });
      btn.textContent = btn.dataset.label + ' (' + ct + ')';
    });
    hideZeroPills(verdictBtns, 'filter');
    hideZeroPills(locBtns, 'city');
    hideZeroPills(payBtns, 'pay');
  }

  function applyFilters() {
    // Filter the full dataset
    filtered = allItems.filter(matchItem);

    // Clear the grid and re-render first batch
    grid.innerHTML = '';
    rendered = 0;
    renderBatch(BATCH);

    // Expose filtered for map view
    window._filteredCards = filtered;

    if (noResults) noResults.style.display = filtered.length === 0 ? 'block' : 'none';
    if (countEl) countEl.textContent = filtered.length + ' result' + (filtered.length !== 1 ? 's' : '');
    updateCounts();
    if (window._updateMapMarkers) window._updateMapMarkers();
  }

  // ---- Sorting ----
  function sortItems(key) {
    allItems.sort(function(a, b) {
      if (key === 'salary-desc') return (b.sn||0) - (a.sn||0);
      if (key === 'salary-asc') {
        if (!a.sn && !b.sn) return 0; if (!a.sn) return 1; if (!b.sn) return -1;
        return a.sn - b.sn;
      }
      if (key === 'verdict') return (a.vn||0) - (b.vn||0);
      if (key === 'company') return (a.c||'').localeCompare(b.c||'');
      return 0;
    });
  }

  function hideZeroPills(btns, activeAttr) {
    btns.forEach(function(btn) {
      var isAll = btn.dataset[activeAttr] === 'all';
      var isActive = btn.classList.contains('active');
      var ct = parseInt(btn.textContent.match(/\\((\\d+)\\)/)?.[1] || '0');
      btn.style.display = (isAll || isActive || ct > 0) ? '' : 'none';
    });
  }

  // ---- Event bindings ----
  function bindPills(btns, stateKey) {
    btns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        btns.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        if (stateKey === 'verdict') activeVerdict = btn.dataset.filter;
        else if (stateKey === 'city') activeCity = btn.dataset.city;
        else if (stateKey === 'pay') activePay = btn.dataset.pay;
        window.scrollTo({ top: 0, behavior: 'smooth' });
        applyFilters();
      });
    });
  }
  bindPills(verdictBtns, 'verdict');
  bindPills(locBtns, 'city');
  bindPills(payBtns, 'pay');

  if (tierSelect) tierSelect.addEventListener('change', function() { applyFilters(); });

  var searchTimer;
  if (searchBox) searchBox.addEventListener('input', function() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 200);
  });

  if (sortSelect) sortSelect.addEventListener('change', function() {
    if (this.value !== 'default') sortItems(this.value);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    applyFilters();
  });

  // ---- Infinite scroll via IntersectionObserver ----
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function(entries) {
      if (entries[0].isIntersecting && rendered < filtered.length) {
        renderBatch(BATCH);
      }
    }, { rootMargin: '400px' });
    observer.observe(sentinel);
  } else {
    // Fallback: render all
    renderBatch(Infinity);
  }

  // ---- Clickable cards ----
  grid.addEventListener('click', function(e) {
    if (e.target.closest('a')) return;  // preserve link behavior
    var card = e.target.closest('.card');
    if (card && card.dataset.href) {
      window.location.href = card.dataset.href;
    }
  });

  // ---- Set initial verdict pill ----
  verdictBtns.forEach(function(btn) {
    btn.classList.remove('active');
    if (btn.dataset.filter === 'recommended') btn.classList.add('active');
  });

  // ---- Initial render ----
  applyFilters();
})();
"""

EVAL_TABS_JS = """\
(function() {
  var tabs = document.querySelectorAll('.eval-tab');
  var panels = document.querySelectorAll('.eval-tab-panel');
  if (!tabs.length) return;
  tabs.forEach(function(tab) {
    tab.addEventListener('click', function() {
      tabs.forEach(function(t) { t.classList.remove('active'); });
      panels.forEach(function(p) { p.classList.remove('active'); });
      tab.classList.add('active');
      var panel = document.getElementById(tab.dataset.panel);
      if (panel) panel.classList.add('active');
    });
  });
})();
"""

# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def wrap_page(title: str, body_html: str, extra_js: str = "",
              sidebar: str = "", sidebar_default: str = "closed",
              extra_head: str = "") -> str:
    sidebar_js = f"<script>{SIDEBAR_JS}</script>" if sidebar else ""
    data_attr = f' data-sidebar-default="{sidebar_default}"' if sidebar else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{SHARED_CSS}</style>
{extra_head}
</head>
<body{data_attr}>
{sidebar}
{body_html}
{sidebar_js}
{f"<script>{extra_js}</script>" if extra_js else ""}
</body>
</html>"""


def build_eval_page(md_path: Path, out_dir: Path, date_str: str, verdict: str, job_info: dict) -> str:
    """Convert a .md eval to a styled .html page. Merges deep eval if available."""
    html_name = md_path.stem + ".html"

    # Standard eval content
    md_converter.reset()
    raw_md = md_path.read_text()
    raw_md = re.sub(r'^#\s+.+?\n---', '---', raw_md, count=1, flags=re.DOTALL)
    standard_html = md_converter.convert(raw_md)

    # Check for deep evaluation
    deep_path = md_path.parent / "deep" / md_path.name
    deep_html = ""
    has_deep = deep_path.exists()
    if has_deep:
        md_converter.reset()
        deep_md = deep_path.read_text()
        deep_md = re.sub(r'^#\s+.+?\n---', '---', deep_md, count=1, flags=re.DOTALL)
        deep_html = md_converter.convert(deep_md)

    # Meta chips
    chips = []
    if job_info.get("location"):
        chips.append(f'<span class="eval-chip">📍 {job_info["location"]}</span>')
    if job_info.get("salary"):
        chips.append(f'<span class="eval-chip">💰 {job_info["salary"]}</span>')
    if job_info.get("tier"):
        chips.append(f'<span class="eval-chip">🏢 {job_info["tier"]}</span>')
    meta_html = "\n        ".join(chips)

    # Actions
    actions = ""
    if job_info.get("url"):
        clean_url = strip_utm(job_info["url"])
        actions += f'<a href="{clean_url}" target="_blank" rel="noopener" class="eval-btn eval-btn-primary">View Posting ↗</a>'

    # Build tabs if deep eval exists
    if has_deep:
        content_section = f"""
    <div class="eval-tabs">
      <button class="eval-tab active" data-panel="panel-eval">Evaluation</button>
      <button class="eval-tab" data-panel="panel-deep">Deep Dive & Prep</button>
    </div>
    <div class="eval-tab-panel active" id="panel-eval">
      <div class="eval-content">{standard_html}</div>
    </div>
    <div class="eval-tab-panel" id="panel-deep">
      <div class="eval-content">{deep_html}</div>
    </div>"""
    else:
        content_section = f'<div class="eval-content">{standard_html}</div>'

    body = f"""
<nav class="topnav">
  <a href="../" class="brand">← Dashboard</a>
  <span class="spacer"></span>
  <span class="badge badge-{verdict.split('/')[0]}">{verdict.split('/')[0]}</span>
</nav>
<div class="container">
  <div class="eval-wrap">
    <div class="eval-hero">
      <div class="eval-hero-title">{job_info.get('title', md_path.stem)}</div>
      <div class="eval-hero-company">{job_info.get('company', '')}</div>
      <div class="eval-hero-meta">
        <span class="badge badge-{verdict.split('/')[0]}">{verdict.split('/')[0].upper()}</span>
        {meta_html}
      </div>
      {f'<div class="eval-actions">{actions}</div>' if actions else ''}
    </div>
    {content_section}
  </div>
</div>"""

    js = EVAL_TABS_JS if has_deep else ""
    page = wrap_page(
        f"{job_info.get('title', md_path.stem)} — {job_info.get('company', '')}",
        body, extra_js=js,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / html_name).write_text(page)
    return html_name


def build_card_data(job: dict, date_str: str, verdict: str) -> dict:
    """Build a JSON-serializable dict for a card (rendered client-side)."""
    city = normalize_city(job["location"])
    salary_num = parse_salary_number(job["salary"])
    tier_key = job["tier"].split("—")[0].strip() if job["tier"] else ""
    verdict_num = VERDICT_ORDER.get(verdict, 9)
    # Use job_summary as primary card text; fall back to match reasoning
    card_summary = job.get("job_summary") or job["summary"]
    match_reason = job["summary"] if job.get("job_summary") else ""
    return {
        "t": job["title"],
        "c": job["company"],
        "l": job["location"],
        "s": job["salary"],
        "r": job["tier"],
        "u": card_summary,
        "mr": match_reason,
        "v": verdict,
        "f": job["filename"],
        "ci": city,
        "sn": salary_num,
        "tk": tier_key,
        "vn": verdict_num,
    }


def build_card_html(job: dict, date_str: str, verdict: str) -> str:
    """Build a static card HTML (used for moderate index page)."""
    loc = f"📍 {job['location']}" if job["location"] else ""
    salary = f"💰 {job['salary']}" if job["salary"] else ""
    tier_display = f"🏢 {job['tier']}" if job["tier"] else ""
    meta_items = " ".join(f"<span>{m}</span>" for m in [loc, salary, tier_display] if m)
    search_text = f"{job['title']} {job['company']} {job['location']} {job['tier']}".lower()
    link = f"{verdict}/{job['filename']}.html"
    city = normalize_city(job["location"])
    salary_num = parse_salary_number(job["salary"])
    tier_key = job["tier"].split("—")[0].strip() if job["tier"] else ""
    verdict_num = VERDICT_ORDER.get(verdict, 9)

    return f"""<div class="card" data-verdict="{verdict}" data-search="{search_text}" data-city="{city}" data-tier="{tier_key}" data-salary="{salary_num}" data-verdict-order="{verdict_num}" data-company="{job['company'].lower()}">
  <div class="card-header">
    <span class="card-company">{job['company']}</span>
    <span class="badge badge-{verdict}">{verdict}</span>
  </div>
  <div class="card-title">{job['title']}</div>
  <div class="card-meta">{meta_items}</div>
  <div class="card-summary">{job['summary']}</div>
  <div class="card-footer">
    <a href="{link}" class="card-link">View evaluation →</a>
  </div>
</div>"""


def build_date_index(date_str: str) -> dict:
    """Build the dashboard page for a single run date. Returns verdict counts."""
    run_dir = RESULTS_DIR / date_str
    site_date_dir = SITE_DIR / date_str

    all_jobs = []
    counts = {}

    for verdict in ("strong", "moderate", "stretch", "weak"):
        verdict_dir = run_dir / verdict
        if not verdict_dir.is_dir():
            continue

        md_files = sorted(verdict_dir.glob("*.md"))
        if not md_files:
            continue

        out_dir = site_date_dir / verdict
        counts[verdict] = len(md_files)

        for md_path in md_files:
            job_info = parse_eval_file(md_path, verdict)
            build_eval_page(md_path, out_dir, date_str, verdict, job_info)
            all_jobs.append((verdict, job_info))

    # Build card data as JSON for lazy rendering
    cards_data = []
    cities = {}
    tiers = {}
    for verdict, job in all_jobs:
        cards_data.append(build_card_data(job, date_str, verdict))
        city = normalize_city(job["location"])
        if city:
            cities[city] = cities.get(city, 0) + 1
        tier_key = job["tier"].split("—")[0].strip() if job["tier"] else ""
        if tier_key:
            tiers[tier_key] = tiers.get(tier_key, 0) + 1

    import json as _json
    cards_json = _json.dumps(cards_data, separators=(",", ":"))

    stats_html = ""
    for v in ("strong", "moderate", "stretch", "weak"):
        if v in counts:
            stats_html += f'<span class="stat-chip stat-{v}">{counts[v]} {v.upper()}</span>\n'

    total = sum(counts.values())

    sorted_cities = sorted(cities.items(), key=lambda x: -x[1])
    loc_pills = '<button class="loc-btn active" data-city="all" data-label="All">All</button>\n'
    for city, ct in sorted_cities:
        loc_pills += f'<button class="loc-btn" data-city="{city}" data-label="{city}">{city} ({ct})</button>\n'

    tier_options = '<option value="all">All Tiers</option>\n'
    for tier, ct in sorted(tiers.items()):
        tier_options += f'<option value="{tier}">{tier} ({ct})</option>\n'

    pay_pills = '<button class="pay-btn active" data-pay="all" data-label="All">All</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="u100" data-label="Under $100K">Under $100K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="100-130" data-label="$100–130K">$100–130K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="130-160" data-label="$130–160K">$130–160K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="160-200" data-label="$160–200K">$160–200K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="200+" data-label="$200K+">$200K+</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="unlisted" data-label="Unlisted">Unlisted</button>\n'

    recommended_count = sum(counts.get(v, 0) for v in ("strong", "moderate", "stretch"))
    verdict_pills = f'<button class="filter-btn" data-filter="all" data-label="All">All ({total})</button>'
    verdict_pills += f'<button class="filter-btn active" data-filter="recommended" data-label="Recommended">Recommended ({recommended_count})</button>'
    for v in ("strong", "moderate", "stretch", "weak"):
        if v in counts:
            verdict_pills += f'<button class="filter-btn" data-filter="{v}" data-label="{v.title()}">{v.title()} ({counts[v]})</button>'

    sb = sidebar_html(active="dashboard", date_str=date_str)

    body = f"""
<nav class="topnav">
  {SIDEBAR_TOGGLE}
  <span class="brand">Job Scan</span>
  <span class="nav-date">{date_str}</span>
  <span class="spacer"></span>
</nav>
<div class="container main-content">
  <div class="stats">{stats_html}</div>

  <div class="filter-row">
    <input type="text" class="search-box" id="search" placeholder="Search jobs, companies, locations...">
  </div>

  <div class="filter-row">
    <label>Match</label>
    {verdict_pills}
  </div>

  <div class="filter-row">
    <label>Location</label>
    {loc_pills}
  </div>

  <div class="filter-row">
    <label>Pay</label>
    {pay_pills}
  </div>

  <div class="filter-row">
    <label>Tier</label>
    <select class="filter-select" id="tierFilter">{tier_options}</select>
    <label style="margin-left:.75rem;">Sort</label>
    <select class="filter-select" id="sortSelect">
      <option value="default">Default</option>
      <option value="salary-desc">Salary ↓</option>
      <option value="salary-asc">Salary ↑</option>
      <option value="verdict">Verdict</option>
      <option value="company">Company A→Z</option>
    </select>
  </div>

  <div class="filter-row">
    <div class="results-count" id="resultsCount">{total} results</div>
    <div class="view-toggle">
      <button class="view-btn active" data-view="grid" id="viewGrid">Grid</button>
      <button class="view-btn" data-view="map" id="viewMap">Map</button>
    </div>
  </div>

  <div id="mapContainer"></div>
  <div class="cards" id="cardsGrid"></div>
  <div id="loadMore" style="height:1px;"></div>
  <div class="no-results" id="noResults">No matches found.</div>
</div>
<script>var CARDS_DATA={cards_json};</script>"""

    page = wrap_page(f"Job Scan — {date_str}", body,
                     extra_js=DASHBOARD_JS + "\n" + MAP_JS,
                     sidebar=sb, sidebar_default="open",
                     extra_head=google_maps_head())
    site_date_dir.mkdir(parents=True, exist_ok=True)
    (site_date_dir / "index.html").write_text(page)

    # Moderate index for email "view all" link
    if "moderate" in counts:
        mod_cards = "\n".join(build_card_html(j, date_str, "moderate") for v, j in all_jobs if v == "moderate")
        mod_body = f"""
<nav class="topnav">
  <a href="../" class="brand">← Dashboard</a>
  <span class="nav-date">Moderate Matches</span>
  <span class="spacer"></span>
</nav>
<div class="container">
  <div class="page-title">All Moderate Matches</div>
  <div class="page-subtitle">{counts['moderate']} results</div>
  <div class="cards">{mod_cards}</div>
</div>"""
        mod_page = wrap_page(f"Moderate Matches — {date_str}", mod_body, extra_js=DASHBOARD_JS)
        mod_dir = site_date_dir / "moderate"
        mod_dir.mkdir(parents=True, exist_ok=True)
        (mod_dir / "index.html").write_text(mod_page)

    return counts


def _format_date_short(date_str: str) -> str:
    """Format '2026-02-17' as 'Feb 17'."""
    from datetime import datetime as _dt
    try:
        dt = _dt.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%b %-d")
    except ValueError:
        return date_str


def _days_ago(date_str: str) -> str:
    """Return 'Today', 'Yesterday', or 'X days ago'."""
    from datetime import datetime as _dt, timedelta as _td
    try:
        dt = _dt.strptime(date_str, "%Y-%m-%d").date()
        delta = (_dt.now().date() - dt).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Yesterday"
        return f"{delta}d ago"
    except ValueError:
        return ""


def _month_label(date_str: str) -> str:
    """Return 'February 2026' from '2026-02-17'."""
    from datetime import datetime as _dt
    try:
        dt = _dt.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%B %Y")
    except ValueError:
        return "Other"


def build_root_index(dates: list[str], all_counts: dict) -> None:
    sb = sidebar_html(active="history", latest_date=dates[0] if dates else "")

    # Group: first 4 as "Recent", rest by month
    recent = dates[:4]
    older = dates[4:]

    def make_run_card(d: str) -> str:
        c = all_counts.get(d, {})
        chips = ""
        for v in ("strong", "moderate", "stretch", "weak"):
            if v in c:
                chips += f'<span class="stat-chip stat-{v}">{c[v]} {v.upper()}</span> '
        total = sum(c.values())
        elapsed = _days_ago(d)
        elapsed_html = f'<span class="run-elapsed">{elapsed}</span>' if elapsed else ""
        return f"""
<div class="run-item">
  <div class="run-item-header">
    <a href="./{d}/">{_format_date_short(d)}</a>
    {elapsed_html}
  </div>
  <div class="run-stats">{chips}</div>
  <div class="run-total">{total} jobs evaluated</div>
</div>"""

    sections_html = ""

    if recent:
        cards = "\n".join(make_run_card(d) for d in recent)
        sections_html += f"""
<div class="history-section">
  <div class="history-section-title">Recent</div>
  <div class="run-list">{cards}</div>
</div>"""

    if older:
        months: dict[str, list[str]] = {}
        for d in older:
            ml = _month_label(d)
            months.setdefault(ml, []).append(d)

        for month, month_dates in months.items():
            cards = "\n".join(make_run_card(d) for d in month_dates)
            sections_html += f"""
<div class="history-section">
  <div class="history-section-title">{month}</div>
  <div class="run-list">{cards}</div>
</div>"""

    body = f"""
<nav class="topnav">
  {SIDEBAR_TOGGLE}
  <span class="brand">Job Scan</span>
  <span class="spacer"></span>
</nav>
<div class="container main-content">
  <div class="page-title">Scan History</div>
  <div class="page-subtitle">All automated job scan runs</div>
  {sections_html}
</div>"""

    page = wrap_page("Job Scan — History", body, sidebar=sb, sidebar_default="open")
    (SITE_DIR / "index.html").write_text(page)


# ---------------------------------------------------------------------------
# Freelance site builders
# ---------------------------------------------------------------------------

def get_freelance_dates() -> list[str]:
    """Return sorted list of YYYY-MM-DD subdirs inside freelance/."""
    if not FREELANCE_DIR.exists():
        return []
    dates = []
    for item in sorted(FREELANCE_DIR.iterdir(), reverse=True):
        if item.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", item.name):
            dates.append(item.name)
    return dates


def parse_company_file(md_path: Path, tier: str) -> dict:
    """Extract structured data from a company evaluation markdown file."""
    text = md_path.read_text()
    lines = text.split("\n")

    info = {
        "filename": md_path.stem,
        "tier": tier,
        "name": "",
        "location": "",
        "category": "",
        "website": "",
        "relationship": "",
        "discovered": "",
        "fit_score": 0,
        "fit_summary": "",
        "has_outreach": False,
        "outreach_subject": "",
    }

    # Parse H1: "# Company Name — City, State"
    for line in lines:
        if line.startswith("# "):
            parts = line[2:].split(" — ", 1)
            info["name"] = parts[0].strip()
            if len(parts) > 1:
                info["location"] = parts[1].strip()
            break

    # Parse metadata lines
    for line in lines:
        if "**Category:**" in line:
            m = re.search(r"\*\*Category:\*\*\s*([^|]+)", line)
            if m:
                info["category"] = m.group(1).strip()
            m = re.search(r"\*\*Website:\*\*\s*(\S+)", line)
            if m:
                info["website"] = m.group(1).strip()
        elif "**Relationship:**" in line:
            m = re.search(r"\*\*Relationship:\*\*\s*([^|]+)", line)
            if m:
                info["relationship"] = m.group(1).strip()
            m = re.search(r"\*\*Discovered:\*\*\s*(\S+)", line)
            if m:
                info["discovered"] = m.group(1).strip()

    # Parse trailing tags
    for line in lines:
        if line.startswith("FIT_SCORE:"):
            try:
                info["fit_score"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("FIT_SUMMARY:"):
            info["fit_summary"] = line.split(":", 1)[1].strip()

    # Detect outreach draft
    for line in lines:
        if "## Cold Outreach Draft" in line or "**SUBJECT:**" in line:
            info["has_outreach"] = True
        if "**SUBJECT:**" in line:
            info["outreach_subject"] = line.split("**SUBJECT:**", 1)[1].strip()

    return info


def build_company_eval_page(md_path: Path, out_dir: Path, tier: str, info: dict) -> str:
    """Convert a company .md eval to a styled .html page."""
    html_name = md_path.stem + ".html"

    md_converter.reset()
    raw_md = md_path.read_text()
    # Remove the H1 header block and trailing FIT_ tags from rendered HTML
    raw_md = re.sub(r'^#\s+.+?\n---', '---', raw_md, count=1, flags=re.DOTALL)
    raw_md = re.sub(r'\nFIT_TIER:.*$', '', raw_md, flags=re.MULTILINE)
    raw_md = re.sub(r'\nFIT_SCORE:.*$', '', raw_md, flags=re.MULTILINE)
    raw_md = re.sub(r'\nFIT_SUMMARY:.*$', '', raw_md, flags=re.MULTILINE)
    content_html = md_converter.convert(raw_md)

    tier_lower = tier.lower()
    chips = []
    if info.get("category"):
        chips.append(f'<span class="eval-chip">🎛 {info["category"]}</span>')
    if info.get("location"):
        chips.append(f'<span class="eval-chip">📍 {info["location"]}</span>')
    if info.get("fit_score"):
        chips.append(f'<span class="eval-chip">⭐ Score: {info["fit_score"]}</span>')
    meta_html = "\n        ".join(chips)

    actions = ""
    if info.get("website"):
        website = info["website"].rstrip("|").strip()
        if website and website.startswith("http"):
            actions = f'<a href="{website}" target="_blank" rel="noopener" class="eval-btn eval-btn-primary">Visit Website ↗</a>'

    outreach_note = ""
    if info.get("outreach_subject"):
        outreach_note = f'<div class="outreach-subject">✉ Subject: {info["outreach_subject"]}</div>'

    body = f"""
<nav class="topnav">
  <a href="../" class="brand">← Prospects</a>
  <span class="spacer"></span>
  <span class="badge badge-{tier_lower}">{tier_lower.upper()}</span>
</nav>
<div class="container">
  <div class="eval-wrap">
    <div class="eval-hero">
      <div class="eval-hero-title">{info.get("name", md_path.stem)}</div>
      <div class="eval-hero-company">{info.get("location", "")}</div>
      <div class="eval-hero-meta">
        <span class="badge badge-{tier_lower}">{tier_lower.upper()}</span>
        {meta_html}
      </div>
      {outreach_note}
      {f'<div class="eval-actions">{actions}</div>' if actions else ""}
    </div>
    <div class="eval-content">{content_html}</div>
  </div>
</div>"""

    page = wrap_page(f"{info.get('name', md_path.stem)} — Freelance Prospect", body)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / html_name).write_text(page)
    return html_name


FREELANCE_DASH_JS = """\
(function() {
  var cards = window.__CARDS__ || [];
  var grid = document.getElementById('grid');
  var sentinel = document.getElementById('sentinel');
  var search = document.getElementById('search');
  var tierBtns = document.querySelectorAll('.tier-btn');
  var BATCH = 24;
  var rendered = 0;
  var filtered = [];

  function cardHtml(c) {
    var badge = '<span class="badge badge-' + c.tier.toLowerCase() + '">' + c.tier + '</span>';
    var loc = c.location ? '<span>📍 ' + c.location + '</span>' : '';
    var cat = c.category ? '<span>🎛 ' + c.category + '</span>' : '';
    var score = c.fit_score ? '<span>⭐ ' + c.fit_score + '</span>' : '';
    var meta = [loc, cat, score].filter(Boolean).join(' ');
    var outreach = c.has_outreach
      ? '<span class="badge" style="background:rgba(16,185,129,.1);color:#6ee7b7;border:1px solid rgba(16,185,129,.2);font-size:.55rem">✉ outreach ready</span>'
      : '';
    return '<div class="card" data-tier="' + c.tier.toLowerCase() + '" data-href="' + c.tier.toLowerCase() + '/' + c.filename + '.html">' +
      '<div class="card-header">' + badge + outreach + '</div>' +
      '<div class="card-title">' + c.name + '</div>' +
      '<div class="card-meta">' + meta + '</div>' +
      '<div class="card-summary">' + (c.fit_summary || '') + '</div>' +
      '<div class="card-footer"><a href="' + c.tier.toLowerCase() + '/' + c.filename + '.html" class="card-link">View evaluation →</a></div>' +
      '</div>';
  }

  function renderBatch(n) {
    var end = Math.min(rendered + n, filtered.length);
    var html = '';
    for (var i = rendered; i < end; i++) html += cardHtml(filtered[i]);
    grid.insertAdjacentHTML('beforeend', html);
    rendered = end;
  }

  function applyFilters() {
    var q = search ? search.value.toLowerCase() : '';
    var activeTier = 'all';
    tierBtns.forEach(function(b) { if (b.classList.contains('active')) activeTier = b.dataset.tier; });
    filtered = cards.filter(function(c) {
      if (activeTier !== 'all' && c.tier.toLowerCase() !== activeTier) return false;
      if (q) {
        var text = (c.name + ' ' + c.location + ' ' + c.category + ' ' + c.fit_summary).toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
    grid.innerHTML = '';
    rendered = 0;
    renderBatch(BATCH);
  }

  tierBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      tierBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      applyFilters();
    });
  });
  if (search) search.addEventListener('input', applyFilters);

  if ('IntersectionObserver' in window && sentinel) {
    var obs = new IntersectionObserver(function(entries) {
      if (entries[0].isIntersecting && rendered < filtered.length) renderBatch(BATCH);
    }, { rootMargin: '400px' });
    obs.observe(sentinel);
  }

  grid.addEventListener('click', function(e) {
    if (e.target.closest('a')) return;
    var card = e.target.closest('.card');
    if (card && card.dataset.href) window.location.href = card.dataset.href;
  });

  applyFilters();
})();
"""


def build_freelance_date_index(date_str: str) -> dict:
    """Build the freelance prospects dashboard for a single date. Returns tier counts."""
    run_dir = FREELANCE_DIR / date_str
    site_date_dir = FREELANCE_SITE_DIR / date_str

    all_companies = []
    counts = {}

    for tier in ("hot", "warm", "cold"):
        tier_dir = run_dir / tier
        if not tier_dir.is_dir():
            continue
        md_files = sorted(tier_dir.glob("*.md"))
        if not md_files:
            continue
        out_dir = site_date_dir / tier
        counts[tier] = len(md_files)
        for md_path in md_files:
            info = parse_company_file(md_path, tier.upper())
            build_company_eval_page(md_path, out_dir, tier.upper(), info)
            all_companies.append(info)

    # Build card data JSON for client-side rendering
    cards_data = [
        {
            "name": c["name"],
            "location": c["location"],
            "category": c["category"],
            "tier": c["tier"],
            "filename": c["filename"],
            "fit_score": c["fit_score"],
            "fit_summary": c["fit_summary"],
            "has_outreach": c["has_outreach"],
        }
        for c in all_companies
    ]
    cards_json = json.dumps(cards_data, separators=(",", ":"))

    stats_html = ""
    for t in ("hot", "warm", "cold"):
        if t in counts:
            stats_html += f'<span class="stat-chip stat-{t}">{counts[t]} {t.upper()}</span>\n'
    total = sum(counts.values())

    tier_pills = f'<button class="tier-btn active" data-tier="all">All ({total})</button>'
    for t in ("hot", "warm", "cold"):
        if t in counts:
            tier_pills += f'<button class="tier-btn" data-tier="{t}">{t.upper()} ({counts[t]})</button>'

    sb = sidebar_html(active="freelance", root="../../")

    body = f"""
<nav class="topnav">
  {SIDEBAR_TOGGLE}
  <span class="brand">Freelance Prospects</span>
  <span class="nav-date">{date_str}</span>
  <span class="spacer"></span>
</nav>
<div class="container main-content">
  <div class="stats">{stats_html}</div>
  <div class="filter-row">
    <input type="text" class="search-box" id="search" placeholder="Search companies, locations, categories...">
  </div>
  <div class="filter-row">
    <label>Tier</label>
    {tier_pills}
  </div>
  <div class="card-grid" id="grid"></div>
  <div id="sentinel" style="height:1px"></div>
</div>"""

    js = f"window.__CARDS__={cards_json};\n{FREELANCE_DASH_JS}"
    page = wrap_page(f"Freelance Prospects — {date_str}", body, extra_js=js, sidebar=sb,
                     sidebar_default="open")
    site_date_dir.mkdir(parents=True, exist_ok=True)
    (site_date_dir / "index.html").write_text(page)
    return counts


def build_freelance_root_index(dates: list[str], all_counts: dict) -> None:
    """Build the freelance history / root index page."""
    sb = sidebar_html(active="freelance", root="../")

    def make_run_card(d: str) -> str:
        c = all_counts.get(d, {})
        chips = ""
        for t in ("hot", "warm", "cold"):
            if t in c:
                chips += f'<span class="stat-chip stat-{t}">{c[t]} {t.upper()}</span> '
        total = sum(c.values())
        elapsed = _days_ago(d)
        elapsed_html = f'<span class="run-elapsed">{elapsed}</span>' if elapsed else ""
        return f"""
<div class="run-item">
  <div class="run-item-header">
    <a href="./{d}/">{_format_date_short(d)}</a>
    {elapsed_html}
  </div>
  <div class="run-stats">{chips}</div>
  <div class="run-total">{total} prospects evaluated</div>
</div>"""

    recent = dates[:4]
    older = dates[4:]
    sections_html = ""

    if recent:
        cards = "\n".join(make_run_card(d) for d in recent)
        sections_html += f"""
<div class="history-section">
  <div class="history-section-title">Recent</div>
  <div class="run-list">{cards}</div>
</div>"""

    if older:
        months: dict[str, list[str]] = {}
        for d in older:
            ml = _month_label(d)
            months.setdefault(ml, []).append(d)
        for month, month_dates in months.items():
            cards = "\n".join(make_run_card(d) for d in month_dates)
            sections_html += f"""
<div class="history-section">
  <div class="history-section-title">{month}</div>
  <div class="run-list">{cards}</div>
</div>"""

    body = f"""
<nav class="topnav">
  {SIDEBAR_TOGGLE}
  <span class="brand">Freelance Prospects</span>
  <span class="spacer"></span>
</nav>
<div class="container main-content">
  <div class="page-title">Freelance Prospect History</div>
  <div class="page-subtitle">All automated freelance discovery runs</div>
  {sections_html}
</div>"""

    page = wrap_page("Freelance Prospects — History", body, sidebar=sb, sidebar_default="open")
    FREELANCE_SITE_DIR.mkdir(parents=True, exist_ok=True)
    (FREELANCE_SITE_DIR / "index.html").write_text(page)


def main():
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    dates = get_run_dates()
    if not dates:
        print("No results found in results/ directory.")
        return

    print(f"Building site for {len(dates)} run(s): {', '.join(dates)}")

    all_counts = {}
    for date_str in dates:
        counts = build_date_index(date_str)
        all_counts[date_str] = counts
        total = sum(counts.values())
        print(f"  Built {date_str}/ — {total} evaluations")

    build_root_index(dates, all_counts)

    # Freelance section
    fl_dates = get_freelance_dates()
    if fl_dates:
        print(f"Building freelance site for {len(fl_dates)} run(s): {', '.join(fl_dates)}")
        fl_counts = {}
        for date_str in fl_dates:
            counts = build_freelance_date_index(date_str)
            fl_counts[date_str] = counts
            total = sum(counts.values())
            print(f"  Built freelance/{date_str}/ — {total} prospects")
        build_freelance_root_index(fl_dates, fl_counts)
    else:
        print("No freelance results found — skipping freelance site build.")

    print(f"Site generated at {SITE_DIR}/")


if __name__ == "__main__":
    main()
