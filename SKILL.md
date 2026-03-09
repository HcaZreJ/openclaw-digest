---
name: openclaw-digest
description: >
  Fetch and summarize the latest OpenClaw project updates from GitHub, blogs, Reddit, Twitter, and WeChat.
  Use this skill whenever the user wants an OpenClaw daily digest, OpenClaw news roundup, project tracking,
  or asks about recent OpenClaw developments. Also trigger when setting up automated OpenClaw monitoring
  or cron jobs for tech news aggregation.
---

# OpenClaw Digest

Fetch the latest OpenClaw-related content from multiple channels, summarize in Chinese, and produce a structured digest ready to post (e.g., to Feishu, Slack, or any messaging platform).

## Prerequisites

Python 3.10+ with dependencies managed by `uv`:

```bash
cd <skill-path>
uv venv && source .venv/bin/activate
uv sync
```

Optional: set `GITHUB_TOKEN` env var for higher GitHub API rate limits (unauthenticated limit is 60 req/hr).

## Step 1: Fetch raw content

Run the fetch script from the skill directory:

```bash
cd <skill-path> && uv run python scripts/fetch_sources.py --hours 24
```

This outputs JSON to stdout with content from:
- **GitHub Releases** — new version announcements
- **GitHub Discussions** — community Q&A and proposals
- **Official Blog** (openclaw.ai/blog) — project announcements
- **Community Blog** (openclaws.io/blog) — tutorials and guides
- **Reddit** (r/AI_Agents, r/LocalLLaMA, r/vibecoding) — community posts
- **X/Twitter** — tweets mentioning OpenClaw (via DuckDuckGo, best-effort)
- **WeChat** — Chinese articles (via Sogou search, best-effort)

To fetch only specific sources: `--sources github,reddit`

To look further back: `--hours 168` (7 days)

## Step 2: Summarize

Read the JSON output and produce a Chinese digest. For each item, write a one-sentence summary of what it says and why it matters. Group by source.

Use this template:

```
📋 OpenClaw 每日速递 (YYYY-MM-DD)

🔖 版本更新
- vX.Y.Z: [一句话说明此版本的关键变化]

💬 社区讨论
- [讨论标题]: [一句话概括核心观点或问题]

📝 博客文章
- [文章标题]: [一句话总结要点]

🗨️ Reddit 热议
- [帖子标题] (r/xxx, ↑分数): [一句话总结]

🐦 Twitter 动态
- [推文概要]

📱 微信文章
- [文章标题] (公众号名): [一句话总结]

---
共 N 条更新 | 数据来源: GitHub, Blog, Reddit, Twitter, WeChat
```

Skip any section that has zero items. If a source returned an error, note it briefly at the bottom.

## Step 3: Deliver

Send the formatted digest to the designated channel (Feishu, Slack, etc.) according to how your messaging integration is configured.

## Customization

See `references/sources.md` for details on each data source, including rate limits, authentication, and known limitations.
