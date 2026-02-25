"""Travel screenshots tool — runs Playwright directly (no LLM subagent) to capture
real flight, hotel and ticket search results from live booking sites."""

import asyncio
import os
import re
import urllib.parse
from typing import Any, Callable, Awaitable, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

_SCREENSHOTS_DIR = os.path.expanduser("~/.nanobot/workspace/screenshots")
_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "http://localhost:3001/api/screenshots")

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class TravelScreenshotsTool(Tool):
    """
    Capture real screenshots of flight prices, hotel availability and event tickets
    by directly driving a Playwright browser — no LLM subagent involved.

    Uses Google Search result pages which render inline flight/hotel/ticket widgets
    with real prices. Results are saved and posted as inline images.

    Call this in the SAME round as your first web_searches (runs in background).
    """

    def __init__(
        self,
        manager: "SubagentManager",
        screenshots_dir: str = _SCREENSHOTS_DIR,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    ):
        self._manager = manager
        self._screenshots_dir = screenshots_dir
        self._send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = send_callback
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "travel_screenshots"

    @property
    def description(self) -> str:
        return (
            "Capture live screenshots of real flight prices, hotels and ticket availability "
            "from booking sites. Runs Playwright directly — no subagent needed. "
            "Call this BEFORE writing the itinerary text so screenshots post as a follow-up."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trip_slug": {
                    "type": "string",
                    "description": "Lowercase hyphenated trip ID. e.g. 'bts-busan-mar26'",
                },
                "origin_city": {
                    "type": "string",
                    "description": "Departure city. Default: Sydney",
                    "default": "Sydney",
                },
                "destination_city": {
                    "type": "string",
                    "description": "Destination city. e.g. 'Busan', 'Tokyo', 'Paris'",
                },
                "travel_date": {
                    "type": "string",
                    "description": "Concert/event date or travel period. e.g. 'March 21 2026' or 'March 2026'",
                },
                "event_name": {
                    "type": "string",
                    "description": "Event name for ticket search. e.g. 'BTS World Tour 2026', 'Coldplay Tokyo 2026'",
                },
                "budget_per_night": {
                    "type": "string",
                    "description": "Max hotel budget. e.g. '$200' — used to filter hotel search",
                    "default": "$200",
                },
            },
            "required": ["trip_slug", "destination_city", "travel_date", "event_name"],
        }

    async def execute(  # pylint: disable=arguments-differ
        self,
        trip_slug: str,
        destination_city: str,
        travel_date: str,
        event_name: str,
        origin_city: str = "Sydney",
        budget_per_night: str = "$200",
        # Legacy params — accepted but ignored (backwards compat with auto-inject)
        flights_url: str = "",
        hotels_url: str = "",
        event_url: str = "",
        **kwargs: Any,
    ) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", trip_slug.lower()).strip("-")
        os.makedirs(self._screenshots_dir, exist_ok=True)

        fl_file = f"{self._screenshots_dir}/{slug}-flights.png"
        ht_file = f"{self._screenshots_dir}/{slug}-hotels.png"
        tk_file = f"{self._screenshots_dir}/{slug}-tickets.png"
        fl_img  = f"{_SCREENSHOTS_URL}/{slug}-flights.png"
        ht_img  = f"{_SCREENSHOTS_URL}/{slug}-hotels.png"
        tk_img  = f"{_SCREENSHOTS_URL}/{slug}-tickets.png"

        # Build Google Search URLs — inline widgets show real prices without bot-blocking
        flights_q = urllib.parse.quote(
            f"return flights {origin_city} to {destination_city} {travel_date} "
            f"price AUD Korean Air Asiana"
        )
        hotels_q = urllib.parse.quote(
            f"hotels {destination_city} {travel_date} under {budget_per_night} per night near venue"
        )
        tickets_q = urllib.parse.quote(
            f"{event_name} tickets buy official {travel_date}"
        )

        urls = [
            (f"https://www.google.com/search?q={flights_q}&gl=au&hl=en", fl_file, "flights"),
            (f"https://www.google.com/search?q={hotels_q}&gl=au&hl=en",  ht_file, "hotels"),
            (f"https://www.google.com/search?q={tickets_q}&gl=au&hl=en", tk_file, "tickets"),
        ]

        results: list[str] = []
        errors: list[str] = []

        # Run Playwright directly — no LLM subagent
        asyncio.get_event_loop()  # ensure loop exists
        await self._capture_screenshots(urls, results, errors)

        if errors:
            logger.warning("travel_screenshots partial errors: {}", errors)

        # Post images directly via message bus
        img_md = (
            f"![Flights — {origin_city} → {destination_city}]({fl_img})\n\n"
            f"![Hotels — {destination_city} {budget_per_night}/night]({ht_img})\n\n"
            f"![Tickets — {event_name}]({tk_img})"
        )
        if self._send_callback:
            await self._send_callback(OutboundMessage(
                channel=self._origin_channel,
                chat_id=self._origin_chat_id,
                content=img_md,
            ))
            logger.info("travel_screenshots: posted 3 images for '{}'", slug)
            return f"Screenshots captured and posted for '{slug}': flights, hotels, tickets."
        else:
            return f"Screenshots saved for '{slug}'.\n\n{img_md}"

    async def _capture_screenshots(
        self,
        urls: list[tuple[str, str, str]],
        results: list[str],
        errors: list[str],
    ) -> None:
        """Drive Playwright directly to capture each page."""
        import asyncio as _asyncio
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            ctx = await browser.new_context(
                user_agent=_UA,
                viewport={"width": 1280, "height": 900},
                locale="en-AU",
                timezone_id="Australia/Sydney",
            )
            await ctx.add_init_script(
                'Object.defineProperty(navigator,"webdriver",{get:()=>undefined})'
            )
            page = await ctx.new_page()

            for url, path, label in urls:
                try:
                    logger.info("travel_screenshots: capturing {} → {}", label, url[:80])
                    await page.goto(url, timeout=25000, wait_until="domcontentloaded")

                    # Wait for Google's inline result widgets to render
                    if "google.com/search" in url:
                        # Try to wait for rich result cards (flights/hotels/events widget)
                        for selector in [
                            "[data-md]",          # Google inline widgets
                            ".kp-blk",            # Knowledge panel
                            ".g",                 # Standard search result
                        ]:
                            try:
                                await page.wait_for_selector(selector, timeout=5000)
                                break
                            except Exception:
                                pass

                    await _asyncio.sleep(3)
                    await page.screenshot(path=path, full_page=False)
                    results.append(label)
                    logger.info("travel_screenshots: {} OK → {}", label, path)
                except Exception as exc:
                    errors.append(f"{label}: {exc}")
                    logger.warning("travel_screenshots: {} failed: {}", label, exc)

            await browser.close()
