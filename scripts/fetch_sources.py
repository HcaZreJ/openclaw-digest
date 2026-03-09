#!/usr/bin/env python3
"""
OpenClaw Digest — fetch latest OpenClaw-related content from multiple channels.

Outputs structured JSON to stdout. Each source is fetched independently;
a failure in one source does not block the others.

Uses curl_cffi to impersonate real browser TLS fingerprints, which bypasses
most anti-bot detection (Reddit, Sogou, DuckDuckGo, etc.).

Dependencies: curl_cffi, beautifulsoup4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

TIMEOUT = 15
GITHUB_REPO = "openclaw/openclaw"
BROWSER = "chrome"  # curl_cffi impersonation target


# ── helpers ───────────────────────────────────────────────────────────

def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _cutoff(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _parse_iso(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def _get(url: str, *, headers: dict | None = None, params: dict | None = None) -> cffi_requests.Response:
    return cffi_requests.get(url, headers=headers, params=params,
                             impersonate=BROWSER, timeout=TIMEOUT)


def _post(url: str, *, data: dict | None = None, headers: dict | None = None) -> cffi_requests.Response:
    return cffi_requests.post(url, data=data, headers=headers,
                              impersonate=BROWSER, timeout=TIMEOUT)


# ── GitHub Releases ───────────────────────────────────────────────────

def fetch_github_releases(hours: int) -> list[dict]:
    cutoff = _cutoff(hours)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    resp = _get(url, headers=_github_headers(), params={"per_page": 20})
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

def fetch_github_discussions(hours: int) -> list[dict]:
    cutoff = _cutoff(hours)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    q = f"repo:{GITHUB_REPO} type:discussion created:>{cutoff_str}"
    url = "https://api.github.com/search/issues"
    resp = _get(url, headers=_github_headers(),
                params={"q": q, "sort": "created", "order": "desc", "per_page": 30})
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

def _scrape_blog(base_url: str, hours: int) -> list[dict]:
    """Generic blog scraper. Looks for <article> or common blog post patterns."""
    cutoff = _cutoff(hours)
    resp = _get(base_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    articles = soup.select("article") or soup.select(".post") or soup.select(".blog-post")
    if not articles:
        articles = soup.select("a[href*='/blog/']")

    seen_urls = set()
    for el in articles[:30]:
        link_el = el if el.name == "a" else el.select_one("a[href]")
        if not link_el or not link_el.get("href"):
            continue

        href = link_el["href"]
        if href.startswith("/"):
            href = base_url.rstrip("/") + href

        # Skip non-article links (language switchers, nav, index pages)
        path = href.split("//", 1)[-1].split("/", 1)[-1]
        path_parts = [p for p in path.strip("/").split("/") if p]
        if len(path_parts) < 2 or path_parts[-1] == "blog":
            continue

        if href in seen_urls:
            continue
        seen_urls.add(href)

        title_el = el.select_one("h1, h2, h3") or link_el
        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            continue

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


def fetch_official_blog(hours: int) -> list[dict]:
    return _scrape_blog("https://openclaw.ai/blog", hours)


def fetch_community_blog(hours: int) -> list[dict]:
    return _scrape_blog("https://openclaws.io/blog", hours)


# ── Reddit ────────────────────────────────────────────────────────────

def fetch_reddit(hours: int) -> list[dict]:
    cutoff = _cutoff(hours)
    subreddits = ["AI_Agents", "LocalLLaMA", "vibecoding"]
    items = []

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {"q": "openclaw", "sort": "new", "restrict_sr": "on", "t": "week", "limit": 20}
        try:
            resp = _get(url, params=params)
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

    seen = set()
    unique = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


# ── X / Twitter (via DuckDuckGo search) ───────────────────────────────

def fetch_twitter(hours: int) -> list[dict]:
    """
    Twitter has no free API. Uses DuckDuckGo HTML search to find
    recent tweets mentioning OpenClaw. Best-effort, no exact timestamps.
    """
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = _post(url, data={"q": "openclaw site:x.com", "df": "d"})
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

def fetch_wechat(hours: int) -> list[dict]:
    """
    Searches Sogou's WeChat article index via POST form submission.
    Requires a session (cookie from homepage) + curl_cffi browser impersonation
    to bypass Sogou's anti-bot checks.
    """
    try:
        s = cffi_requests.Session(impersonate=BROWSER)
        s.get("https://weixin.sogou.com/", timeout=TIMEOUT)
        resp = s.post("https://weixin.sogou.com/weixin", data={
            "ie": "utf8",
            "s_from": "input",
            "_sug_": "n",
            "_sug_type_": "",
            "type": "2",
            "query": "openclaw",
        }, headers={
            "Referer": "https://weixin.sogou.com/",
            "Origin": "https://weixin.sogou.com",
        }, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for el in soup.select(".news-list li"):
        # Title and link are in .txt-box h3 a
        title_link = el.select_one(".txt-box h3 a")
        if not title_link:
            continue
        title = title_link.get_text(strip=True)
        if not title:
            continue
        href = title_link.get("href", "")
        if href.startswith("/"):
            href = "https://weixin.sogou.com" + href

        snippet_el = el.select_one(".txt-info")
        snippet = snippet_el.get_text(strip=True)[:500] if snippet_el else ""

        account_el = el.select_one(".s-p .all-time-y2, .s-p a")
        account = account_el.get_text(strip=True) if account_el else ""

        items.append({
            "title": title,
            "url": href,
            "snippet": snippet,
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
    return list(dict.fromkeys(names))


def fetch_all(hours: int, source_names: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    total = 0

    for name in source_names:
        fn = ALL_SOURCES[name]
        try:
            items = fn(hours)
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
    print()


if __name__ == "__main__":
    main()
