#!/usr/bin/env python3
"""
Stealthy page fetcher using Scrapling.

USAGE:
  python3 scrapling_fetch.py <url> [--mode fast|stealth] [--max-chars N]

MODES:
  fast    — Fetcher: TLS/JA3 fingerprint spoofing + real browser headers (no browser binary)
  stealth — StealthyFetcher: full headless browser with canvas noise, CDP removal, Cloudflare bypass

SETUP (run once inside Docker):
  pip install scrapling
  scrapling install           # downloads browser binaries for stealth mode

OUTPUT: JSON with keys: url, mode, status, length, truncated, text, error
"""

import sys
import json
import re
import html
import argparse
from pathlib import Path

MAX_CHARS_DEFAULT = 50_000


def _strip_tags(text: str) -> str:
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _to_markdown(raw_html: str) -> str:
    text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                  lambda m: f'[{_strip_tags(m[2])}]({m[1]})', raw_html, flags=re.I)
    text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                  lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
    text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
    text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
    text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
    return _normalize(_strip_tags(text))


def extract_text(page_or_response, use_readability: bool = True) -> str:
    """Extract readable text from a Scrapling Page or raw HTML string."""
    raw = page_or_response if isinstance(page_or_response, str) else str(page_or_response.html)
    if use_readability:
        try:
            from readability import Document
            doc = Document(raw)
            title = doc.title() or ""
            body = _to_markdown(doc.summary())
            return f"# {title}\n\n{body}" if title else body
        except ImportError:
            pass
    return _normalize(_strip_tags(raw))


def fetch_fast(url: str, max_chars: int) -> dict:
    """Use Scrapling Fetcher — TLS fingerprint spoofing, no browser binary needed."""
    from scrapling.fetchers import Fetcher

    fetcher = Fetcher(auto_match=False)
    try:
        response = fetcher.get(url, stealthy_headers=True, follow_redirects=True)
        text = extract_text(response)
        truncated = len(text) > max_chars
        return {
            "url": url,
            "mode": "fast",
            "status": response.status,
            "length": len(text),
            "truncated": truncated,
            "text": text[:max_chars],
        }
    except Exception as e:
        return {"url": url, "mode": "fast", "error": str(e)}


def fetch_stealth(url: str, max_chars: int, solve_cloudflare: bool = True) -> dict:
    """Use Scrapling StealthyFetcher — headless browser with canvas noise, Cloudflare bypass."""
    from scrapling.fetchers import StealthyFetcher

    try:
        # StealthyFetcher.fetch() is synchronous (handles its own event loop internally)
        response = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            block_webrtc=True,
            allow_webgl=False,
            extra_headers={"Accept-Language": "en-US,en;q=0.9"},
            solve_cloudflare=solve_cloudflare,
        )
        text = extract_text(response)
        truncated = len(text) > max_chars
        return {
            "url": url,
            "mode": "stealth",
            "status": response.status,
            "length": len(text),
            "truncated": truncated,
            "text": text[:max_chars],
        }
    except Exception as e:
        return {"url": url, "mode": "stealth", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Stealthy page fetcher using Scrapling")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--mode", choices=["fast", "stealth", "auto"], default="auto",
                        help="fast=TLS spoofing only, stealth=full browser, auto=fast then stealth on failure")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS_DEFAULT, dest="max_chars")
    parser.add_argument("--no-solve-cf", action="store_true",
                        help="Disable Cloudflare Turnstile auto-solve (stealth mode only)")
    args = parser.parse_args()

    url = args.url
    solve_cf = not args.no_solve_cf

    if args.mode == "fast":
        result = fetch_fast(url, args.max_chars)
    elif args.mode == "stealth":
        result = fetch_stealth(url, args.max_chars, solve_cloudflare=solve_cf)
    else:  # auto
        result = fetch_fast(url, args.max_chars)
        if "error" in result or result.get("status", 200) in (403, 429, 503):
            print(json.dumps({"info": "fast mode blocked, retrying with stealth..."}), flush=True)
            result = fetch_stealth(url, args.max_chars, solve_cloudflare=solve_cf)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
