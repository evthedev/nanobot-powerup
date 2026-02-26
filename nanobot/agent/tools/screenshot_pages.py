"""Generic screenshot_pages tool — navigates to a list of URLs, captures a screenshot
of each, extracts visible text, and returns everything to the calling agent.

Decoupled from any domain: the caller constructs the URLs. Works for travel research,
product reviews, restaurant lookups, news pages, or anything else.
"""

import os
import re
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, quote_plus

from loguru import logger

from nanobot.agent.tools.base import Tool


def _rewrite_google_url(url: str) -> tuple[str, bool]:
    """
    Google detects headless browsers and serves a CAPTCHA — useless for screenshots.
    Rewrite any google.com URL to DuckDuckGo by extracting the 'q' param.
    Returns (rewritten_url, was_rewritten).
    """
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().lstrip("www.")
        if not (host == "google.com" or host.endswith(".google.com")):
            return url, False
        params = parse_qs(parsed.query)
        query = (params.get("q") or params.get("query") or [""])[0].strip()
        if query:
            ddg = f"https://duckduckgo.com/?q={quote_plus(query)}&ia=web"
        else:
            # No query param — fall back to a generic Bing search using the path
            path_hint = parsed.path.strip("/").replace("/", " ")
            ddg = f"https://duckduckgo.com/?q={quote_plus(path_hint or 'web search')}&ia=web"
        return ddg, True
    except Exception:
        return url, False

_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "/api/screenshots")
_SCREENSHOTS_DIR = os.path.expanduser("~/.nanobot/workspace/screenshots")


class ScreenshotPagesTool(Tool):
    """
    Navigates to each provided URL using direct Playwright Python, captures a
    screenshot and extracts visible text. Returns extracted content plus image
    URLs to the calling agent — no subagents, no LLM concurrency issues.

    Generic: caller provides the URLs and labels. Works for any research task.
    """

    def __init__(self, manager=None, screenshots_dir: str = "", send_callback=None):  # pylint: disable=unused-argument
        self._manager = manager

    def set_context(self, channel: str, chat_id: str) -> None:
        pass

    def set_send_callback(self, callback) -> None:
        pass

    @property
    def name(self) -> str:
        return "screenshot_pages"

    @property
    def description(self) -> str:
        return (
            "Navigates to URLs using a real browser, captures screenshots, and returns text "
            "content + image URLs. Use for visual proof that a specific fact came from a real "
            "source.\n\n"
            "TWO TYPES OF SCREENSHOTS:\n"
            "• TYPE A (prices/availability only): DuckDuckGo or Booking.com search results — "
            "price cards appear inline. Use for flights, hotels, ticket prices.\n"
            "• TYPE B (all factual claims about specific things): The ACTUAL SOURCE PAGE — "
            "Wikipedia, TripAdvisor, official site, Reddit thread. A search results page "
            "(DuckDuckGo link list) does NOT verify a claim about a place or product — it only "
            "proves a search was typed. You MUST screenshot the actual Wikipedia/TripAdvisor/"
            "official page that contains the information.\n\n"
            "NEVER use google.com — redirects to CAPTCHA. "
            "NEVER use DuckDuckGo/Bing for factual claims about places/products/events."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Lowercase hyphenated identifier used for screenshot filenames, "
                        "e.g. 'coldplay-tokyo-mar26' or 'iphone16-review'. Keep it short."
                    ),
                },
                "pages": {
                    "type": "array",
                    "description": (
                        "Ordered list of pages to visit. Each entry has a 'url' and a 'label'. "
                        "Screenshots are named {slug}-{label}.png. Max 5 pages."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Full URL to navigate to.",
                            },
                            "label": {
                                "type": "string",
                                "description": (
                                    "Short snake_case label for this page, used in the filename "
                                    "and in the result block. E.g. 'flights', 'hotels', 'tickets', "
                                    "'reviews', 'menu'."
                                ),
                            },
                            "wait_seconds": {
                                "type": "number",
                                "description": "Seconds to wait after page load before screenshot. Default: 4.",
                                "default": 4,
                            },
                        },
                        "required": ["url", "label"],
                    },
                    "maxItems": 5,
                },
            },
            "required": ["slug", "pages"],
        }

    async def execute(  # pylint: disable=arguments-differ
        self,
        slug: str,
        pages: list[dict],
        **kwargs: Any,
    ) -> str:
        import math as _math
        safe_slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

        # Hard limit: reject > 5 pages and tell the agent exactly how to split
        if len(pages) > 5:
            n_calls = _math.ceil(len(pages) / 5)
            splits = "\n".join(
                f"  Call {i+1}: slug='{safe_slug}-{i+1}', pages {i*5+1}–{min((i+1)*5, len(pages))}"
                for i in range(n_calls)
            )
            logger.warning(
                "screenshot_pages: ❌ {} pages submitted for slug='{}' — max is 5. Rejected.",
                len(pages), safe_slug,
            )
            return (
                f"❌ screenshot_pages REJECTED: {len(pages)} pages submitted but max is 5 per call.\n\n"
                f"You MUST split this into {n_calls} separate calls:\n{splits}\n\n"
                f"Make {n_calls} separate screenshot_pages calls with different slugs and 5 pages each. "
                f"Do NOT try to combine them into one call."
            )

        import asyncio as _asyncio  # pylint: disable=import-outside-toplevel
        from playwright.async_api import async_playwright  # pylint: disable=import-outside-toplevel

        results: list[dict] = []  # {label, url, img_url, content, ok}

        logger.info("screenshot_pages: launching Playwright for slug='{}', {} pages", safe_slug, len(pages))

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                page = await browser.new_page()

                for entry in pages[:5]:
                    url = entry.get("url", "").strip()
                    label = re.sub(r"[^a-z0-9_-]", "-", entry.get("label", "page").lower()).strip("-")
                    wait_sec = float(entry.get("wait_seconds", 4))

                    # Hard-redirect Google URLs to DuckDuckGo — Google serves CAPTCHA to headless browsers
                    url, was_rewritten = _rewrite_google_url(url)
                    if was_rewritten:
                        logger.warning("screenshot_pages: ⛔ Google URL blocked — redirected to DuckDuckGo: {}", url)

                    # Warn when a search-results page is used for a non-price label
                    # (search results don't verify factual claims — source pages do)
                    _is_search_results = any(h in url for h in ("duckduckgo.com", "bing.com/search", "bing.com/news"))
                    _price_labels = {"flights", "hotels", "hotel", "flight", "tickets", "ticket", "price", "prices", "availability"}
                    if _is_search_results and label not in _price_labels:
                        logger.warning(
                            "screenshot_pages: ⚠️ Search-results URL used for label='{}' — "
                            "this verifies nothing. Use a source page (Wikipedia, TripAdvisor, "
                            "official site) to actually verify factual claims. URL: {}", label, url
                        )

                    filename = f"{safe_slug}-{label}.png"
                    filepath = f"{_SCREENSHOTS_DIR}/{filename}"
                    img_url = f"{_SCREENSHOTS_URL}/{filename}"

                    content = ""
                    ok = False

                    logger.info("screenshot_pages: navigating to {} → {}", label, url)
                    try:
                        await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                        await _asyncio.sleep(wait_sec)
                        # Dismiss modal/popup dialogs (Booking.com sign-in, DuckDuckGo upgrade)
                        try:
                            await page.keyboard.press("Escape")
                            await _asyncio.sleep(0.3)
                        except Exception:
                            pass
                        try:
                            # JS fallback: hide large overlay/modal/popup elements
                            await page.evaluate(
                                "document.querySelectorAll("
                                "'[class*=\"popup\"], [class*=\"modal\"], [class*=\"overlay\"],"
                                " [id*=\"popup\"], [id*=\"modal\"], [id*=\"overlay\"],"
                                " [role=\"dialog\"]'"
                                ").forEach(el => {"
                                "  const r = el.getBoundingClientRect();"
                                "  if (r.width > 100 && r.height > 100) el.style.display = 'none';"
                                "})"
                            )
                            await _asyncio.sleep(0.3)
                        except Exception:
                            pass
                        content = (await page.inner_text("body"))[:5000]
                        await page.screenshot(path=filepath, type="png", full_page=False)
                        ok = True
                        logger.info("screenshot_pages: ✅ {} saved → {}", label, filepath)
                    except Exception as exc:
                        logger.warning("screenshot_pages: ⚠️ {} failed: {}", label, exc)
                        try:
                            await page.screenshot(path=filepath, type="png")
                        except Exception:
                            pass

                    results.append({
                        "label": label,
                        "url": url,
                        "img_url": img_url,
                        "content": content,
                        "ok": ok,
                        "rewritten": was_rewritten,
                        "search_results_warning": _is_search_results and label not in _price_labels,
                    })

                await browser.close()

        except Exception as exc:
            logger.error("screenshot_pages: Playwright session failed: {}", exc)

        # Build structured return for the calling agent
        lines = [
            f"## screenshot_pages results for '{safe_slug}'\n",
            f"Captured {sum(1 for r in results if r['ok'])}/{len(results)} pages successfully.\n",
            "\n### Image URLs\n",
            "⚠️ CRITICAL: Only embed URLs marked ✅ USABLE — those files were saved to disk.\n"
            "DO NOT embed ❌ FAILED URLs — those files do NOT exist and will show as broken images.\n\n",
        ]
        for r in results:
            rewrite_note = " [Google URL redirected to DuckDuckGo]" if r.get("rewritten") else ""
            search_warn = (
                " ❌ [SEARCH RESULTS PAGE — does not verify factual claims. "
                "Re-screenshot using Wikipedia/TripAdvisor/official source page instead.]"
            ) if r.get("search_results_warning") else ""
            if r["ok"]:
                lines.append(f"- **{r['label']}** ✅ USABLE{rewrite_note}{search_warn}: `{r['img_url']}`\n")
            else:
                lines.append(
                    f"- **{r['label']}** ❌ FAILED — file NOT saved — DO NOT EMBED: `{r['img_url']}`\n"
                )

        lines.append("\n")
        for r in results:
            status = "✅" if r["ok"] else "⚠️ no content"
            lines.append(f"### {r['label'].upper()} page content ({status})\n")
            lines.append(f"Source: {r['url']}\n")
            if r["content"]:
                lines.append(f"```\n{r['content']}\n```\n\n")
            else:
                lines.append("```\n(failed to load)\n```\n\n")

        lines.append(
            "Extract all relevant data (prices, names, availability, etc.) from the content above. "
            "Embed ONLY the ✅ USABLE image URLs in your response — never the ❌ FAILED ones.\n"
            "For any ❌ FAILED page, retry with a different URL (e.g. Wikipedia or TripAdvisor) "
            "rather than embedding a broken URL.\n"
        )

        return "".join(lines)
