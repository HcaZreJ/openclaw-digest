# Data Source Reference

## GitHub (Releases + Discussions)

- **API**: REST API v3, no auth required for public repos
- **Rate limit**: 60 req/hr unauthenticated, 5000 req/hr with `GITHUB_TOKEN`
- **Repo**: `openclaw/openclaw`
- **Reliability**: High

Set token:
```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
```

## Official Blog (openclaw.ai/blog)

- **Method**: HTTP GET + HTML parsing with BeautifulSoup
- **Looks for**: `<article>`, `<time datetime="...">`, heading + link patterns
- **Reliability**: Medium — depends on HTML structure staying consistent
- **No auth required**

## Community Blog (openclaws.io/blog)

- **Method**: Same as official blog
- **Reliability**: Medium
- **No auth required**

## Reddit

- **API**: Public JSON endpoint (append `.json` to any reddit URL)
- **Subreddits searched**: r/AI_Agents, r/LocalLLaMA, r/vibecoding
- **Rate limit**: Requires User-Agent header; ~100 req/min
- **Reliability**: High
- **No auth required**

## X / Twitter

- **Method**: DuckDuckGo HTML search for `openclaw site:x.com`
- **Limitation**: No exact timestamps, results are approximate
- **Rate limit**: Moderate (DuckDuckGo may rate-limit)
- **Reliability**: Low — best-effort supplementary source
- **No auth required**

The Twitter/X API requires paid access ($100/mo minimum). The DuckDuckGo fallback is free but coarse. If you have API access, consider replacing this fetcher.

## WeChat (via Sogou)

- **Method**: Sogou WeChat search (`weixin.sogou.com`)
- **Limitation**: Sogou aggressively rate-limits and may require CAPTCHA
- **Reliability**: Low — treat as supplementary
- **No auth required** (but may be blocked)

For more reliable WeChat fetching, consider using the `wechat-article-to-markdown` skill with specific article URLs.
