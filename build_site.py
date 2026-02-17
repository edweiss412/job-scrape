#!/usr/bin/env python3
"""
Build a modern static HTML dashboard from markdown evaluation results.
Outputs to site/ for GitHub Pages deployment.

Features:
  - Mobile-first responsive card layout
  - Filter by verdict, location
  - Search across job titles and companies
  - Dark mode toggle (respects system preference)
  - Individual evaluation pages with clean typography

Usage:
    python build_site.py
"""

import json
import re
from pathlib import Path

import markdown

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
SITE_DIR = SCRIPT_DIR / "site"

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

    # Header: "# Title — Company"
    for line in lines:
        if line.startswith("# "):
            parts = line[2:].split(" — ", 1)
            info["title"] = parts[0].strip()
            if len(parts) > 1:
                info["company"] = parts[1].strip()
            break

    # Metadata fields
    for line in lines:
        if line.startswith("**Location:**"):
            info["location"] = line.split("**Location:**")[1].strip()
        elif line.startswith("**Salary:**"):
            info["salary"] = line.split("**Salary:**")[1].strip()
        elif line.startswith("**Tier:**"):
            info["tier"] = line.split("**Tier:**")[1].strip()
        elif line.startswith("**URL:**"):
            info["url"] = line.split("**URL:**")[1].strip()

    # Extract summary from section 2 (between ### 2. and ### 3.)
    in_section = False
    summary_lines = []
    for line in lines:
        if re.match(r"###\s*2\.", line):
            in_section = True
            continue
        if re.match(r"###\s*3\.", line):
            break
        if in_section and line.strip():
            # Clean markdown formatting
            clean = re.sub(r'\*\*[^*]+\*\*', '', line).strip()
            clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
            if clean:
                summary_lines.append(clean)

    # First line is usually the verdict badge, rest is reasoning
    if summary_lines:
        info["verdict_line"] = summary_lines[0]
        info["summary"] = " ".join(summary_lines[1:])[:250]
    if not info["summary"] and len(summary_lines) > 0:
        info["summary"] = " ".join(summary_lines)[:250]

    # Try to extract location from Role Summary if header location is empty
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
    """Map location to a target city bucket, or 'Other'."""
    if not location:
        return "Other"
    loc_lower = location.lower().strip()
    for pattern, city in TARGET_CITIES.items():
        if pattern in loc_lower:
            return city
    return "Other"


def parse_salary_number(salary: str) -> int:
    """Extract a numeric salary value for sorting. Returns 0 if unparseable."""
    if not salary:
        return 0
    # Find dollar amounts like $135K, $135,000, $135k-$155k
    nums = re.findall(r'\$?([\d,]+)\s*[kK]', salary)
    if nums:
        return int(nums[0].replace(",", "")) * 1000
    nums = re.findall(r'\$?([\d,]+)', salary)
    if nums:
        val = int(nums[0].replace(",", ""))
        return val if val > 1000 else val * 1000
    return 0


VERDICT_ORDER = {"strong": 0, "moderate": 1, "stretch": 2, "weak": 3}


def convert_md_file(md_path: Path) -> str:
    md_converter.reset()
    return md_converter.convert(md_path.read_text())


def get_run_dates() -> list[str]:
    dates = []
    for item in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if item.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", item.name):
            dates.append(item.name)
    return dates


# ---------------------------------------------------------------------------
# CSS + JS (inlined for zero-dependency static site)
# ---------------------------------------------------------------------------

SHARED_CSS = """\
:root {
  --bg: #f8f9fa; --bg-card: #ffffff; --bg-nav: #ffffff;
  --text: #1a1a2e; --text-muted: #6b7280; --text-link: #2563eb;
  --border: #e5e7eb; --border-hover: #d1d5db;
  --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
  --shadow-hover: 0 4px 12px rgba(0,0,0,.1);
  --radius: 12px; --radius-sm: 8px;
  --strong: #059669; --strong-bg: #ecfdf5; --strong-border: #a7f3d0;
  --moderate: #d97706; --moderate-bg: #fffbeb; --moderate-border: #fde68a;
  --stretch: #6b7280; --stretch-bg: #f3f4f6; --stretch-border: #d1d5db;
  --weak: #9ca3af; --weak-bg: #f9fafb; --weak-border: #e5e7eb;
}
[data-theme="dark"] {
  --bg: #0f172a; --bg-card: #1e293b; --bg-nav: #1e293b;
  --text: #e2e8f0; --text-muted: #94a3b8; --text-link: #60a5fa;
  --border: #334155; --border-hover: #475569;
  --shadow: 0 1px 3px rgba(0,0,0,.3);
  --shadow-hover: 0 4px 12px rgba(0,0,0,.4);
  --strong: #34d399; --strong-bg: #064e3b; --strong-border: #065f46;
  --moderate: #fbbf24; --moderate-bg: #451a03; --moderate-border: #78350f;
  --stretch: #94a3b8; --stretch-bg: #1e293b; --stretch-border: #334155;
  --weak: #64748b; --weak-bg: #1e293b; --weak-border: #334155;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6;
  -webkit-font-smoothing: antialiased; transition: background .2s, color .2s;
}
a { color: var(--text-link); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Nav */
.topnav {
  position: sticky; top: 0; z-index: 100;
  background: var(--bg-nav); border-bottom: 1px solid var(--border);
  padding: .75rem 1rem; backdrop-filter: blur(10px);
  display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;
}
.topnav .brand { font-weight: 700; font-size: 1.1rem; white-space: nowrap; }
.topnav .spacer { flex: 1; }
.theme-toggle {
  background: none; border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: .4rem .6rem; cursor: pointer; font-size: 1rem; color: var(--text);
  transition: border-color .2s;
}
.theme-toggle:hover { border-color: var(--text-muted); }

/* Container */
.container { max-width: 1200px; margin: 0 auto; padding: 1rem; }

/* Filters bar */
.filters {
  display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1.25rem;
  align-items: center;
}
.search-box {
  flex: 1; min-width: 200px; padding: .55rem .85rem;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); color: var(--text); font-size: .9rem;
  transition: border-color .2s;
}
.search-box:focus { outline: none; border-color: var(--text-link); }
.filter-btn {
  padding: .45rem .85rem; border: 1px solid var(--border);
  border-radius: 20px; background: var(--bg-card); color: var(--text-muted);
  font-size: .8rem; font-weight: 500; cursor: pointer; transition: all .15s;
  white-space: nowrap;
}
.filter-btn:hover { border-color: var(--text-muted); color: var(--text); }
.filter-btn.active { background: var(--text-link); color: #fff; border-color: var(--text-link); }

/* Filter rows */
.filter-row {
  display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .75rem;
  align-items: center;
}
.filter-row label {
  font-size: .75rem; font-weight: 600; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .04em; margin-right: .25rem;
  white-space: nowrap;
}
.filter-select {
  padding: .4rem .7rem; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); color: var(--text); font-size: .8rem;
  cursor: pointer; transition: border-color .2s;
}
.filter-select:focus { outline: none; border-color: var(--text-link); }
.sort-select { min-width: 140px; }
.loc-btn {
  padding: .35rem .7rem; border: 1px solid var(--border);
  border-radius: 20px; background: var(--bg-card); color: var(--text-muted);
  font-size: .75rem; font-weight: 500; cursor: pointer; transition: all .15s;
  white-space: nowrap;
}
.loc-btn:hover { border-color: var(--text-muted); color: var(--text); }
.loc-btn.active { background: var(--text); color: var(--bg); border-color: var(--text); }
.pay-btn {
  padding: .35rem .7rem; border: 1px solid var(--border);
  border-radius: 20px; background: var(--bg-card); color: var(--text-muted);
  font-size: .75rem; font-weight: 500; cursor: pointer; transition: all .15s;
  white-space: nowrap;
}
.pay-btn:hover { border-color: var(--text-muted); color: var(--text); }
.pay-btn.active { background: var(--text); color: var(--bg); border-color: var(--text); }
.active-filters {
  display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .75rem;
}
.active-filter-tag {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .2rem .6rem; border-radius: 20px; font-size: .75rem;
  background: var(--text-link); color: #fff; cursor: pointer;
}
.active-filter-tag:hover { opacity: .8; }
.results-count {
  font-size: .8rem; color: var(--text-muted); margin-bottom: .75rem;
}

/* Stats strip */
.stats {
  display: flex; gap: .75rem; margin-bottom: 1.25rem; flex-wrap: wrap;
}
.stat-chip {
  padding: .3rem .7rem; border-radius: 20px; font-size: .8rem; font-weight: 600;
}
.stat-strong { background: var(--strong-bg); color: var(--strong); border: 1px solid var(--strong-border); }
.stat-moderate { background: var(--moderate-bg); color: var(--moderate); border: 1px solid var(--moderate-border); }
.stat-stretch { background: var(--stretch-bg); color: var(--stretch); border: 1px solid var(--stretch-border); }
.stat-weak { background: var(--weak-bg); color: var(--weak); border: 1px solid var(--weak-border); }

/* Cards grid */
.cards { display: grid; grid-template-columns: 1fr; gap: .75rem; }
@media (min-width: 640px) { .cards { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .cards { grid-template-columns: repeat(3, 1fr); } }

.card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem; transition: box-shadow .15s, border-color .15s;
  display: flex; flex-direction: column; gap: .5rem;
}
.card:hover { box-shadow: var(--shadow-hover); border-color: var(--border-hover); }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; }
.card-company { font-size: .8rem; color: var(--text-muted); font-weight: 500; }
.card-title { font-size: .95rem; font-weight: 600; line-height: 1.3; }
.card-meta { display: flex; gap: .75rem; flex-wrap: wrap; font-size: .8rem; color: var(--text-muted); }
.card-meta span::before { margin-right: .25rem; }
.card-summary { font-size: .85rem; color: var(--text-muted); line-height: 1.5; flex: 1; }
.card-footer { display: flex; justify-content: space-between; align-items: center; margin-top: auto; }
.badge {
  display: inline-block; padding: .2rem .6rem; border-radius: 6px;
  font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
}
.badge-strong { background: var(--strong-bg); color: var(--strong); border: 1px solid var(--strong-border); }
.badge-moderate { background: var(--moderate-bg); color: var(--moderate); border: 1px solid var(--moderate-border); }
.badge-stretch { background: var(--stretch-bg); color: var(--stretch); border: 1px solid var(--stretch-border); }
.badge-weak { background: var(--weak-bg); color: var(--weak); border: 1px solid var(--weak-border); }
.card-link { font-size: .8rem; font-weight: 500; }

/* Eval page */
.eval-content { max-width: 780px; margin: 0 auto; }
.eval-content h1 { font-size: 1.5rem; margin-bottom: .5rem; }
.eval-content h2 { font-size: 1.2rem; margin-top: 2rem; margin-bottom: .5rem; }
.eval-content h3 { font-size: 1.05rem; margin-top: 1.5rem; margin-bottom: .5rem; color: var(--text-muted); }
.eval-content p { margin-bottom: .75rem; }
.eval-content ul, .eval-content ol { margin-bottom: .75rem; padding-left: 1.5rem; }
.eval-content li { margin-bottom: .35rem; }
.eval-content hr { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
.eval-content strong { color: var(--text); }
.eval-content code { background: var(--stretch-bg); padding: 2px 6px; border-radius: 4px; font-size: .9em; }
.eval-meta { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; font-size: .85rem; color: var(--text-muted); }

/* Run history (root index) */
.run-list { list-style: none; }
.run-item {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1rem; margin-bottom: .75rem; transition: box-shadow .15s;
}
.run-item:hover { box-shadow: var(--shadow-hover); }
.run-item a { font-weight: 600; font-size: 1.05rem; }
.run-item .run-stats { margin-top: .4rem; display: flex; gap: .5rem; flex-wrap: wrap; }

/* Empty state */
.empty { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.no-results { display: none; text-align: center; padding: 2rem; color: var(--text-muted); }
"""

DASHBOARD_JS = """\
(function() {
  // --- Theme ---
  var html = document.documentElement;
  var saved = localStorage.getItem('theme');
  if (saved) html.setAttribute('data-theme', saved);
  else if (matchMedia('(prefers-color-scheme: dark)').matches) html.setAttribute('data-theme', 'dark');

  var tog = document.getElementById('themeToggle');
  if (tog) {
    tog.textContent = html.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
    tog.addEventListener('click', function() {
      var next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      this.textContent = next === 'dark' ? '☀️' : '🌙';
    });
  }

  // --- Filter state ---
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

  // Pay range buckets: [min, max] (max=Infinity for open-ended)
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

  // Test if a card passes all filters EXCEPT one dimension (for dynamic counts)
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
    // Update verdict counts
    verdictBtns.forEach(function(btn) {
      var f = btn.dataset.filter;
      var ct = 0;
      cards.forEach(function(card) {
        if (passesOtherFilters(card, 'verdict') && (f === 'all' || card.dataset.verdict === f)) ct++;
      });
      var label = btn.dataset.label;
      btn.textContent = label + ' (' + ct + ')';
    });

    // Update location counts
    locBtns.forEach(function(btn) {
      var c = btn.dataset.city;
      var ct = 0;
      cards.forEach(function(card) {
        if (passesOtherFilters(card, 'city') && (c === 'all' || card.dataset.city === c)) ct++;
      });
      var label = btn.dataset.label;
      btn.textContent = label + ' (' + ct + ')';
    });

    // Update pay counts
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
      var label = btn.dataset.label;
      btn.textContent = label + ' (' + ct + ')';
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
      var mv = activeVerdict === 'all' || card.dataset.verdict === activeVerdict;
      var mc = activeCity === 'all' || card.dataset.city === activeCity;
      var mp = matchPay(card);
      var mt = tier === 'all' || card.dataset.tier === tier;
      var ms = !q || card.dataset.search.indexOf(q) !== -1;
      var show = mv && mc && mp && mt && ms;
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

  // Verdict pills
  verdictBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      verdictBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeVerdict = btn.dataset.filter;
      applyFilters();
    });
  });

  // Location pills
  locBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      locBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeCity = btn.dataset.city;
      applyFilters();
    });
  });

  // Pay range pills
  payBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      payBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activePay = btn.dataset.pay;
      applyFilters();
    });
  });

  // Tier dropdown
  if (tierSelect) tierSelect.addEventListener('change', applyFilters);

  // Search
  if (searchBox) searchBox.addEventListener('input', applyFilters);

  // --- Sorting ---
  function sortCards(key) {
    cards.sort(function(a, b) {
      if (key === 'salary-desc') {
        return (parseInt(b.dataset.salary) || 0) - (parseInt(a.dataset.salary) || 0);
      } else if (key === 'salary-asc') {
        var sa = parseInt(a.dataset.salary) || 0;
        var sb = parseInt(b.dataset.salary) || 0;
        if (sa === 0 && sb === 0) return 0;
        if (sa === 0) return 1;
        if (sb === 0) return -1;
        return sa - sb;
      } else if (key === 'verdict') {
        return (parseInt(a.dataset.verdictOrder) || 0) - (parseInt(b.dataset.verdictOrder) || 0);
      } else if (key === 'company') {
        return (a.dataset.company || '').localeCompare(b.dataset.company || '');
      }
      return 0;
    });
    cards.forEach(function(card) { grid.appendChild(card); });
  }

  if (sortSelect) {
    sortSelect.addEventListener('change', function() {
      if (this.value !== 'default') sortCards(this.value);
      applyFilters();
    });
  }

  // Initial count render
  updateCounts();
})();
"""

# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def wrap_page(title: str, body_html: str, has_dashboard_js: bool = False) -> str:
    theme_btn_label = "🌙"
    js = f"<script>{DASHBOARD_JS}</script>" if has_dashboard_js else ""
    theme_js = """<script>
(function(){
  var h=document.documentElement,s=localStorage.getItem('theme');
  if(s)h.setAttribute('data-theme',s);
  else if(matchMedia('(prefers-color-scheme:dark)').matches)h.setAttribute('data-theme','dark');
})();
</script>""" if not has_dashboard_js else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{SHARED_CSS}</style>
{theme_js}
</head>
<body>
{body_html}
{js}
</body>
</html>"""


def build_eval_page(md_path: Path, out_dir: Path, date_str: str, verdict: str, job_info: dict) -> str:
    """Convert a single .md eval to a styled .html page. Returns filename."""
    html_name = md_path.stem + ".html"
    md_converter.reset()
    content_html = md_converter.convert(md_path.read_text())

    meta_parts = []
    if job_info.get("location"):
        meta_parts.append(f"📍 {job_info['location']}")
    if job_info.get("salary"):
        meta_parts.append(f"💰 {job_info['salary']}")
    if job_info.get("tier"):
        meta_parts.append(f"🏢 {job_info['tier']}")
    meta_html = " &nbsp;·&nbsp; ".join(meta_parts)

    posting_link = ""
    if job_info.get("url"):
        posting_link = f'<a href="{job_info["url"]}" target="_blank" rel="noopener">View Original Posting ↗</a>'

    body = f"""
<nav class="topnav">
  <a href="/{date_str}/" class="brand">← {date_str}</a>
  <span class="spacer"></span>
  <span class="badge badge-{verdict}">{verdict}</span>
  <button class="theme-toggle" id="themeToggle">🌙</button>
</nav>
<div class="container">
  <div class="eval-content">
    <div class="eval-meta">{meta_html}</div>
    {f'<div style="margin-bottom:1rem">{posting_link}</div>' if posting_link else ''}
    {content_html}
  </div>
</div>"""

    # Inline the theme toggle JS for eval pages
    page = wrap_page(
        f"{job_info.get('title', md_path.stem)} — {job_info.get('company', '')}",
        body,
        has_dashboard_js=True,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / html_name).write_text(page)
    return html_name


def build_card_html(job: dict, date_str: str, verdict: str) -> str:
    """Build a single job card with data attributes for filtering/sorting."""
    loc = f"📍 {job['location']}" if job["location"] else ""
    salary = f"💰 {job['salary']}" if job["salary"] else ""
    tier_display = f"🏢 {job['tier']}" if job["tier"] else ""
    meta_items = " ".join(f"<span>{m}</span>" for m in [loc, salary, tier_display] if m)
    search_text = f"{job['title']} {job['company']} {job['location']} {job['tier']}".lower()
    link = f"/{date_str}/{verdict}/{job['filename']}.html"
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
    <a href="{link}" class="card-link">View evaluation &rarr;</a>
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

        # Build deep eval pages
        deep_dir = verdict_dir / "deep"
        if deep_dir.is_dir():
            deep_out = out_dir / "deep"
            for md_path in sorted(deep_dir.glob("*.md")):
                deep_info = parse_eval_file(md_path, verdict)
                build_eval_page(md_path, deep_out, date_str, f"{verdict}/deep", deep_info)

    # Build dashboard cards and collect filter dimensions
    cards_html = ""
    cities = {}  # city -> count
    tiers = {}   # tier -> count
    for verdict, job in all_jobs:
        cards_html += build_card_html(job, date_str, verdict) + "\n"
        city = normalize_city(job["location"])
        if city:
            cities[city] = cities.get(city, 0) + 1
        tier_key = job["tier"].split("—")[0].strip() if job["tier"] else ""
        if tier_key:
            tiers[tier_key] = tiers.get(tier_key, 0) + 1

    # Stats chips
    stats_html = ""
    for v in ("strong", "moderate", "stretch", "weak"):
        if v in counts:
            stats_html += f'<span class="stat-chip stat-{v}">{counts[v]} {v.upper()}</span>\n'

    total = sum(counts.values())

    # Location pills (sorted by count descending, target cities first)
    sorted_cities = sorted(cities.items(), key=lambda x: -x[1])
    loc_pills = '<button class="loc-btn active" data-city="all" data-label="All">All</button>\n'
    for city, ct in sorted_cities:
        loc_pills += f'<button class="loc-btn" data-city="{city}" data-label="{city}">{city} ({ct})</button>\n'

    # Tier dropdown
    tier_options = '<option value="all">All Tiers</option>\n'
    for tier, ct in sorted(tiers.items()):
        tier_options += f'<option value="{tier}">{tier} ({ct})</option>\n'

    # Pay range pills
    pay_pills = '<button class="pay-btn active" data-pay="all" data-label="All">All</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="u100" data-label="Under $100K">Under $100K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="100-130" data-label="$100–130K">$100–130K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="130-160" data-label="$130–160K">$130–160K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="160-200" data-label="$160–200K">$160–200K</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="200+" data-label="$200K+">$200K+</button>\n'
    pay_pills += '<button class="pay-btn" data-pay="unlisted" data-label="Unlisted">Unlisted</button>\n'

    # Verdict pills with data-label
    verdict_pills = f'<button class="filter-btn active" data-filter="all" data-label="All">All ({total})</button>'
    for v in ("strong", "moderate", "stretch", "weak"):
        if v in counts:
            verdict_pills += f'<button class="filter-btn" data-filter="{v}" data-label="{v.title()}">{v.title()} ({counts[v]})</button>'

    body = f"""
<nav class="topnav">
  <a href="/" class="brand">Job Scan</a>
  <span style="color:var(--text-muted); font-size:.9rem;">{date_str}</span>
  <span class="spacer"></span>
  <button class="theme-toggle" id="themeToggle">🌙</button>
</nav>
<div class="container">
  <div class="stats">{stats_html}</div>

  <div class="filter-row">
    <input type="text" class="search-box" id="search" placeholder="Search jobs, companies, locations...">
  </div>

  <div class="filter-row">
    <label>Match:</label>
    {verdict_pills}
  </div>

  <div class="filter-row">
    <label>Location:</label>
    {loc_pills}
  </div>

  <div class="filter-row">
    <label>Pay:</label>
    {pay_pills}
  </div>

  <div class="filter-row">
    <label>Tier:</label>
    <select class="filter-select" id="tierFilter">
      {tier_options}
    </select>

    <label style="margin-left:.75rem;">Sort:</label>
    <select class="filter-select sort-select" id="sortSelect">
      <option value="default">Default (by verdict)</option>
      <option value="salary-desc">Salary: High &rarr; Low</option>
      <option value="salary-asc">Salary: Low &rarr; High</option>
      <option value="verdict">Verdict strength</option>
      <option value="company">Company A &rarr; Z</option>
    </select>
  </div>

  <div class="results-count" id="resultsCount">{total} results</div>

  <div class="cards">
    {cards_html}
  </div>
  <div class="no-results" id="noResults">No matches found. Try a different search or filter.</div>
</div>"""

    page = wrap_page(f"Job Scan — {date_str}", body, has_dashboard_js=True)
    site_date_dir.mkdir(parents=True, exist_ok=True)
    (site_date_dir / "index.html").write_text(page)

    # Also build a moderate index for email "view all" link
    if "moderate" in counts:
        mod_cards = "\n".join(build_card_html(j, date_str, "moderate") for v, j in all_jobs if v == "moderate")
        mod_body = f"""
<nav class="topnav">
  <a href="/{date_str}/" class="brand">← Back to all</a>
  <span style="color:var(--text-muted); font-size:.9rem;">Moderate Matches</span>
  <span class="spacer"></span>
  <button class="theme-toggle" id="themeToggle">🌙</button>
</nav>
<div class="container">
  <h2 style="margin-bottom:1rem;">All Moderate Matches ({counts['moderate']})</h2>
  <div class="cards">{mod_cards}</div>
</div>"""
        mod_page = wrap_page(f"Moderate Matches — {date_str}", mod_body, has_dashboard_js=True)
        mod_dir = site_date_dir / "moderate"
        mod_dir.mkdir(parents=True, exist_ok=True)
        (mod_dir / "index.html").write_text(mod_page)

    return counts


def build_root_index(dates: list[str], all_counts: dict) -> None:
    """Build root index with run history."""
    items_html = ""
    for d in dates:
        c = all_counts.get(d, {})
        chips = ""
        for v in ("strong", "moderate", "stretch", "weak"):
            if v in c:
                chips += f'<span class="stat-chip stat-{v}">{c[v]} {v.upper()}</span> '
        items_html += f"""
<div class="run-item">
  <a href="/{d}/">{d}</a>
  <div class="run-stats">{chips}</div>
</div>"""

    body = f"""
<nav class="topnav">
  <span class="brand">Job Scan</span>
  <span class="spacer"></span>
  <button class="theme-toggle" id="themeToggle">🌙</button>
</nav>
<div class="container">
  <h1 style="margin-bottom:1rem; font-size:1.4rem;">Scan History</h1>
  <div class="run-list">{items_html}</div>
</div>"""

    page = wrap_page("Job Scan", body, has_dashboard_js=True)
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
