"""Generic screenshot_pages tool — navigates to a list of URLs, captures a screenshot
of each, extracts visible text, and returns everything to the calling agent.

Decoupled from any domain: the caller constructs the URLs. Works for travel research,
product reviews, restaurant lookups, news pages, or anything else.
"""

import os
import re
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "http://localhost:3001/api/screenshots")
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
            "Navigates to a list of URLs using a real browser, captures a screenshot of each "
            "page, and returns the extracted text content plus image URLs. Use this whenever "
            "you need live visual proof or real data from a web page — travel prices, product "
            "reviews, restaurant menus, ticket availability, hotel listings, etc. "
            "Pass up to 5 URLs. Results arrive synchronously in the tool result."
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
        safe_slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

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

                    filename = f"{safe_slug}-{label}.png"
                    filepath = f"{_SCREENSHOTS_DIR}/{filename}"
                    img_url = f"{_SCREENSHOTS_URL}/{filename}"

                    content = ""
                    ok = False

                    logger.info("screenshot_pages: navigating to {} → {}", label, url)
                    try:
                    await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                    await _asyncio.sleep(wait_sec)
                    # Dismiss modal/popup dialogs (Booking.com sign-in, DuckDuckGo upgrade, etc.)
                    try:
                        await page.keyboard.press("Escape")
                        await _asyncio.sleep(0.3)
                    except Exception:
                        pass
                    try:
                        # JS fallback: hide overlay/modal/popup elements that obscure content
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

                    results.append({"label": label, "url": url, "img_url": img_url, "content": content, "ok": ok})

                await browser.close()

        except Exception as exc:
            logger.error("screenshot_pages: Playwright session failed: {}", exc)

        # Build structured return for the calling agent
        lines = [
            f"## screenshot_pages results for '{safe_slug}'\n",
            f"Captured {sum(1 for r in results if r['ok'])}/{len(results)} pages successfully.\n",
            "Use the image URLs and page content below. Embed the images in your response.\n",
            "\n### Image URLs\n",
        ]
        for r in results:
            status = "✅" if r["ok"] else "⚠️ failed"
            lines.append(f"- **{r['label']}** ({status}): {r['img_url']}\n")

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
            "Extract all relevant data (prices, names, availability, etc.) from the content "
            "above and include it in your response. Embed all images.\n"
        )

        return "".join(lines)
