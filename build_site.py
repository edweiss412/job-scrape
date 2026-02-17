#!/usr/bin/env python3
"""
Build a static HTML site from markdown evaluation results.
Outputs to site/ for GitHub Pages deployment.

Usage:
    python build_site.py
"""

import re
from datetime import datetime
from pathlib import Path

import markdown

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
SITE_DIR = SCRIPT_DIR / "site"

PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ max-width: 800px; margin: 2rem auto; padding: 0 1rem; font-family: -apple-system, system-ui, sans-serif; line-height: 1.6; color: #222; }}
  h1 {{ font-size: 1.6rem; border-bottom: 2px solid #333; padding-bottom: .3rem; }}
  h2 {{ font-size: 1.3rem; margin-top: 2rem; }}
  h3 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
  a {{ color: #0366d6; }}
  code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 1.5rem 0; }}
  .nav {{ margin-bottom: 1.5rem; font-size: .9rem; }}
  .job-list {{ list-style: none; padding: 0; }}
  .job-list li {{ padding: .5rem 0; border-bottom: 1px solid #eee; }}
  .verdict {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: .8rem; font-weight: 600; }}
  .strong {{ background: #d4edda; color: #155724; }}
  .moderate {{ background: #fff3cd; color: #856404; }}
  .stretch {{ background: #e2e3e5; color: #383d41; }}
</style>
</head>
<body>
<div class="nav"><a href="/">&larr; All Runs</a> {extra_nav}</div>
{content}
</body>
</html>
"""

md = markdown.Markdown(extensions=["tables", "fenced_code"])


def render_page(title: str, content_html: str, extra_nav: str = "") -> str:
    return PAGE_TEMPLATE.format(title=title, content=content_html, extra_nav=extra_nav)


def convert_md_file(md_path: Path) -> str:
    md.reset()
    return md.convert(md_path.read_text())


def get_run_dates() -> list[str]:
    """Find all YYYY-MM-DD directories under results/."""
    dates = []
    for item in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if item.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", item.name):
            dates.append(item.name)
    return dates


def build_eval_page(md_path: Path, out_dir: Path, date_str: str, verdict: str) -> str:
    """Convert a single .md eval to .html. Returns the output filename."""
    html_name = md_path.stem + ".html"
    html_content = convert_md_file(md_path)
    nav = f'| <a href="/{date_str}/">{date_str}</a> | <a href="/{date_str}/{verdict}/">{verdict}</a>'
    page = render_page(md_path.stem.replace("_", " "), html_content, extra_nav=nav)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / html_name).write_text(page)
    return html_name


def build_date_index(date_str: str) -> None:
    """Build index pages for a single run date."""
    run_dir = RESULTS_DIR / date_str
    site_date_dir = SITE_DIR / date_str

    sections_html = f"<h1>Job Scan &mdash; {date_str}</h1>\n"

    for verdict in ("strong", "moderate", "stretch", "weak"):
        verdict_dir = run_dir / verdict
        if not verdict_dir.is_dir():
            continue

        md_files = sorted(verdict_dir.glob("*.md"))
        if not md_files:
            continue

        out_dir = site_date_dir / verdict
        out_dir.mkdir(parents=True, exist_ok=True)

        sections_html += f'<h2><span class="verdict {verdict}">{verdict.upper()}</span> ({len(md_files)})</h2>\n'
        sections_html += '<ul class="job-list">\n'

        for md_path in md_files:
            html_name = build_eval_page(md_path, out_dir, date_str, verdict)
            label = md_path.stem.replace("_", " ")
            sections_html += f'  <li><a href="/{date_str}/{verdict}/{html_name}">{label}</a></li>\n'

        sections_html += "</ul>\n"

        # Build deep eval pages if they exist
        deep_dir = verdict_dir / "deep"
        if deep_dir.is_dir():
            deep_out = out_dir / "deep"
            for md_path in sorted(deep_dir.glob("*.md")):
                build_eval_page(md_path, deep_out, date_str, f"{verdict}/deep")

        # Build per-verdict index for moderate (for "view all" link from email)
        if verdict == "moderate":
            verdict_index = render_page(
                f"All Moderate Matches — {date_str}",
                sections_html.split(f'<h2><span class="verdict {verdict}">')[-1],
                extra_nav=f'| <a href="/{date_str}/">{date_str}</a>',
            )
            (out_dir / "index.html").write_text(verdict_index)

    # Write date index
    page = render_page(f"Job Scan — {date_str}", sections_html)
    site_date_dir.mkdir(parents=True, exist_ok=True)
    (site_date_dir / "index.html").write_text(page)


def build_root_index(dates: list[str]) -> None:
    """Build the top-level index linking to each run."""
    items = ""
    for d in dates:
        items += f'  <li><a href="/{d}/">{d}</a></li>\n'

    html = f"<h1>Job Scan Results</h1>\n<ul>\n{items}</ul>\n"
    page = render_page("Job Scan Results", html)
    (SITE_DIR / "index.html").write_text(page)


def main():
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    dates = get_run_dates()
    if not dates:
        print("No results found in results/ directory.")
        return

    print(f"Building site for {len(dates)} run(s): {', '.join(dates)}")

    for date_str in dates:
        build_date_index(date_str)
        print(f"  Built {date_str}/")

    build_root_index(dates)
    print(f"Site generated at {SITE_DIR}/")


if __name__ == "__main__":
    main()
