#!/usr/bin/env python3
"""
Facebook Group Monitor for Freelance AV Gigs
=============================================
Hybrid monitor: public groups use BrightData Dataset API, private groups use
Playwright with a saved Facebook session. Groups are organized by priority tier
(high/medium/low) so high-priority groups can run more frequently.

Pipeline: Fetch → Filter → Score → Notify

Usage:
  python facebook_monitor.py                    # Full run: fetch + filter + score + digest
  python facebook_monitor.py --fetch-only       # Fetch and cache, no scoring
  python facebook_monitor.py --score-only       # Re-score last fetch
  python facebook_monitor.py --immediate        # Immediate alerts for HOT only
  python facebook_monitor.py --digest           # Daily digest email
  python facebook_monitor.py --no-email         # Score but skip email
  python facebook_monitor.py --dry-run          # Keyword matches only, no LLM
  python facebook_monitor.py --group GROUP_KEY  # Single group
  python facebook_monitor.py --days-back N      # Override lookback window
  python facebook_monitor.py --tier high        # Filter by priority tier
  python facebook_monitor.py --login            # Save Facebook session for private groups

Requirements:
  pip install requests pyyaml rich resend playwright
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import yaml
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
console = Console(force_terminal=False, no_color=True) if os.environ.get("CI") else Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("facebook_monitor.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("facebook_monitor")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
FB_MONITOR_DIR = SCRIPT_DIR / "fb_monitor"
FB_CACHE_PATH = SCRIPT_DIR / "fb_posts_cache.json"
FB_SESSION_PATH = Path(os.environ.get("FB_SESSION_PATH", str(SCRIPT_DIR / "fb_session.json")))

FB_MONITOR_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Shared utilities (copied from freelance_finder.py)
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found: {CONFIG_PATH}[/red]")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

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

    return config


def resolve_model(config: dict, role: str) -> tuple[str, str]:
    """Return (provider, model_id) for *role* from the centralized models section."""
    models = config.get("models", {})
    entry = models.get(role, {})
    if entry.get("model"):
        provider = entry.get("provider", config.get("llm_provider", "openrouter"))
        return provider, entry["model"]

    # Generic legacy fallback
    provider = config.get("llm_provider", "openrouter")
    legacy_map = {
        "openrouter": ("openrouter_model", "anthropic/claude-sonnet-4"),
        "anthropic": ("anthropic_model", "claude-sonnet-4-20250514"),
        "google_aistudio": ("google_aistudio_model", "gemini-3-flash-preview"),
        "openai_compatible": ("openai_compatible_model", "local-model"),
    }
    key, default = legacy_map.get(provider, ("openrouter_model", "anthropic/claude-sonnet-4"))
    return provider, config.get(key, default)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class FacebookPost:
    # BrightData fields
    post_id: str
    content: str
    date_posted: str = ""
    author_username: str = ""
    post_url: str = ""
    num_comments: int = 0
    num_shares: int = 0
    num_likes: int = 0
    hashtags: list[str] = field(default_factory=list)

    # Derived
    fb_post_hash: str = ""       # MD5 of post_id, for dedup
    group_name: str = ""
    group_url: str = ""
    matched_keywords: list[str] = field(default_factory=list)

    # LLM scoring
    relevance_tier: str = ""     # HOT / WARM / COLD
    relevance_score: int = 0     # 0-100
    relevance_reasoning: str = ""
    gig_summary: str = ""
    location_mentioned: str = ""
    date_mentioned: str = ""
    pay_mentioned: str = ""

    # Tracking
    alert_sent: bool = False
    first_seen_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    last_seen_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def __post_init__(self):
        if not self.fb_post_hash and self.post_id:
            self.fb_post_hash = hashlib.md5(self.post_id.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# BrightData Facebook Groups Dataset Scraper
# ---------------------------------------------------------------------------
class BrightDataFacebookScraper:
    """
    Async trigger/poll/download pattern for BrightData Facebook Groups Dataset.

    Dataset ID: gd_lz11l67o2cb3r0lkj3 (Facebook Groups Posts)
    Docs: https://docs.brightdata.com/scraping-automation/web-data-apis/web-scraper-api
    """

    BASE_URL = "https://api.brightdata.com/datasets/v3"
    DATASET_ID = "gd_lz11l67o2cb3r0lkj3"

    def __init__(self, api_token: str):
        self.api_token = api_token
        if not api_token:
            log.warning("BrightData API token not set")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def trigger_collection(
        self,
        group_urls: list[str],
        days_back: int = 1,
        num_posts: int = 50,
    ) -> str:
        """Trigger a new data collection for the given group URLs. Returns snapshot_id."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        # BrightData expects MM-DD-YYYY format for date params
        start_str = start_date.strftime("%m-%d-%Y")
        end_str = end_date.strftime("%m-%d-%Y")

        # Build input records — one per group URL
        inputs = [{"url": url, "start_date": start_str, "end_date": end_str, "num_of_posts": num_posts} for url in group_urls]

        url = f"{self.BASE_URL}/trigger?dataset_id={self.DATASET_ID}&include_errors=true"
        try:
            log.info(f"BrightData: triggering collection for {len(group_urls)} groups, {days_back}d lookback")
            resp = requests.post(url, headers=self._headers(), json=inputs, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            snapshot_id = data.get("snapshot_id", "")
            if not snapshot_id:
                log.error(f"BrightData: no snapshot_id in response: {data}")
                return ""
            log.info(f"BrightData: snapshot triggered → {snapshot_id}")
            from pipeline_utils import log_api_usage
            log_api_usage(
                source="external", category="dataset_api", pipeline="facebook_monitor", operation="brightdata_fb_trigger",
                provider="brightdata", success=True,
                http_status=resp.status_code,
                metadata={"groups": len(group_urls), "days_back": days_back},
            )
            return snapshot_id
        except Exception as e:
            log.error(f"BrightData trigger error: {e}")
            return ""

    def poll_status(self, snapshot_id: str) -> str:
        """Check snapshot status. Returns: 'running', 'ready', 'failed'."""
        url = f"{self.BASE_URL}/progress/{snapshot_id}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "unknown")
            return status
        except Exception as e:
            log.error(f"BrightData poll error: {e}")
            return "unknown"

    def wait_for_results(
        self,
        snapshot_id: str,
        poll_interval: int = 15,
        max_wait: int = 600,
    ) -> bool:
        """Poll until snapshot is ready. Returns True if data is available."""
        elapsed = 0
        while elapsed < max_wait:
            status = self.poll_status(snapshot_id)
            if status == "ready":
                log.info(f"BrightData: snapshot {snapshot_id} ready after {elapsed}s")
                return True
            if status == "failed":
                log.error(f"BrightData: snapshot {snapshot_id} failed")
                return False
            log.info(f"BrightData: snapshot {snapshot_id} status={status}, waiting ({elapsed}/{max_wait}s)...")
            time.sleep(poll_interval)
            elapsed += poll_interval

        log.error(f"BrightData: snapshot {snapshot_id} timed out after {max_wait}s")
        return False

    def download_results(self, snapshot_id: str) -> list[dict]:
        """Download snapshot results as JSON."""
        url = f"{self.BASE_URL}/snapshot/{snapshot_id}?format=json"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=120)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            log.error(f"BrightData download error: {e}")
            return []

    def fetch_groups(
        self,
        group_urls: list[str],
        days_back: int = 1,
        num_posts: int = 50,
    ) -> list[dict]:
        """Convenience: trigger → wait → download. Returns raw post dicts."""
        if not self.api_token:
            log.error("BrightData: API token required")
            return []

        snapshot_id = self.trigger_collection(group_urls, days_back, num_posts)
        if not snapshot_id:
            return []

        if not self.wait_for_results(snapshot_id):
            return []

        results = self.download_results(snapshot_id)
        log.info(f"BrightData: downloaded {len(results)} posts from {len(group_urls)} groups")
        return results


def _parse_brightdata_posts(
    raw_posts: list[dict],
    groups: list[dict],
) -> list[FacebookPost]:
    """Convert raw BrightData post dicts into FacebookPost objects."""
    # Build URL-to-name lookup from flat group list
    url_to_name = {}
    for grp in groups:
        url = grp.get("url", "").rstrip("/")
        name = grp.get("name", "")
        if url and name:
            url_to_name[url] = name
            # Also map without trailing slash variations
            if url.endswith("/"):
                url_to_name[url.rstrip("/")] = name

    posts = []
    for raw in raw_posts:
        if not isinstance(raw, dict):
            continue

        post_id = str(raw.get("post_id", raw.get("id", "")))
        if not post_id:
            continue

        content = str(raw.get("content", raw.get("text", raw.get("message", ""))))
        if not content:
            continue

        # Cap content at 5000 chars
        if len(content) > 5000:
            content = content[:5000]

        # Resolve group name from URL
        group_url = str(raw.get("group_url", raw.get("url", ""))).rstrip("/")
        group_name = url_to_name.get(group_url, "")
        if not group_name:
            # Try matching by group_id in the URL
            for cfg_url, cfg_name in url_to_name.items():
                if cfg_url.rstrip("/") in group_url or group_url in cfg_url.rstrip("/"):
                    group_name = cfg_name
                    break

        post = FacebookPost(
            post_id=post_id,
            content=content,
            date_posted=str(raw.get("date_posted", raw.get("date", raw.get("created_time", "")))),
            author_username=str(raw.get("author_name", raw.get("author_username", raw.get("user_name", "")))),
            post_url=str(raw.get("post_url", raw.get("url", ""))),
            num_comments=int(raw.get("num_comments", raw.get("comments_count", 0)) or 0),
            num_shares=int(raw.get("num_shares", raw.get("shares_count", 0)) or 0),
            num_likes=int(raw.get("num_likes", raw.get("likes_count", raw.get("reactions_count", 0))) or 0),
            hashtags=raw.get("hashtags", []) or [],
            group_name=group_name,
            group_url=group_url,
        )
        posts.append(post)

    return posts


# ---------------------------------------------------------------------------
# Playwright Facebook Scraper — private groups via saved session
# ---------------------------------------------------------------------------
class PlaywrightFacebookScraper:
    """
    Scrapes private Facebook groups using Playwright with a saved session.

    Requires fb_session.json (Playwright storage state) containing Facebook
    login cookies. Generate with: python facebook_monitor.py --login
    """

    def __init__(self, session_path: Path = FB_SESSION_PATH):
        self.session_path = session_path

    def _ensure_session(self) -> bool:
        """Check that a session file exists. Restore from env var if needed."""
        if self.session_path.exists():
            return True

        # Restore from base64-encoded env var (CI pattern)
        b64 = os.environ.get("FB_SESSION_B64", "")
        if b64:
            try:
                data = base64.b64decode(b64)
                self.session_path.write_bytes(data)
                log.info(f"Restored FB session from FB_SESSION_B64 → {self.session_path}")
                return True
            except Exception as e:
                log.error(f"Failed to decode FB_SESSION_B64: {e}")
                return False

        log.error(
            f"No Facebook session found at {self.session_path}. "
            "Run: python facebook_monitor.py --login"
        )
        return False

    def _extract_posts_from_page(self, page, group_url: str, group_name: str) -> list[FacebookPost]:
        """Extract posts from the currently loaded Facebook group page."""
        posts = []

        try:
            articles = page.query_selector_all('div[role="article"]')
        except Exception as e:
            log.warning(f"Failed to select articles from {group_name}: {e}")
            return posts

        for article in articles:
            post_data = {"group_url": group_url, "group_name": group_name}

            # Content text
            try:
                # The main post text is usually in a div with dir="auto"
                text_els = article.query_selector_all('div[dir="auto"]')
                texts = []
                for el in text_els:
                    t = el.inner_text().strip()
                    if t and len(t) > 10:
                        texts.append(t)
                post_data["content"] = "\n".join(texts) if texts else ""
            except Exception:
                post_data["content"] = ""

            if not post_data["content"]:
                continue

            # Cap content
            if len(post_data["content"]) > 5000:
                post_data["content"] = post_data["content"][:5000]

            # Author
            try:
                author_link = article.query_selector('a[role="link"] > strong')
                if author_link:
                    post_data["author"] = author_link.inner_text().strip()
                else:
                    # Fallback: first strong tag
                    strong = article.query_selector("strong")
                    post_data["author"] = strong.inner_text().strip() if strong else ""
            except Exception:
                post_data["author"] = ""

            # Timestamp and post URL
            try:
                # Timestamps are typically in <a> tags with aria-label containing date info
                time_links = article.query_selector_all('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]')
                if time_links:
                    post_data["post_url"] = time_links[0].get_attribute("href") or ""
                    aria = time_links[0].get_attribute("aria-label") or ""
                    post_data["timestamp"] = aria
                else:
                    # Fallback: look for abbr or span with timestamp
                    abbr = article.query_selector("abbr")
                    if abbr:
                        post_data["timestamp"] = abbr.get_attribute("title") or abbr.inner_text().strip()
                    else:
                        post_data["timestamp"] = ""
                    post_data["post_url"] = ""
            except Exception:
                post_data["timestamp"] = ""
                post_data["post_url"] = ""

            # Make post URL absolute
            if post_data.get("post_url") and post_data["post_url"].startswith("/"):
                post_data["post_url"] = f"https://www.facebook.com{post_data['post_url']}"

            # Engagement counts
            try:
                article_text = article.inner_text()
                comment_match = re.search(r'(\d+)\s+comment', article_text, re.IGNORECASE)
                share_match = re.search(r'(\d+)\s+share', article_text, re.IGNORECASE)
                like_match = re.search(r'(\d+)\s+(?:like|reaction)', article_text, re.IGNORECASE)
                post_data["num_comments"] = int(comment_match.group(1)) if comment_match else 0
                post_data["num_shares"] = int(share_match.group(1)) if share_match else 0
                post_data["num_likes"] = int(like_match.group(1)) if like_match else 0
            except Exception:
                post_data["num_comments"] = 0
                post_data["num_shares"] = 0
                post_data["num_likes"] = 0

            # Generate post_id from content hash if no FB ID in URL
            post_id = ""
            if post_data.get("post_url"):
                id_match = re.search(r'(?:posts/|permalink/|story_fbid=)(\d+)', post_data["post_url"])
                if id_match:
                    post_id = id_match.group(1)
            if not post_id:
                post_id = f"pw_{hashlib.md5(post_data['content'][:200].encode()).hexdigest()[:16]}"

            post = FacebookPost(
                post_id=post_id,
                content=post_data["content"],
                date_posted=post_data.get("timestamp", ""),
                author_username=post_data.get("author", ""),
                post_url=post_data.get("post_url", ""),
                num_comments=post_data.get("num_comments", 0),
                num_shares=post_data.get("num_shares", 0),
                num_likes=post_data.get("num_likes", 0),
                group_name=group_name,
                group_url=group_url,
            )
            posts.append(post)

        return posts

    def fetch_groups(
        self,
        groups: list[dict],
        max_scrolls: int = 15,
    ) -> list[FacebookPost]:
        """
        Fetch posts from private groups using Playwright.

        Args:
            groups: List of dicts with 'url' and 'name' keys.
            max_scrolls: Number of scroll iterations per group.

        Returns:
            List of FacebookPost objects.
        """
        if not self._ensure_session():
            return []

        if not groups:
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        all_posts = []
        log.info(f"Playwright: fetching {len(groups)} private groups (max_scrolls={max_scrolls})")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(self.session_path))
            page = context.new_page()

            for grp in groups:
                url = grp["url"]
                name = grp.get("name", url)
                log.info(f"Playwright: navigating to {name}")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)

                    # Check if redirected to login (session expired)
                    if "login" in page.url.lower():
                        log.error(
                            f"Playwright: redirected to login for {name} — session expired. "
                            "Run: python facebook_monitor.py --login"
                        )
                        continue

                    # Wait for feed to load
                    try:
                        page.wait_for_selector('div[role="main"]', timeout=15000)
                    except Exception:
                        log.warning(f"Playwright: feed container not found for {name}, trying anyway")

                    # Click "See more" buttons to expand truncated posts
                    try:
                        see_more_buttons = page.query_selector_all('div[role="button"]')
                        for btn in see_more_buttons:
                            try:
                                btn_text = btn.inner_text().strip().lower()
                                if btn_text in ("see more", "see more…"):
                                    btn.click()
                                    time.sleep(0.3)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Scroll to load more posts
                    for i in range(max_scrolls):
                        page.evaluate("window.scrollBy(0, 1500)")
                        delay = random.uniform(2.0, 3.5)
                        time.sleep(delay)

                        # Click any new "See more" buttons that appeared
                        try:
                            see_more_buttons = page.query_selector_all('div[role="button"]')
                            for btn in see_more_buttons:
                                try:
                                    btn_text = btn.inner_text().strip().lower()
                                    if btn_text in ("see more", "see more…"):
                                        btn.click()
                                        time.sleep(0.2)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    # Extract posts
                    posts = self._extract_posts_from_page(page, url, name)
                    log.info(f"Playwright: extracted {len(posts)} posts from {name}")
                    all_posts.extend(posts)

                except Exception as e:
                    log.error(f"Playwright: error fetching {name}: {e}")
                    continue

            browser.close()

        log.info(f"Playwright: total {len(all_posts)} posts from {len(groups)} private groups")
        return all_posts


def save_login_session():
    """Interactive: open a browser for manual Facebook login, then save the session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("[red]Playwright not installed. Run: pip install playwright && playwright install chromium[/red]")
        sys.exit(1)

    console.print("\n[bold]Facebook Session Saver[/bold]")
    console.print("A browser window will open. Log in to Facebook (handle 2FA if prompted).")
    console.print("When you're fully logged in and see your feed, close the browser window.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.facebook.com/")

        # Wait for user to close the browser
        try:
            page.wait_for_event("close", timeout=300_000)  # 5 min
        except Exception:
            pass

        # Save storage state
        context.storage_state(path=str(FB_SESSION_PATH))
        browser.close()

    console.print(f"\n[bold green]Session saved to {FB_SESSION_PATH}[/bold green]")
    console.print("\nFor CI setup, base64-encode the file and add as a GitHub secret:")
    console.print(f"  base64 -i {FB_SESSION_PATH} | pbcopy  # macOS")
    console.print(f"  base64 -w 0 {FB_SESSION_PATH}         # Linux")
    console.print("  → Add as GitHub secret: FB_SESSION_B64")


# ---------------------------------------------------------------------------
# Keyword Matcher — fast pre-filter
# ---------------------------------------------------------------------------
class KeywordMatcher:
    """Fast keyword-based pre-filter for Facebook posts."""

    # Primary AV gig keywords (case-insensitive)
    DEFAULT_KEYWORDS = [
        # Roles
        "a1", "a2", "v1", "v2",
        "audio engineer", "sound engineer", "mix engineer",
        "av tech", "av technician", "a/v tech", "a/v technician",
        "audio tech", "audio technician",
        "video tech", "video technician", "video engineer",
        "freelance audio", "freelance av", "freelance a/v",
        "freelance sound", "freelance video",
        "monitor engineer", "foh engineer", "foh mix",
        "rf tech", "rf technician", "rf coordinator",
        "broadcast engineer", "broadcast tech",
        "stagehand", "stage hand",
        "led tech", "led technician",
        "lighting tech", "lighting technician",
        # Calls / gig language
        "day call", "crew call", "show call",
        "live sound", "live event", "live production",
        "corporate event", "corporate av", "corporate show",
        "need a tech", "need an a1", "need an a2",
        "looking for a tech", "looking for an a1", "looking for an a2",
        "looking for audio", "looking for av",
        "hiring freelance", "hiring a1", "hiring a2",
        "need crew", "crew needed", "techs needed", "tech needed",
        "gig available", "gig alert",
        "day rate", "rates available",
        # Gear / systems
        "digico", "yamaha cl", "yamaha pm", "yamaha rivage",
        "allen & heath", "allen and heath", "dlive", "avantis",
        "midas", "soundcraft",
        "l-acoustics", "d&b audiotechnik", "d&b", "meyer sound",
        "jbl vrx", "jbl vtx", "qsc",
        "shure axient", "shure uhf-r", "shure psm",
        "sennheiser", "wisycom", "lectrosonics",
        "dante", "dante network", "avb",
        "blackmagic", "ross carbonite", "tricaster",
        "disguise", "resolume", "watchout",
    ]

    # Negative keywords — posts matching these are likely NOT gig postings
    DEFAULT_NEGATIVES = [
        "for sale", "selling", "wts", "want to sell",
        "looking for work", "available for work", "seeking employment",
        "meme", "joke", "lol", "lmao",
        "buy my", "check out my",
        "podcast", "subscribe to",
        "rip ", "passed away", "obituary",
    ]

    def __init__(
        self,
        extra_keywords: list[str] | None = None,
        extra_negatives: list[str] | None = None,
    ):
        self.keywords = [k.lower() for k in self.DEFAULT_KEYWORDS]
        if extra_keywords:
            self.keywords.extend(k.lower() for k in extra_keywords)

        self.negatives = [n.lower() for n in self.DEFAULT_NEGATIVES]
        if extra_negatives:
            self.negatives.extend(n.lower() for n in extra_negatives)

    def match(self, post: FacebookPost) -> list[str]:
        """Return list of matched keywords, or empty list if no match or negative hit."""
        text = post.content.lower()

        # Check negatives first
        for neg in self.negatives:
            if neg in text:
                return []

        matched = []
        for kw in self.keywords:
            if kw in text:
                matched.append(kw)

        return matched


# ---------------------------------------------------------------------------
# LLM Post Scorer
# ---------------------------------------------------------------------------
class PostScorer:
    """LLM-based relevance scoring for Facebook posts."""

    def __init__(self, config: dict):
        self.client = None
        self.provider, self.model = resolve_model(config, "fb_monitor")

        if self.provider == "openrouter":
            api_key = config.get("openrouter_key", "")
            if not api_key:
                log.warning("OpenRouter key not set")
                return
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
            except ImportError:
                log.error("Install openai: pip install openai")

        elif self.provider == "anthropic":
            api_key = config.get("anthropic_key", "")
            if not api_key:
                log.warning("Anthropic key not set")
                return
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                log.error("Install anthropic: pip install anthropic")

        elif self.provider == "google_aistudio":
            api_key = config.get("google_aistudio_key", "")
            if not api_key:
                log.warning("Google AI Studio key not set")
                return
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except ImportError:
                log.error("Install google-genai: pip install google-genai")

        elif self.provider == "openai_compatible":
            base_url = config.get("openai_compatible_base_url", "http://localhost:1234/v1")
            api_key = config.get("openai_compatible_key", "not-needed")
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=base_url, api_key=api_key)
            except ImportError:
                log.error("Install openai: pip install openai")

        else:
            log.error(f"Unknown LLM provider: {self.provider}")

    def _call_llm(self, prompt: str) -> str:
        import time as _time
        from pipeline_utils import log_api_usage
        if not self.client:
            return ""
        _start = _time.time()
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            _latency = int((_time.time() - _start) * 1000)
            _pt = getattr(response.usage, "input_tokens", 0)
            _ct = getattr(response.usage, "output_tokens", 0)
            log_api_usage(
                source="pipeline", category="llm", pipeline="facebook_monitor", operation="fb_monitor_score",
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                latency_ms=_latency, success=True,
            )
            return response.content[0].text.strip()
        elif self.provider == "google_aistudio":
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"max_output_tokens": 1000, "temperature": 0.3},
            )
            _latency = int((_time.time() - _start) * 1000)
            um = getattr(response, "usage_metadata", None)
            _pt = getattr(um, "prompt_token_count", 0) if um else 0
            _ct = getattr(um, "candidates_token_count", 0) if um else 0
            log_api_usage(
                source="pipeline", category="llm", pipeline="facebook_monitor", operation="fb_monitor_score",
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                latency_ms=_latency, success=True,
            )
            return response.text.strip()
        else:
            extra_headers = {}
            if self.provider == "openrouter":
                extra_headers = {
                    "HTTP-Referer": "https://github.com/job-scraper",
                    "X-Title": "Facebook Monitor",
                }
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
                extra_headers=extra_headers,
            )
            _latency = int((_time.time() - _start) * 1000)
            _pt = response.usage.prompt_tokens or 0 if response.usage else 0
            _ct = response.usage.completion_tokens or 0 if response.usage else 0
            _cost = getattr(response.usage, "cost", None) if response.usage else None
            log_api_usage(
                source="pipeline", category="llm", pipeline="facebook_monitor", operation="fb_monitor_score",
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                cost_usd=_cost, latency_ms=_latency, success=True,
            )
            return response.choices[0].message.content.strip()

    def score_post(self, post: FacebookPost) -> dict:
        """Score a single post for relevance as a freelance AV gig."""
        prompt = f"""You are analyzing a Facebook group post to determine if it's someone hiring a freelance AV/audio technician or engineer for a gig.

POST CONTENT:
{post.content}

POST METADATA:
- Group: {post.group_name}
- Author: {post.author_username}
- Date: {post.date_posted}
- Engagement: {post.num_likes} likes, {post.num_comments} comments, {post.num_shares} shares
- Matched keywords: {', '.join(post.matched_keywords)}

TASK:
Determine if this post is someone actively hiring/looking for a freelance AV/audio tech. Consider:
1. Is this someone HIRING (not someone looking for work)?
2. Are there actionable details (dates, location, role type)?
3. What specific role, location, dates, and pay are mentioned?

RESPOND WITH EXACTLY THESE FIELDS (one per line):

RELEVANCE_TIER: [HOT|WARM|COLD]
RELEVANCE_SCORE: [0-100]
GIG_SUMMARY: [1-2 sentence summary of the gig opportunity, or "Not a gig posting" if COLD]
LOCATION: [city/state if mentioned, or "Not specified"]
DATE: [event dates if mentioned, or "Not specified"]
PAY: [pay/rate if mentioned, or "Not specified"]
REASONING: [1-2 sentences explaining your classification]

HOT = Real gig posting with actionable details (dates, location, role). Someone is clearly hiring.
WARM = Likely a gig but missing key details, or somewhat ambiguous. Worth monitoring.
COLD = Not a gig posting (selling gear, looking for work, meme, discussion, etc.)"""

        try:
            response = self._call_llm(prompt)
        except Exception as e:
            log.error(f"LLM error scoring post {post.fb_post_hash}: {e}")
            return {}

        result = {}

        tier_match = re.search(r'RELEVANCE_TIER:\s*(HOT|WARM|COLD)', response, re.IGNORECASE)
        if tier_match:
            result["relevance_tier"] = tier_match.group(1).upper()

        score_match = re.search(r'RELEVANCE_SCORE:\s*(\d+)', response)
        if score_match:
            result["relevance_score"] = int(score_match.group(1))

        summary_match = re.search(r'GIG_SUMMARY:\s*(.+?)(?:\n|$)', response)
        if summary_match:
            result["gig_summary"] = summary_match.group(1).strip()

        loc_match = re.search(r'LOCATION:\s*(.+?)(?:\n|$)', response)
        if loc_match:
            result["location_mentioned"] = loc_match.group(1).strip()

        date_match = re.search(r'DATE:\s*(.+?)(?:\n|$)', response)
        if date_match:
            result["date_mentioned"] = date_match.group(1).strip()

        pay_match = re.search(r'PAY:\s*(.+?)(?:\n|$)', response)
        if pay_match:
            result["pay_mentioned"] = pay_match.group(1).strip()

        reasoning_match = re.search(r'REASONING:\s*(.+?)(?:\n|$)', response)
        if reasoning_match:
            result["relevance_reasoning"] = reasoning_match.group(1).strip()

        return result

    def score_batch(
        self,
        posts: list[FacebookPost],
        max_workers: int = 6,
    ) -> list[FacebookPost]:
        """Score multiple posts concurrently."""
        if not self.client:
            console.print("[red]No LLM client configured — skipping scoring[/red]")
            return posts

        console.print(f"\n[bold]Scoring {len(posts)} posts...[/bold]")
        console.print(f"[dim]Provider: {self.provider} | Model: {self.model}[/dim]")

        tier_style = {"HOT": "red bold", "WARM": "yellow", "COLD": "dim"}
        completed = 0

        def _score_one(post: FacebookPost) -> FacebookPost:
            result = self.score_post(post)
            post.relevance_tier = result.get("relevance_tier", "")
            post.relevance_score = result.get("relevance_score", 0)
            post.relevance_reasoning = result.get("relevance_reasoning", "")
            post.gig_summary = result.get("gig_summary", "")
            post.location_mentioned = result.get("location_mentioned", "")
            post.date_mentioned = result.get("date_mentioned", "")
            post.pay_mentioned = result.get("pay_mentioned", "")
            return post

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_post = {executor.submit(_score_one, p): p for p in posts}
            for future in as_completed(future_to_post):
                completed += 1
                try:
                    post = future.result()
                    style = tier_style.get(post.relevance_tier, "white")
                    preview = post.content[:60].replace("\n", " ")
                    console.print(
                        f"  [{completed}/{len(posts)}] [{style}]{post.relevance_tier} ({post.relevance_score})[/{style}] "
                        f"{preview}..."
                    )
                except Exception as e:
                    p = future_to_post[future]
                    log.error(f"Scoring failed for post {p.fb_post_hash}: {e}")

        return posts


# ---------------------------------------------------------------------------
# Cache / dedup
# ---------------------------------------------------------------------------
def load_cache() -> dict:
    if FB_CACHE_PATH.exists():
        try:
            with open(FB_CACHE_PATH) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Failed to load FB cache: {e}")
    return {}


def save_cache(cache: dict):
    with open(FB_CACHE_PATH, "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    log.info(f"FB cache saved: {len(cache)} entries")


def deduplicate_posts(
    posts: list[FacebookPost],
    cache: dict,
) -> tuple[list[FacebookPost], int]:
    """Remove posts already seen in cache. Returns (new_posts, skipped_count)."""
    seen = set()
    new_posts = []
    skipped = 0

    for post in posts:
        if post.fb_post_hash in cache:
            skipped += 1
            continue
        if post.fb_post_hash in seen:
            continue
        seen.add(post.fb_post_hash)
        new_posts.append(post)

    return new_posts, skipped


# ---------------------------------------------------------------------------
# Email notifications
# ---------------------------------------------------------------------------
def _build_post_row(post: FacebookPost, accent: str) -> str:
    """Build one post entry for the email (dark theme)."""
    group_html = f'<span style="color:#737373;">{post.group_name}</span>' if post.group_name else ""
    link_html = f'<a href="{post.post_url}" style="color:{accent};font-size:13px;font-weight:500;text-decoration:none;">View Post &rarr;</a>' if post.post_url else ""

    details_parts = []
    if post.location_mentioned and post.location_mentioned.lower() != "not specified":
        details_parts.append(f"Location: {post.location_mentioned}")
    if post.date_mentioned and post.date_mentioned.lower() != "not specified":
        details_parts.append(f"Date: {post.date_mentioned}")
    if post.pay_mentioned and post.pay_mentioned.lower() != "not specified":
        details_parts.append(f"Pay: {post.pay_mentioned}")
    details_html = f'<div style="font-size:12px;color:{accent};margin-bottom:6px;font-family:\'JetBrains Mono\',monospace;">{" &middot; ".join(details_parts)}</div>' if details_parts else ""

    summary = post.gig_summary or post.content[:200]

    return f"""
    <tr><td style="padding:16px 20px;border-bottom:1px solid rgba(255,255,255,.06);">
      <div style="margin-bottom:4px;">
        <span style="font-family:'Syne',sans-serif;font-weight:700;font-size:15px;color:#FDFDFD;">
          {summary[:120]}
        </span>
      </div>
      <div style="margin-bottom:6px;font-size:13px;color:#737373;font-family:'DM Sans',sans-serif;">
        {post.author_username} &middot; {group_html} &middot; {post.date_posted}
      </div>
      {details_html}
      <div style="font-size:13px;color:#ADADAD;line-height:1.6;margin-bottom:8px;font-family:'DM Sans',sans-serif;">
        {post.content[:300]}{'...' if len(post.content) > 300 else ''}
      </div>
      {link_html}
    </td></tr>"""


def _build_fb_email_html(
    date_str: str,
    hot_posts: list[FacebookPost],
    warm_posts: list[FacebookPost],
) -> str:
    """Build a dark-themed HTML email for FB monitor results."""
    hot_count = len(hot_posts)
    warm_count = len(warm_posts)

    html = f"""
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<div style="font-family:'DM Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;background:#000000;border-radius:12px;overflow:hidden;">

  <!-- Header -->
  <div style="padding:28px 24px 20px;border-bottom:1px solid rgba(255,255,255,.06);">
    <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#FDFDFD;margin-bottom:4px;">FB Group Monitor</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#535353;letter-spacing:.04em;margin-bottom:14px;">{date_str}</div>
    <div>
      <span style="display:inline-block;background:rgba(239,68,68,.1);color:#ef4444;padding:4px 12px;border-radius:20px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;border:1px solid rgba(239,68,68,.2);margin-right:6px;">{hot_count} Hot</span>
      <span style="display:inline-block;background:rgba(245,158,11,.1);color:#f59e0b;padding:4px 12px;border-radius:20px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;border:1px solid rgba(245,158,11,.2);">{warm_count} Warm</span>
    </div>
  </div>
"""

    if hot_posts:
        html += """
  <div style="padding:14px 20px;border-left:2px solid #ef4444;border-bottom:1px solid rgba(255,255,255,.06);">
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;color:#ef4444;text-transform:uppercase;letter-spacing:.08em;">
      Hot Gigs
    </div>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#000000;">
"""
        for post in hot_posts:
            html += _build_post_row(post, "#ef4444")
        html += "  </table>\n"

    if warm_posts:
        shown = warm_posts[:10]
        html += f"""
  <div style="padding:14px 20px;border-left:2px solid #f59e0b;border-bottom:1px solid rgba(255,255,255,.06);">
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;color:#f59e0b;text-transform:uppercase;letter-spacing:.08em;">
      Warm Leads{f' ({len(shown)} of {warm_count})' if warm_count > 10 else ''}
    </div>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#000000;">
"""
        for post in shown:
            html += _build_post_row(post, "#f59e0b")
        html += "  </table>\n"

    html += f"""
  <div style="padding:22px 20px;border-top:1px solid rgba(255,255,255,.06);text-align:center;">
    <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#535353;">Facebook Group Monitor &middot; Sent via Resend</div>
  </div>

</div>"""

    return html


def send_immediate_alert(post: FacebookPost):
    """Send a single HOT post alert email (for future frequent runs)."""
    import resend

    api_key = os.environ.get("RESEND_API_KEY")
    notify_email = os.environ.get("NOTIFY_EMAIL")
    email_from = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    if not api_key or not notify_email:
        log.warning("RESEND_API_KEY or NOTIFY_EMAIL not set — skipping immediate alert")
        return

    resend.api_key = api_key

    subject = f"HOT Gig Alert: {post.gig_summary[:60] if post.gig_summary else post.content[:60]}"
    html = _build_fb_email_html(
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        [post], [],
    )

    try:
        result = resend.Emails.send({
            "from": email_from,
            "to": [notify_email],
            "subject": subject,
            "html": html,
        })
        log.info(f"Immediate alert sent: {result}")
        post.alert_sent = True
    except Exception as e:
        log.error(f"Failed to send immediate alert: {e}")


def send_digest_email(posts: list[FacebookPost]):
    """Send a daily HOT + WARM digest email."""
    import resend

    api_key = os.environ.get("RESEND_API_KEY")
    notify_email = os.environ.get("NOTIFY_EMAIL")
    email_from = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    if not api_key or not notify_email:
        log.warning("RESEND_API_KEY or NOTIFY_EMAIL not set — skipping digest")
        return

    resend.api_key = api_key

    hot = [p for p in posts if p.relevance_tier == "HOT"]
    warm = [p for p in posts if p.relevance_tier == "WARM"]

    if not hot and not warm:
        log.info("No HOT or WARM posts — skipping digest email")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    subject = f"FB Gig Monitor — {date_str}: {len(hot)} HOT, {len(warm)} WARM"
    html = _build_fb_email_html(date_str, hot, warm)

    try:
        result = resend.Emails.send({
            "from": email_from,
            "to": [notify_email],
            "subject": subject,
            "html": html,
        })
        log.info(f"Digest email sent: {result}")
        for p in hot + warm:
            p.alert_sent = True
    except Exception as e:
        log.error(f"Failed to send digest email: {e}")


# ---------------------------------------------------------------------------
# Supabase sync
# ---------------------------------------------------------------------------
def _supabase_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def sync_fb_posts_to_supabase(config: dict, posts: list[FacebookPost]):
    """Upsert scored FB posts into the Supabase facebook_posts table."""
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        log.info("Supabase: not configured — skipping FB posts sync")
        return

    headers = _supabase_headers(supabase_key)

    # Only sync scored posts
    to_sync = [p for p in posts if p.relevance_tier]
    if not to_sync:
        log.info("Supabase: no scored FB posts to sync")
        return

    try:
        BATCH = 100
        for i in range(0, len(to_sync), BATCH):
            batch = to_sync[i:i + BATCH]
            records = [{
                "fb_post_hash": p.fb_post_hash,
                "post_id": p.post_id,
                "group_name": p.group_name or None,
                "group_url": p.group_url or None,
                "content": p.content[:5000] if p.content else None,
                "date_posted": p.date_posted or None,
                "author_username": p.author_username or None,
                "post_url": p.post_url or None,
                "matched_keywords": p.matched_keywords or [],
                "relevance_tier": p.relevance_tier,
                "relevance_score": p.relevance_score,
                "relevance_reasoning": p.relevance_reasoning or None,
                "gig_summary": p.gig_summary or None,
                "location_mentioned": p.location_mentioned or None,
                "date_mentioned": p.date_mentioned or None,
                "pay_mentioned": p.pay_mentioned or None,
                "alert_sent": p.alert_sent,
                "first_seen_date": p.first_seen_date,
                "last_seen_date": p.last_seen_date,
            } for p in batch]
            resp = requests.post(
                f"{supabase_url}/rest/v1/facebook_posts?on_conflict=fb_post_hash",
                headers={**headers, "Prefer": "resolution=merge-duplicates"},
                json=records, timeout=60,
            )
            resp.raise_for_status()

        log.info(f"Supabase: upserted {len(to_sync)} FB posts")

    except Exception as e:
        log.error(f"Supabase FB posts sync failed: {e}")


# ---------------------------------------------------------------------------
# Result saving
# ---------------------------------------------------------------------------
def save_fb_results(posts: list[FacebookPost]) -> tuple[Path, Path]:
    """Save results to JSON snapshot and per-tier markdown files."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    run_dir = FB_MONITOR_DIR / date_str
    run_dir.mkdir(parents=True, exist_ok=True)

    # Raw JSON snapshot
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = run_dir / f"fb_posts_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump([asdict(p) for p in posts], f, indent=2, default=str)
    log.info(f"Saved {len(posts)} posts to {json_path}")

    # Per-tier markdown
    scored = [p for p in posts if p.relevance_tier]
    for tier in ["HOT", "WARM"]:
        tier_posts = [p for p in scored if p.relevance_tier == tier]
        if not tier_posts:
            continue

        tier_dir = run_dir / tier.lower()
        tier_dir.mkdir(exist_ok=True)

        for p in tier_posts:
            safe_name = re.sub(r'[^\w\-]', '_', f"{p.group_name}_{p.fb_post_hash}")[:80]
            md_path = tier_dir / f"{safe_name}.md"
            with open(md_path, "w") as f:
                f.write(f"# {p.gig_summary or 'FB Post'}\n\n")
                f.write(f"**Group:** {p.group_name} | **Author:** {p.author_username}\n")
                f.write(f"**Date:** {p.date_posted} | **Post:** {p.post_url}\n")
                if p.location_mentioned and p.location_mentioned.lower() != "not specified":
                    f.write(f"**Location:** {p.location_mentioned}\n")
                if p.date_mentioned and p.date_mentioned.lower() != "not specified":
                    f.write(f"**Event Date:** {p.date_mentioned}\n")
                if p.pay_mentioned and p.pay_mentioned.lower() != "not specified":
                    f.write(f"**Pay:** {p.pay_mentioned}\n")
                f.write(f"\n**Relevance:** {p.relevance_tier} ({p.relevance_score}/100)\n")
                f.write(f"\n---\n\n## Post Content\n\n{p.content}\n")
                if p.relevance_reasoning:
                    f.write(f"\n---\n\n## Analysis\n\n{p.relevance_reasoning}\n")
                if p.matched_keywords:
                    f.write(f"\n**Keywords:** {', '.join(p.matched_keywords)}\n")

        log.info(f"Saved {len(tier_posts)} {tier} post files to {tier_dir}/")

    # Summary markdown
    md_path = run_dir / "summary.md"
    hot = [p for p in scored if p.relevance_tier == "HOT"]
    warm = [p for p in scored if p.relevance_tier == "WARM"]
    cold = [p for p in scored if p.relevance_tier == "COLD"]

    lines = [
        f"# FB Group Monitor — {date_str}",
        f"\n**Total posts:** {len(posts)} | **HOT:** {len(hot)} | **WARM:** {len(warm)} | **COLD:** {len(cold)}",
        "",
    ]

    if hot:
        lines.append(f"## HOT GIGS ({len(hot)})\n")
        for p in hot:
            lines.append(f"### {p.gig_summary or p.content[:80]}")
            lines.append(f"**Group:** {p.group_name} | **Score:** {p.relevance_score}/100")
            if p.location_mentioned and p.location_mentioned.lower() != "not specified":
                lines.append(f"**Location:** {p.location_mentioned}")
            if p.pay_mentioned and p.pay_mentioned.lower() != "not specified":
                lines.append(f"**Pay:** {p.pay_mentioned}")
            lines.append(f"**Post:** {p.post_url}")
            lines.append(f"\n> {p.content[:200]}")
            lines.append("---")

    if warm:
        lines.append(f"\n## WARM LEADS ({len(warm)})\n")
        for p in warm:
            lines.append(f"### {p.gig_summary or p.content[:80]}")
            lines.append(f"**Group:** {p.group_name} | **Score:** {p.relevance_score}/100")
            lines.append(f"**Post:** {p.post_url}")
            lines.append("---")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    log.info(f"Saved summary report to {md_path}")

    return json_path, md_path


def load_previous_posts() -> list[FacebookPost]:
    """Load the most recent FB posts JSON snapshot."""
    date_dirs = sorted(FB_MONITOR_DIR.glob("????-??-??"), reverse=True)
    for date_dir in date_dirs:
        json_files = sorted(date_dir.glob("fb_posts_*.json"), reverse=True)
        if json_files:
            with open(json_files[0]) as f:
                data = json.load(f)
            return [FacebookPost(**d) for d in data]
    return []


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------
def print_fb_summary(posts: list[FacebookPost]):
    """Print a summary table of scored posts."""
    scored = [p for p in posts if p.relevance_tier]
    sorted_posts = sorted(scored, key=lambda p: p.relevance_score, reverse=True)

    table = Table(title="Facebook Group Posts", show_lines=True)
    table.add_column("Tier", style="bold", width=6)
    table.add_column("Score", width=6)
    table.add_column("Summary", width=40)
    table.add_column("Group", width=20)
    table.add_column("Location", width=16)

    tier_style = {"HOT": "red bold", "WARM": "yellow", "COLD": "dim"}
    for p in sorted_posts[:30]:
        style = tier_style.get(p.relevance_tier, "white")
        summary = (p.gig_summary or p.content[:40]).replace("\n", " ")[:40]
        loc = p.location_mentioned if p.location_mentioned and p.location_mentioned.lower() != "not specified" else ""
        table.add_row(
            f"[{style}]{p.relevance_tier or '---'}[/{style}]",
            str(p.relevance_score) if p.relevance_score else "---",
            summary,
            (p.group_name or "")[:20],
            loc[:16],
        )

    console.print(table)

    hot = sum(1 for p in posts if p.relevance_tier == "HOT")
    warm = sum(1 for p in posts if p.relevance_tier == "WARM")
    cold = sum(1 for p in posts if p.relevance_tier == "COLD")
    console.print(f"\n  HOT:   {hot}")
    console.print(f"  WARM:  {warm}")
    console.print(f"  COLD:  {cold}")
    console.print(f"  Total: {len(posts)}")


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
def _resolve_groups(
    config: dict,
    tier_filter: Optional[str] = None,
    group_filter: Optional[str] = None,
) -> list[dict]:
    """
    Flatten tiered group config into a single list of group dicts.

    Supports both new tiered format and legacy flat format for backward compat.
    Each returned dict has at minimum: name, url, access, tier.
    """
    fb_cfg = config.get("facebook_monitor", {})
    groups_cfg = fb_cfg.get("groups", {})
    if not groups_cfg:
        return []

    all_groups: list[dict] = []

    # Detect format: new tiered (keys are high/medium/low with list values)
    # vs legacy flat (keys are group_key with dict values containing url/name)
    tier_keys = {"high", "medium", "low"}
    if any(k in groups_cfg for k in tier_keys):
        # New tiered format
        for tier in ("high", "medium", "low"):
            tier_groups = groups_cfg.get(tier, [])
            if isinstance(tier_groups, list):
                for grp in tier_groups:
                    if isinstance(grp, dict) and grp.get("url"):
                        grp.setdefault("access", "public")
                        grp["tier"] = tier
                        all_groups.append(grp)
    else:
        # Legacy flat format — treat all as public, high tier
        for key, grp in groups_cfg.items():
            if isinstance(grp, dict) and grp.get("url"):
                grp.setdefault("name", key)
                grp.setdefault("access", "public")
                grp["tier"] = "high"
                all_groups.append(grp)

    # Apply tier filter
    if tier_filter and tier_filter != "all":
        all_groups = [g for g in all_groups if g.get("tier") == tier_filter]

    # Apply single-group filter (match by name, case-insensitive)
    if group_filter:
        matched = [g for g in all_groups if group_filter.lower() in g.get("name", "").lower()]
        if not matched:
            console.print(f"[red]Group '{group_filter}' not found in config[/red]")
            return []
        all_groups = matched

    return all_groups


def run_fetch(
    config: dict,
    group_filter: Optional[str] = None,
    days_back: Optional[int] = None,
    tier_filter: Optional[str] = None,
) -> list[FacebookPost]:
    """Fetch posts from Facebook groups — hybrid: BrightData (public) + Playwright (private)."""
    fb_cfg = config.get("facebook_monitor", {})

    groups = _resolve_groups(config, tier_filter=tier_filter, group_filter=group_filter)
    if not groups:
        console.print("[yellow]No Facebook groups matched filters. Check config.yaml[/yellow]")
        return []

    actual_days_back = days_back or fb_cfg.get("days_back", 1)
    num_posts = fb_cfg.get("num_posts_per_group", 50)
    max_scrolls = fb_cfg.get("max_scrolls", 15)

    # Split into public and private
    public_groups = [g for g in groups if g.get("access") == "public"]
    private_groups = [g for g in groups if g.get("access") == "private"]

    all_posts: list[FacebookPost] = []

    # --- Public groups via BrightData ---
    if public_groups:
        api_token = config.get("brightdata_api_token", "")
        if not api_token:
            console.print("[yellow]BRIGHTDATA_API_TOKEN not set — skipping public groups[/yellow]")
        else:
            public_urls = [g["url"] for g in public_groups]
            console.print(f"[bold]Fetching {len(public_groups)} public groups via BrightData...[/bold]")
            scraper = BrightDataFacebookScraper(api_token=api_token)
            raw_posts = scraper.fetch_groups(public_urls, actual_days_back, num_posts)
            bd_posts = _parse_brightdata_posts(raw_posts, public_groups)
            console.print(f"  BrightData: {len(bd_posts)} posts from {len(public_groups)} public groups")
            all_posts.extend(bd_posts)

    # --- Private groups via Playwright ---
    if private_groups:
        console.print(f"[bold]Fetching {len(private_groups)} private groups via Playwright...[/bold]")
        pw_scraper = PlaywrightFacebookScraper()
        pw_posts = pw_scraper.fetch_groups(private_groups, max_scrolls=max_scrolls)
        console.print(f"  Playwright: {len(pw_posts)} posts from {len(private_groups)} private groups")
        all_posts.extend(pw_posts)

    console.print(f"\n[bold]Total fetched: {len(all_posts)} posts from {len(groups)} groups[/bold]")
    return all_posts


def run_filter(posts: list[FacebookPost], config: dict) -> list[FacebookPost]:
    """Apply keyword matching to filter posts."""
    fb_cfg = config.get("facebook_monitor", {})
    matcher = KeywordMatcher(
        extra_keywords=fb_cfg.get("extra_keywords"),
        extra_negatives=fb_cfg.get("extra_negatives"),
    )

    matched = []
    for post in posts:
        keywords = matcher.match(post)
        if keywords:
            post.matched_keywords = keywords
            matched.append(post)

    console.print(f"[bold]Keyword filter: {len(matched)}/{len(posts)} posts matched[/bold]")
    return matched


def run_score(posts: list[FacebookPost], config: dict) -> list[FacebookPost]:
    """Score matched posts with LLM."""
    scorer = PostScorer(config)
    if not scorer.client:
        console.print("[red]No LLM client configured — skipping scoring[/red]")
        return posts
    return scorer.score_batch(posts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Facebook Group Monitor — monitors FB groups for freelance AV gigs"
    )
    parser.add_argument(
        "--fetch-only", action="store_true",
        help="Fetch and cache posts, no scoring",
    )
    parser.add_argument(
        "--score-only", action="store_true",
        help="Re-score last fetch (no new API calls to BrightData)",
    )
    parser.add_argument(
        "--immediate", action="store_true",
        help="Send immediate alerts for HOT posts only",
    )
    parser.add_argument(
        "--digest", action="store_true",
        help="Send daily digest email (HOT + WARM)",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="Score but skip email notifications",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Keyword matches only, no LLM scoring",
    )
    parser.add_argument(
        "--group",
        help="Filter to a single group by name (substring match)",
    )
    parser.add_argument(
        "--days-back", type=int,
        help="Override lookback window (days)",
    )
    parser.add_argument(
        "--tier",
        choices=["high", "medium", "low", "all"],
        default="all",
        help="Filter groups by priority tier (default: all)",
    )
    parser.add_argument(
        "--login", action="store_true",
        help="Open a browser to save Facebook session for private groups",
    )
    args = parser.parse_args()

    # --- Login mode (exits after saving session) ---
    if args.login:
        save_login_session()
        return

    config = load_config()
    cache = load_cache()

    # --- Fetch or load previous ---
    if args.score_only:
        console.print("[bold]Loading previous posts for re-scoring...[/bold]")
        posts = load_previous_posts()
        if not posts:
            console.print("[red]No previous posts found. Run without --score-only first.[/red]")
            sys.exit(1)
        console.print(f"  Loaded {len(posts)} posts from last snapshot")
    else:
        console.print("[bold]Fetching posts from Facebook groups...[/bold]")
        posts = run_fetch(config, args.group, args.days_back, tier_filter=args.tier)
        if not posts:
            console.print("[yellow]No posts fetched. Check config and API token.[/yellow]")
            sys.exit(0)

    # --- Dedup against cache ---
    posts, skipped = deduplicate_posts(posts, cache)
    if skipped:
        console.print(f"[dim]Skipped {skipped} previously seen posts[/dim]")
    if not posts:
        console.print("[yellow]No new posts to process.[/yellow]")
        sys.exit(0)

    # --- Keyword filter ---
    posts = run_filter(posts, config)
    if not posts:
        console.print("[yellow]No posts matched keywords.[/yellow]")
        sys.exit(0)

    if args.fetch_only:
        # Save raw filtered posts and update cache
        save_fb_results(posts)
        for p in posts:
            cache[p.fb_post_hash] = {
                "date_fetched": datetime.now().strftime("%Y-%m-%d"),
                "group": p.group_name,
                "relevance_tier": "",
            }
        save_cache(cache)
        print_fb_summary(posts)
        console.print(f"\n[bold]Fetch complete.[/bold] Results in fb_monitor/{datetime.now().strftime('%Y-%m-%d')}/")
        return

    # --- Score (LLM or dry-run) ---
    if not args.dry_run:
        posts = run_score(posts, config)

    # --- Update cache ---
    for p in posts:
        cache[p.fb_post_hash] = {
            "date_fetched": datetime.now().strftime("%Y-%m-%d"),
            "group": p.group_name,
            "relevance_tier": p.relevance_tier,
        }
    save_cache(cache)

    # --- Save results ---
    json_path, md_path = save_fb_results(posts)

    # --- Supabase sync ---
    sync_fb_posts_to_supabase(config, posts)

    # --- Email ---
    if not args.no_email and not args.dry_run:
        if args.immediate:
            hot_posts = [p for p in posts if p.relevance_tier == "HOT" and not p.alert_sent]
            for p in hot_posts:
                send_immediate_alert(p)
        else:
            send_digest_email(posts)

    # --- Console summary ---
    print_fb_summary(posts)
    console.print(f"\n[bold green]Done![/bold green]")
    console.print(f"  Summary: {md_path}")
    console.print(f"  JSON:    {json_path}")


if __name__ == "__main__":
    main()
