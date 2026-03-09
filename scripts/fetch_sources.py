#!/usr/bin/env python3
"""
OpenClaw Digest — fetch latest OpenClaw-related content from multiple channels.

Outputs structured JSON to stdout. Each source is fetched independently;
a failure in one source does not block the others.

Dependencies: httpx, beautifulsoup4
Install:  pip install httpx beautifulsoup4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

TIMEOUT = 15.0
USER_AGENT = "OpenClawDigest/1.0 (https://github.com/openclaw/openclaw)"
GITHUB_REPO = "openclaw/openclaw"


# ── helpers ───────────────────────────────────────────────────────────

def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _cutoff(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _parse_iso(date_str: str) -> datetime:
    # GitHub uses ISO 8601 with Z suffix
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


# ── GitHub Releases ───────────────────────────────────────────────────

def fetch_github_releases(client: httpx.Client, hours: int) -> list[dict]:
    cutoff = _cutoff(hours)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    resp = client.get(url, headers=_github_headers(), params={"per_page": 20})
    resp.raise_for_status()

    items = []
    for r in resp.json():
        published = _parse_iso(r["published_at"])
        if published < cutoff:
            break
        items.append({
            "title": r["name"] or r["tag_name"],
            "url": r["html_url"],
            "body": (r["body"] or "")[:2000],
            "date": r["published_at"],
            "tag": r["tag_name"],
        })
    return items


# ── GitHub Discussions (via search API) ───────────────────────────────

def fetch_github_discussions(client: httpx.Client, hours: int) -> list[dict]:
    cutoff = _cutoff(hours)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    q = f"repo:{GITHUB_REPO} type:discussion created:>{cutoff_str}"
    url = "https://api.github.com/search/issues"
    resp = client.get(url, headers=_github_headers(), params={"q": q, "sort": "created", "order": "desc", "per_page": 30})
    resp.raise_for_status()

    items = []
    for item in resp.json().get("items", []):
        items.append({
            "title": item["title"],
            "url": item["html_url"],
            "body": (item.get("body") or "")[:1000],
            "date": item["created_at"],
            "labels": [l["name"] for l in item.get("labels", [])],
        })
    return items


# ── Blog scraping (generic) ──────────────────────────────────────────

def _scrape_blog(client: httpx.Client, base_url: str, hours: int) -> list[dict]:
    """Generic blog scraper. Looks for <article> or common blog post patterns."""
    cutoff = _cutoff(hours)
    resp = client.get(base_url, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    # Try common blog patterns: <article>, .post, .blog-post
    articles = soup.select("article") or soup.select(".post") or soup.select(".blog-post")
    if not articles:
        # Fallback: look for links that look like blog posts
        articles = soup.select("a[href*='/blog/']")

    for el in articles[:20]:
        link_el = el if el.name == "a" else el.select_one("a[href]")
        if not link_el or not link_el.get("href"):
            continue

        href = link_el["href"]
        if href.startswith("/"):
            href = base_url.rstrip("/") + href

        title_el = el.select_one("h1, h2, h3") or link_el
        title = title_el.get_text(strip=True)
        if not title:
            continue

        # Try to find a date
        time_el = el.select_one("time")
        date_str = ""
        if time_el and time_el.get("datetime"):
            date_str = time_el["datetime"]
            try:
                dt = _parse_iso(date_str)
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        snippet_el = el.select_one("p")
        snippet = snippet_el.get_text(strip=True)[:500] if snippet_el else ""

        items.append({
            "title": title,
            "url": href,
            "snippet": snippet,
            "date": date_str,
        })

    return items


def fetch_official_blog(client: httpx.Client, hours: int) -> list[dict]:
    return _scrape_blog(client, "https://openclaw.ai/blog", hours)


def fetch_community_blog(client: httpx.Client, hours: int) -> list[dict]:
    return _scrape_blog(client, "https://openclaws.io/blog", hours)


# ── Reddit ────────────────────────────────────────────────────────────

def fetch_reddit(client: httpx.Client, hours: int) -> list[dict]:
    cutoff = _cutoff(hours)
    subreddits = ["AI_Agents", "LocalLLaMA", "vibecoding"]
    items = []

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {"q": "openclaw", "sort": "new", "restrict_sr": "on", "t": "day", "limit": 20}
        try:
            resp = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        for post in data.get("data", {}).get("children", []):
            p = post["data"]
            created = datetime.fromtimestamp(p["created_utc"], tz=timezone.utc)
            if created < cutoff:
                continue
            items.append({
                "title": p["title"],
                "url": f"https://www.reddit.com{p['permalink']}",
                "body": (p.get("selftext") or "")[:1000],
                "date": created.isoformat(),
                "subreddit": p["subreddit"],
                "score": p.get("score", 0),
            })

    # Deduplicate by URL
    seen = set()
    unique = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


# ── X / Twitter (via web search fallback) ─────────────────────────────

def fetch_twitter(client: httpx.Client, hours: int) -> list[dict]:
    """
    Twitter has no free API. This uses a DuckDuckGo HTML search as a
    best-effort fallback to find recent tweets mentioning OpenClaw.
    Results are coarse — no exact timestamps — but better than nothing.
    """
    url = "https://html.duckduckgo.com/html/"
    params = {"q": "openclaw site:x.com", "df": "d"}  # df=d means past day
    try:
        resp = client.post(url, data=params, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for result in soup.select(".result__a")[:15]:
        href = result.get("href", "")
        title = result.get_text(strip=True)
        if "x.com" in href or "twitter.com" in href:
            items.append({
                "title": title,
                "url": href,
                "date": "",
                "note": "via DuckDuckGo search, date approximate",
            })
    return items


# ── WeChat (via Sogou search) ─────────────────────────────────────────

def fetch_wechat(client: httpx.Client, hours: int) -> list[dict]:
    """
    Searches Sogou's WeChat article index. This is fragile and may be
    rate-limited or blocked. Treat as best-effort supplementary source.
    """
    url = "https://weixin.sogou.com/weixin"
    params = {"type": 2, "query": "openclaw", "ie": "utf8", "s_from": "input", "tsn": 1}  # tsn=1 means past day
    try:
        resp = client.get(url, params=params, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://weixin.sogou.com/",
        })
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for el in soup.select(".news-list li, .news-box li"):
        link = el.select_one("a")
        if not link:
            continue
        title = link.get_text(strip=True)
        href = link.get("href", "")
        if href.startswith("/"):
            href = "https://weixin.sogou.com" + href

        account_el = el.select_one(".account")
        account = account_el.get_text(strip=True) if account_el else ""

        items.append({
            "title": title,
            "url": href,
            "date": "",
            "account": account,
            "note": "via Sogou WeChat search",
        })
    return items[:10]


# ── Orchestrator ──────────────────────────────────────────────────────

ALL_SOURCES = {
    "github_releases": fetch_github_releases,
    "github_discussions": fetch_github_discussions,
    "official_blog": fetch_official_blog,
    "community_blog": fetch_community_blog,
    "reddit": fetch_reddit,
    "twitter": fetch_twitter,
    "wechat": fetch_wechat,
}

# Source groups for --sources shorthand
SOURCE_GROUPS = {
    "github": ["github_releases", "github_discussions"],
    "blog": ["official_blog", "community_blog"],
    "reddit": ["reddit"],
    "twitter": ["twitter"],
    "wechat": ["wechat"],
}


def resolve_sources(spec: str) -> list[str]:
    if spec == "all":
        return list(ALL_SOURCES.keys())
    names = []
    for part in spec.split(","):
        part = part.strip()
        if part in SOURCE_GROUPS:
            names.extend(SOURCE_GROUPS[part])
        elif part in ALL_SOURCES:
            names.append(part)
    return list(dict.fromkeys(names))  # deduplicate, preserve order


def fetch_all(hours: int, source_names: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    total = 0

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for name in source_names:
            fn = ALL_SOURCES[name]
            try:
                items = fn(client, hours)
                results[name] = items
                total += len(items)
            except Exception as e:
                results[name] = {"error": str(e)}

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "period_hours": hours,
        "sources": results,
        "total_items": total,
    }


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch latest OpenClaw-related content from multiple channels."
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="How far back to look (default: 24)",
    )
    parser.add_argument(
        "--sources", type=str, default="all",
        help="Comma-separated source names or groups: all, github, blog, reddit, twitter, wechat (default: all)",
    )
    args = parser.parse_args()

    source_names = resolve_sources(args.sources)
    if not source_names:
        print("Error: no valid sources specified", file=sys.stderr)
        sys.exit(1)

    result = fetch_all(args.hours, source_names)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()  # trailing newline


if __name__ == "__main__":
    main()
