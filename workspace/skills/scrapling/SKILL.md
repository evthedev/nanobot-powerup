---
name: scrapling
description: Stealthy web fetching that bypasses bot detection, Cloudflare, Turnstile, and TLS fingerprinting. Use instead of web_fetch when a URL returns 403/429/503, loads a Cloudflare interstitial, or is known to block scrapers (e.g. Trustpilot, LinkedIn, Indeed, Google). Two modes: fast (TLS fingerprint spoofing, no browser) and stealth (full headless browser with Cloudflare Turnstile auto-solve). Does NOT replace web_search — only use for direct URL fetching.
---

# Scrapling

Drop-in replacement for `web_fetch` on bot-protected pages.

## When to Use

| Signal | Action |
|---|---|
| `web_fetch` returns 403, 429, 503 | Retry with `scrapling_fetch.py --mode fast` |
| Cloudflare interstitial / "Just a moment..." | Use `--mode stealth` |
| Trustpilot, LinkedIn, Indeed, Glassdoor | Start with stealth |
| Regular site, no signs of protection | Keep using `web_fetch` |

## Setup (once per Docker container)

```bash
pip install scrapling
scrapling install        # downloads browser binary (~150MB) — needed for stealth mode only
```

Check if already installed:
```bash
python -c "import scrapling; print(scrapling.__version__)"
```

## Running the Script


```bash
# Auto mode — tries fast first, falls back to stealth on 403/429/503
python3 ~/.nanobot/workspace/skills/scrapling/scrapling_fetch.py <url>

# Fast mode — TLS/JA3 fingerprint spoofing only (no browser, instant)
python3 ~/.nanobot/workspace/skills/scrapling/scrapling_fetch.py <url> --mode fast

# Stealth mode — headless browser, canvas noise, Cloudflare Turnstile bypass
python3 ~/.nanobot/workspace/skills/scrapling/scrapling_fetch.py <url> --mode stealth

# Stealth without Cloudflare auto-solve (faster if page has no Turnstile)
python3 ~/.nanobot/workspace/skills/scrapling/scrapling_fetch.py <url> --mode stealth --no-solve-cf

# Limit output size
python3 ~/.nanobot/workspace/skills/scrapling/scrapling_fetch.py <url> --max-chars 20000
```

Output is JSON: `{ url, mode, status, length, truncated, text, error? }`

## Mode Comparison

| | `fast` | `stealth` |
|---|---|---|
| Mechanism | httpx + TLS/JA3 spoof + real headers | Headless Chromium + fingerprint patches |
| Speed | ~1–2s | ~10–30s |
| Cloudflare interstitial | ✗ | ✓ |
| Cloudflare Turnstile | ✗ | ✓ (auto-solved) |
| Browser binary needed | No | Yes (`scrapling install`) |
| Best for | Most sites, basic bot detection | Cloudflare, Akamai, heavy JS sites |

## Isolation Note

This skill is **additive** — `web_fetch` and `web_search` remain unchanged.
Once tested and working, ask to replace `web_fetch` with Scrapling's `Fetcher` directly.

## Troubleshooting

- **`ModuleNotFoundError: scrapling`** → run `pip install scrapling`
- **Stealth fails silently** → try `--no-solve-cf` first to isolate Turnstile
- **Still 403 on stealth** → page may need proxy rotation; add `proxy="http://user:pass@host:port"` to `StealthyFetcher.fetch()`
- **Timeout on stealth** → increase with `timeout=60000` in the fetch call
