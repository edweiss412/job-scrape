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
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import markdown

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
SITE_DIR = SCRIPT_DIR / "docs"

md_converter = markdown.Markdown(extensions=["tables", "fenced_code"])

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
# CSS (resend.com-inspired dark design)
# ---------------------------------------------------------------------------

SHARED_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --bg: #050505; --bg-card: rgba(255,255,255,.03); --bg-nav: rgba(5,5,5,.85);
  --bg-hover: rgba(255,255,255,.06);
  --text: #ededed; --text-muted: #888; --text-dim: #555;
  --text-link: #ededed;
  --border: rgba(255,255,255,.06); --border-hover: rgba(255,255,255,.12);
  --shadow: none; --shadow-hover: 0 0 0 1px rgba(255,255,255,.08);
  --radius: 16px; --radius-sm: 10px;
  --accent: #00a3ff;
  --strong: #34d399; --strong-bg: rgba(52,211,153,.08); --strong-border: rgba(52,211,153,.15);
  --moderate: #fbbf24; --moderate-bg: rgba(251,191,36,.08); --moderate-border: rgba(251,191,36,.15);
  --stretch: #888; --stretch-bg: rgba(136,136,136,.08); --stretch-border: rgba(136,136,136,.15);
  --weak: #555; --weak-bg: rgba(85,85,85,.06); --weak-border: rgba(85,85,85,.12);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--text-link); text-decoration: none; }
a:hover { color: #fff; }

/* Nav */
.topnav {
  position: sticky; top: 0; z-index: 100;
  background: var(--bg-nav); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  padding: .75rem 1.25rem;
  display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;
}
.topnav .brand {
  font-weight: 600; font-size: .9rem; color: var(--text-muted);
  transition: color .15s;
}
.topnav .brand:hover { color: #fff; text-decoration: none; }
.topnav .spacer { flex: 1; }
.topnav .nav-date { font-size: .8rem; color: var(--text-dim); }

/* Container */
.container { max-width: 1200px; margin: 0 auto; padding: 1.5rem 1.25rem; }

/* Filters */
.filter-row {
  display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .6rem; align-items: center;
}
.filter-row label {
  font-size: .7rem; font-weight: 600; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: .06em; margin-right: .3rem;
  white-space: nowrap;
}
.search-box {
  flex: 1; min-width: 200px; padding: .5rem .85rem;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); color: var(--text); font-size: .85rem;
  font-family: inherit; transition: border-color .2s;
}
.search-box:focus { outline: none; border-color: rgba(255,255,255,.2); }
.search-box::placeholder { color: var(--text-dim); }

/* Pills */
.filter-btn, .loc-btn, .pay-btn {
  padding: .35rem .75rem; border: 1px solid var(--border);
  border-radius: 20px; background: transparent; color: var(--text-muted);
  font-size: .75rem; font-weight: 500; cursor: pointer; transition: all .15s;
  white-space: nowrap; font-family: inherit;
}
.filter-btn:hover, .loc-btn:hover, .pay-btn:hover {
  border-color: var(--border-hover); color: var(--text); background: var(--bg-hover);
}
.filter-btn.active { background: #fff; color: #000; border-color: #fff; }
.loc-btn.active, .pay-btn.active {
  background: rgba(255,255,255,.1); color: #fff; border-color: rgba(255,255,255,.2);
}

/* Dropdowns */
.filter-select {
  padding: .4rem .7rem; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); color: var(--text); font-size: .8rem;
  cursor: pointer; font-family: inherit;
}
.filter-select:focus { outline: none; border-color: rgba(255,255,255,.2); }

/* Stats */
.stats { display: flex; gap: .5rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
.stat-chip {
  padding: .3rem .7rem; border-radius: 20px; font-size: .75rem; font-weight: 600;
}
.stat-strong { background: var(--strong-bg); color: var(--strong); border: 1px solid var(--strong-border); }
.stat-moderate { background: var(--moderate-bg); color: var(--moderate); border: 1px solid var(--moderate-border); }
.stat-stretch { background: var(--stretch-bg); color: var(--stretch); border: 1px solid var(--stretch-border); }
.stat-weak { background: var(--weak-bg); color: var(--weak); border: 1px solid var(--weak-border); }

.results-count { font-size: .75rem; color: var(--text-dim); margin-bottom: .75rem; }

/* Cards grid */
.cards { display: grid; grid-template-columns: 1fr; gap: .6rem; }
@media (min-width: 640px) { .cards { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .cards { grid-template-columns: repeat(3, 1fr); } }

.card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem 1.1rem; transition: all .2s;
  display: flex; flex-direction: column; gap: .4rem;
}
.card:hover { border-color: var(--border-hover); background: var(--bg-hover); }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; }
.card-company { font-size: .75rem; color: var(--text-dim); font-weight: 500; }
.card-title { font-size: .9rem; font-weight: 600; line-height: 1.35; color: #fff; }
.card-meta { display: flex; gap: .6rem; flex-wrap: wrap; font-size: .75rem; color: var(--text-muted); }
.card-summary { font-size: .8rem; color: var(--text-muted); line-height: 1.55; flex: 1; }
.card-footer { display: flex; justify-content: space-between; align-items: center; margin-top: auto; padding-top: .4rem; }
.card-link {
  font-size: .75rem; font-weight: 500; color: var(--text-muted);
  transition: color .15s;
}
.card-link:hover { color: #fff; text-decoration: none; }

/* Badge */
.badge {
  display: inline-block; padding: .15rem .5rem; border-radius: 6px;
  font-size: .65rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
}
.badge-strong { background: var(--strong-bg); color: var(--strong); border: 1px solid var(--strong-border); }
.badge-moderate { background: var(--moderate-bg); color: var(--moderate); border: 1px solid var(--moderate-border); }
.badge-stretch { background: var(--stretch-bg); color: var(--stretch); border: 1px solid var(--stretch-border); }
.badge-weak { background: var(--weak-bg); color: var(--weak); border: 1px solid var(--weak-border); }

/* ---- Eval page ---- */
.eval-wrap { max-width: 860px; margin: 0 auto; }
@media (min-width: 1200px) { .eval-wrap { max-width: 960px; } }

.eval-hero {
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--bg-card); padding: 2rem; margin-bottom: 1.5rem;
}
.eval-hero-title { font-size: 1.6rem; font-weight: 700; color: #fff; line-height: 1.3; margin-bottom: .3rem; }
@media (min-width: 640px) { .eval-hero-title { font-size: 1.8rem; } }
.eval-hero-company { font-size: .95rem; color: var(--text-muted); margin-bottom: .75rem; }
.eval-hero-meta { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .75rem; }
.eval-chip {
  display: inline-flex; align-items: center; gap: .25rem;
  padding: .3rem .65rem; border-radius: 20px; font-size: .75rem; font-weight: 500;
  background: var(--bg-hover); border: 1px solid var(--border); color: var(--text-muted);
}
.eval-actions { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .75rem; }
.eval-btn {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .5rem 1rem; border-radius: var(--radius-sm); font-size: .8rem; font-weight: 600;
  text-decoration: none; transition: all .15s; font-family: inherit;
  border: 1px solid var(--border);
}
.eval-btn:hover { text-decoration: none; }
.eval-btn-primary { background: #fff; color: #000; border-color: #fff; }
.eval-btn-primary:hover { background: #ddd; }
.eval-btn-ghost { background: transparent; color: var(--text-muted); }
.eval-btn-ghost:hover { color: #fff; border-color: var(--border-hover); }

/* Tabs */
.eval-tabs { display: flex; gap: 0; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); }
.eval-tab {
  padding: .6rem 1rem; font-size: .8rem; font-weight: 500; color: var(--text-muted);
  cursor: pointer; border: none; background: none; font-family: inherit;
  border-bottom: 2px solid transparent; transition: all .15s; margin-bottom: -1px;
}
.eval-tab:hover { color: var(--text); }
.eval-tab.active { color: #fff; border-bottom-color: #fff; }
.eval-tab-panel { display: none; }
.eval-tab-panel.active { display: block; }

/* Eval content styling */
.eval-content h1 { display: none; }
.eval-content h2 { font-size: 1rem; font-weight: 600; margin-top: 1.5rem; margin-bottom: .5rem; color: #fff; }
.eval-content h3 {
  font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em;
  color: var(--text-dim); margin-top: 2rem; margin-bottom: .75rem;
  padding-bottom: .5rem; border-bottom: 1px solid var(--border);
}
.eval-content p { margin-bottom: .75rem; line-height: 1.75; font-size: .9rem; color: var(--text-muted); }
.eval-content ul, .eval-content ol { margin-bottom: .75rem; padding-left: 1.5rem; }
.eval-content li { margin-bottom: .5rem; line-height: 1.7; font-size: .9rem; color: var(--text-muted); }
.eval-content hr { display: none; }
.eval-content strong { color: var(--text); font-weight: 600; }
.eval-content em { color: var(--text-dim); }
.eval-content code { background: var(--bg-hover); padding: 2px 6px; border-radius: 4px; font-size: .85em; }
.eval-content blockquote {
  border-left: 2px solid var(--border-hover); margin: .75rem 0; padding: .5rem 1rem;
  background: var(--bg-card); border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.eval-content blockquote p { color: var(--text); }

/* Run history */
.run-list { list-style: none; }
.run-item {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1rem 1.1rem; margin-bottom: .6rem; transition: all .2s;
}
.run-item:hover { border-color: var(--border-hover); background: var(--bg-hover); }
.run-item a { font-weight: 600; font-size: .95rem; color: #fff; }
.run-item a:hover { text-decoration: none; }
.run-item .run-stats { margin-top: .4rem; display: flex; gap: .4rem; flex-wrap: wrap; }

/* Empty / no results */
.empty { text-align: center; padding: 3rem 1rem; color: var(--text-dim); }
.no-results { display: none; text-align: center; padding: 2rem; color: var(--text-dim); }

/* Page title */
.page-title {
  font-size: 1.2rem; font-weight: 700; color: #fff; margin-bottom: .25rem;
}
.page-subtitle { font-size: .8rem; color: var(--text-dim); margin-bottom: 1.25rem; }
"""

DASHBOARD_JS = """\
(function() {
  var grid = document.querySelector('.cards');
  if (!grid) return;
  var cards = Array.from(grid.querySelectorAll('.card'));
  var searchBox = document.getElementById('search');
  var verdictBtns = document.querySelectorAll('.filter-btn');
  var locBtns = document.querySelectorAll('.loc-btn');
  var payBtns = document.querySelectorAll('.pay-btn');
  var tierSelect = document.getElementById('tierFilter');
  var sortSelect = document.getElementById('sortSelect');
  var noResults = document.getElementById('noResults');
  var countEl = document.getElementById('resultsCount');

  var activeVerdict = 'all';
  var activeCity = 'all';
  var activePay = 'all';

  var payRanges = {
    'all': [0, Infinity],
    'u100': [1, 99999],
    '100-130': [100000, 130000],
    '130-160': [130000, 160000],
    '160-200': [160000, 200000],
    '200+': [200000, Infinity],
    'unlisted': [0, 0]
  };

  function matchPay(card) {
    if (activePay === 'all') return true;
    var s = parseInt(card.dataset.salary) || 0;
    if (activePay === 'unlisted') return s === 0;
    var range = payRanges[activePay];
    return s >= range[0] && s <= range[1];
  }

  function passesOtherFilters(card, exclude) {
    var q = (searchBox ? searchBox.value : '').toLowerCase();
    var tier = tierSelect ? tierSelect.value : 'all';
    if (exclude !== 'verdict' && activeVerdict !== 'all' && card.dataset.verdict !== activeVerdict) return false;
    if (exclude !== 'city' && activeCity !== 'all' && card.dataset.city !== activeCity) return false;
    if (exclude !== 'pay' && !matchPay(card)) return false;
    if (exclude !== 'tier' && tier !== 'all' && card.dataset.tier !== tier) return false;
    if (exclude !== 'search' && q && card.dataset.search.indexOf(q) === -1) return false;
    return true;
  }

  function updateCounts() {
    verdictBtns.forEach(function(btn) {
      var f = btn.dataset.filter;
      var ct = 0;
      cards.forEach(function(card) {
        if (passesOtherFilters(card, 'verdict') && (f === 'all' || card.dataset.verdict === f)) ct++;
      });
      btn.textContent = btn.dataset.label + ' (' + ct + ')';
    });
    locBtns.forEach(function(btn) {
      var c = btn.dataset.city;
      var ct = 0;
      cards.forEach(function(card) {
        if (passesOtherFilters(card, 'city') && (c === 'all' || card.dataset.city === c)) ct++;
      });
      btn.textContent = btn.dataset.label + ' (' + ct + ')';
    });
    payBtns.forEach(function(btn) {
      var p = btn.dataset.pay;
      var ct = 0;
      cards.forEach(function(card) {
        if (!passesOtherFilters(card, 'pay')) return;
        var s = parseInt(card.dataset.salary) || 0;
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
    var q = (searchBox ? searchBox.value : '').toLowerCase();
    var tier = tierSelect ? tierSelect.value : 'all';
    var visible = 0;
    cards.forEach(function(card) {
      var show = (activeVerdict === 'all' || card.dataset.verdict === activeVerdict)
        && (activeCity === 'all' || card.dataset.city === activeCity)
        && matchPay(card)
        && (tier === 'all' || card.dataset.tier === tier)
        && (!q || card.dataset.search.indexOf(q) !== -1);
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    if (noResults) noResults.style.display = visible === 0 ? 'block' : 'none';
    if (countEl) countEl.textContent = visible + ' result' + (visible !== 1 ? 's' : '');
    updateCounts();
  }

  function hideZeroPills(btns, activeAttr) {
    btns.forEach(function(btn) {
      var isAll = btn.dataset[activeAttr] === 'all';
      var isActive = btn.classList.contains('active');
      var ct = parseInt(btn.textContent.match(/\\((\\d+)\\)/)?.[1] || '0');
      btn.style.display = (isAll || isActive || ct > 0) ? '' : 'none';
    });
  }

  function bindPills(btns, stateKey) {
    btns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        btns.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        if (stateKey === 'verdict') activeVerdict = btn.dataset.filter;
        else if (stateKey === 'city') activeCity = btn.dataset.city;
        else if (stateKey === 'pay') activePay = btn.dataset.pay;
        applyFilters();
      });
    });
  }
  bindPills(verdictBtns, 'verdict');
  bindPills(locBtns, 'city');
  bindPills(payBtns, 'pay');

  if (tierSelect) tierSelect.addEventListener('change', applyFilters);
  if (searchBox) searchBox.addEventListener('input', applyFilters);

  function sortCards(key) {
    cards.sort(function(a, b) {
      if (key === 'salary-desc') return (parseInt(b.dataset.salary)||0) - (parseInt(a.dataset.salary)||0);
      if (key === 'salary-asc') {
        var sa = parseInt(a.dataset.salary)||0, sb = parseInt(b.dataset.salary)||0;
        if (!sa && !sb) return 0; if (!sa) return 1; if (!sb) return -1;
        return sa - sb;
      }
      if (key === 'verdict') return (parseInt(a.dataset.verdictOrder)||0) - (parseInt(b.dataset.verdictOrder)||0);
      if (key === 'company') return (a.dataset.company||'').localeCompare(b.dataset.company||'');
      return 0;
    });
    cards.forEach(function(card) { grid.appendChild(card); });
  }

  if (sortSelect) sortSelect.addEventListener('change', function() {
    if (this.value !== 'default') sortCards(this.value);
    applyFilters();
  });

  updateCounts();
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

def wrap_page(title: str, body_html: str, extra_js: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{SHARED_CSS}</style>
</head>
<body>
{body_html}
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


def build_card_html(job: dict, date_str: str, verdict: str) -> str:
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

    # Build dashboard cards and collect filter dimensions
    cards_html = ""
    cities = {}
    tiers = {}
    for verdict, job in all_jobs:
        cards_html += build_card_html(job, date_str, verdict) + "\n"
        city = normalize_city(job["location"])
        if city:
            cities[city] = cities.get(city, 0) + 1
        tier_key = job["tier"].split("—")[0].strip() if job["tier"] else ""
        if tier_key:
            tiers[tier_key] = tiers.get(tier_key, 0) + 1

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

    verdict_pills = f'<button class="filter-btn active" data-filter="all" data-label="All">All ({total})</button>'
    for v in ("strong", "moderate", "stretch", "weak"):
        if v in counts:
            verdict_pills += f'<button class="filter-btn" data-filter="{v}" data-label="{v.title()}">{v.title()} ({counts[v]})</button>'

    body = f"""
<nav class="topnav">
  <a href="../" class="brand">Job Scan</a>
  <span class="nav-date">{date_str}</span>
  <span class="spacer"></span>
</nav>
<div class="container">
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

  <div class="results-count" id="resultsCount">{total} results</div>

  <div class="cards">
    {cards_html}
  </div>
  <div class="no-results" id="noResults">No matches found.</div>
</div>"""

    page = wrap_page(f"Job Scan — {date_str}", body, extra_js=DASHBOARD_JS)
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


def build_root_index(dates: list[str], all_counts: dict) -> None:
    items_html = ""
    for d in dates:
        c = all_counts.get(d, {})
        chips = ""
        for v in ("strong", "moderate", "stretch", "weak"):
            if v in c:
                chips += f'<span class="stat-chip stat-{v}">{c[v]} {v.upper()}</span> '
        items_html += f"""
<div class="run-item">
  <a href="./{d}/">{d}</a>
  <div class="run-stats">{chips}</div>
</div>"""

    body = f"""
<nav class="topnav">
  <span class="brand" style="color:#fff;">Job Scan</span>
  <span class="spacer"></span>
</nav>
<div class="container">
  <div class="page-title">Scan History</div>
  <div class="page-subtitle">All automated job scan runs</div>
  <div class="run-list">{items_html}</div>
</div>"""

    page = wrap_page("Job Scan", body)
    (SITE_DIR / "index.html").write_text(page)


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
    print(f"Site generated at {SITE_DIR}/")


if __name__ == "__main__":
    main()
