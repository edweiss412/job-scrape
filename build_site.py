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
  // Theme
  const html = document.documentElement;
  const saved = localStorage.getItem('theme');
  if (saved) html.setAttribute('data-theme', saved);
  else if (matchMedia('(prefers-color-scheme: dark)').matches) html.setAttribute('data-theme', 'dark');

  document.getElementById('themeToggle')?.addEventListener('click', function() {
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    this.textContent = next === 'dark' ? '☀️' : '🌙';
  });

  // Filters
  const cards = document.querySelectorAll('.card');
  const searchBox = document.getElementById('search');
  const filterBtns = document.querySelectorAll('.filter-btn');
  const noResults = document.getElementById('noResults');
  let activeFilter = 'all';

  function applyFilters() {
    const q = (searchBox?.value || '').toLowerCase();
    let visible = 0;
    cards.forEach(function(card) {
      const verdict = card.dataset.verdict;
      const text = card.dataset.search;
      const matchVerdict = activeFilter === 'all' || verdict === activeFilter;
      const matchSearch = !q || text.indexOf(q) !== -1;
      const show = matchVerdict && matchSearch;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    if (noResults) noResults.style.display = visible === 0 ? 'block' : 'none';
  }

  filterBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      filterBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      applyFilters();
    });
  });
  searchBox?.addEventListener('input', applyFilters);
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
    """Build a single job card."""
    loc = f"📍 {job['location']}" if job["location"] else ""
    salary = f"💰 {job['salary']}" if job["salary"] else ""
    meta_items = " ".join(f"<span>{m}</span>" for m in [loc, salary] if m)
    search_text = f"{job['title']} {job['company']} {job['location']} {job['tier']}".lower()
    link = f"/{date_str}/{verdict}/{job['filename']}.html"

    return f"""<div class="card" data-verdict="{verdict}" data-search="{search_text}">
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

        # Build deep eval pages
        deep_dir = verdict_dir / "deep"
        if deep_dir.is_dir():
            deep_out = out_dir / "deep"
            for md_path in sorted(deep_dir.glob("*.md")):
                deep_info = parse_eval_file(md_path, verdict)
                build_eval_page(md_path, deep_out, date_str, f"{verdict}/deep", deep_info)

    # Build dashboard cards
    cards_html = ""
    for verdict, job in all_jobs:
        cards_html += build_card_html(job, date_str, verdict) + "\n"

    # Stats chips
    stats_html = ""
    for v in ("strong", "moderate", "stretch", "weak"):
        if v in counts:
            stats_html += f'<span class="stat-chip stat-{v}">{counts[v]} {v.upper()}</span>\n'

    total = sum(counts.values())

    body = f"""
<nav class="topnav">
  <a href="/" class="brand">Job Scan</a>
  <span style="color:var(--text-muted); font-size:.9rem;">{date_str}</span>
  <span class="spacer"></span>
  <button class="theme-toggle" id="themeToggle">🌙</button>
</nav>
<div class="container">
  <div class="stats">{stats_html}</div>
  <div class="filters">
    <input type="text" class="search-box" id="search" placeholder="Search jobs, companies, locations...">
    <button class="filter-btn active" data-filter="all">All ({total})</button>
    {"".join(f'<button class="filter-btn" data-filter="{v}">{v.title()} ({counts[v]})</button>' for v in ("strong", "moderate", "stretch", "weak") if v in counts)}
  </div>
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
