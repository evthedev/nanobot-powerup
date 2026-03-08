#!/usr/bin/env python3
"""
Stealthy page fetcher using Scrapling.

USAGE:
  python3 scrapling_fetch.py <url> [--mode fast|stealth|auto] [--max-chars N]

MODES:
  fast    — Fetcher: TLS/JA3 fingerprint spoofing + real browser headers (no browser binary)
  stealth — StealthyFetcher: full headless browser with canvas noise, Cloudflare bypass
  auto    — tries fast first, falls back to stealth on 403/429/503 or error (default)

OUTPUT: JSON with keys: url, mode, status, length, truncated, text, error
"""

import sys
import json
import re
import html
import argparse

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


def _extract(html_content: str) -> str:
    """Extract readable text from raw HTML string via readability, fallback to strip."""
    try:
        from readability import Document
        doc = Document(html_content)
        title = doc.title() or ""
        body = _to_markdown(doc.summary())
        return f"# {title}\n\n{body}" if title else body
    except Exception:
        return _normalize(_strip_tags(html_content))


def _response_html(response) -> str:
    """Safely get HTML string from a Scrapling response object."""
    # Scrapling responses expose the raw HTML via .html_content or .text
    for attr in ("html_content", "text", "content"):
        val = getattr(response, attr, None)
        if val and isinstance(val, str):
            return val
        if val and isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
    return str(response)


def _response_status(response) -> int:
    """Get HTTP status from a Scrapling response (attribute name varies by fetcher)."""
    return getattr(response, "status", None) or getattr(response, "status_code", 0)


def fetch_fast(url: str, max_chars: int) -> dict:
    """Fetcher — TLS fingerprint spoofing, no browser binary needed."""
    from scrapling.fetchers import Fetcher
    try:
        response = Fetcher.get(url, stealthy_headers=True, follow_redirects=True)
        text = _extract(_response_html(response))
        truncated = len(text) > max_chars
        return {
            "url": url,
            "mode": "fast",
            "status": _response_status(response),
            "length": len(text),
            "truncated": truncated,
            "text": text[:max_chars],
        }
    except Exception as e:
        return {"url": url, "mode": "fast", "error": str(e)}


def _ensure_patchright() -> None:
    """Install patchright browser binary if missing (first run after image build)."""
    try:
        from scrapling.fetchers import StealthyFetcher  # noqa: F401
    except Exception:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "scrapling[all]", "-q"], check=False)
        subprocess.run(["scrapling", "install"], check=False)


def fetch_stealth(url: str, max_chars: int, solve_cloudflare: bool = True) -> dict:
    """StealthyFetcher — headless browser with canvas noise, Cloudflare bypass."""
    _ensure_patchright()
    from scrapling.fetchers import StealthyFetcher
    try:
        response = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            block_webrtc=True,
            allow_webgl=False,
            timeout=60000,
            extra_headers={"Accept-Language": "en-US,en;q=0.9"},
            solve_cloudflare=solve_cloudflare,
        )
        text = _extract(_response_html(response))
        truncated = len(text) > max_chars
        return {
            "url": url,
            "mode": "stealth",
            "status": _response_status(response),
            "length": len(text),
            "truncated": truncated,
            "text": text[:max_chars],
        }
    except Exception as e:
        return {"url": url, "mode": "stealth", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Stealthy page fetcher using Scrapling")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--mode", choices=["fast", "stealth", "auto"], default="auto")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS_DEFAULT, dest="max_chars")
    parser.add_argument("--no-solve-cf", action="store_true",
                        help="Disable Cloudflare Turnstile auto-solve (stealth mode only)")
    args = parser.parse_args()

    solve_cf = not args.no_solve_cf

    if args.mode == "fast":
        result = fetch_fast(args.url, args.max_chars)
    elif args.mode == "stealth":
        result = fetch_stealth(args.url, args.max_chars, solve_cloudflare=solve_cf)
    else:  # auto
        result = fetch_fast(args.url, args.max_chars)
        blocked = "error" in result or _response_status_from_result(result) in (403, 429, 503)
        if blocked:
            print(json.dumps({"info": "fast mode blocked, retrying with stealth..."}), flush=True)
            result = fetch_stealth(args.url, args.max_chars, solve_cloudflare=solve_cf)

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _response_status_from_result(result: dict) -> int:
    return result.get("status", 0)


if __name__ == "__main__":
    main()
