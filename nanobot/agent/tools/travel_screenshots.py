"""Travel screenshots tool — captures live flight/hotel/ticket pages using direct Playwright.

Navigates sequentially (no subagent) to avoid concurrency issues. Returns extracted page
content and image URLs directly to the main agent so it can write a complete itinerary
with real prices in one pass — no placeholders, no follow-up subagent needed.
"""

import os
import re
import urllib.parse
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "http://localhost:3001/api/screenshots")
_SCREENSHOTS_DIR = os.path.expanduser("~/.nanobot/workspace/screenshots")


class TravelScreenshotsTool(Tool):
    """
    Navigates directly (via Playwright Python) to live flight, hotel and ticket pages,
    captures a screenshot of each, extracts visible text, and returns everything to the
    main agent so it can write a complete, price-filled itinerary immediately.
    """

    def __init__(self, manager=None, screenshots_dir: str = "", send_callback=None):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    def set_send_callback(self, callback) -> None:
        pass

    @property
    def name(self) -> str:
        return "travel_screenshots"

    @property
    def description(self) -> str:
        return (
            "Navigates to live flight search, hotel listings and ticket pages, captures a "
            "screenshot of each, and returns the extracted page content (with real prices) "
            "plus the image URLs — so you can write a complete, price-filled itinerary "
            "immediately. Call ONCE alongside web_search calls."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trip_slug": {
                    "type": "string",
                    "description": "Lowercase hyphenated trip ID, e.g. 'coldplay-tokyo-mar26'",
                },
                "destination_city": {
                    "type": "string",
                    "description": "Destination city name, e.g. 'Tokyo', 'London', 'Busan'",
                },
                "travel_date": {
                    "type": "string",
                    "description": "Main event date as a readable string, e.g. 'June 12 2026'",
                },
                "checkin": {
                    "type": "string",
                    "description": "Hotel check-in date YYYY-MM-DD. Improves hotel search accuracy.",
                },
                "checkout": {
                    "type": "string",
                    "description": "Hotel check-out date YYYY-MM-DD.",
                },
                "event_name": {
                    "type": "string",
                    "description": "Event/concert name, e.g. 'Coldplay Music of the Spheres Tour 2026'",
                },
                "venue_hint": {
                    "type": "string",
                    "description": "Venue name or area for hotel proximity, e.g. 'Tokyo Dome', 'BEXCO'. Leave empty if unknown.",
                    "default": "",
                },
                "origin_city": {
                    "type": "string",
                    "description": "Departure city. Default: Sydney",
                    "default": "Sydney",
                },
                "airlines": {
                    "type": "string",
                    "description": "Comma-separated preferred airlines for this route, e.g. 'JAL, ANA, Qantas'. Leave empty for cheapest.",
                    "default": "",
                },
                "budget_per_night": {
                    "type": "string",
                    "description": "Max hotel budget per night AUD, e.g. '$200'",
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
        checkin: str = "",
        checkout: str = "",
        venue_hint: str = "",
        origin_city: str = "Sydney",
        airlines: str = "",
        budget_per_night: str = "$200",
        flights_url: str = "",  # legacy
        hotels_url: str = "",   # legacy
        event_url: str = "",    # legacy
        **kwargs: Any,
    ) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", trip_slug.lower()).strip("-")
        venue_for_hotels = venue_hint or destination_city
        airlines_suffix = f" {airlines}" if airlines else ""

        # Flights: DuckDuckGo — loads without bot detection, returns Skyscanner/Kayak results.
        # Google/Bing/Expedia aggressively block Playwright with CAPTCHAs.
        flights_q = urllib.parse.quote(
            f"cheap return flights {origin_city} to {destination_city} {travel_date}"
            f"{airlines_suffix} price AUD"
        )
        flights_search = f"https://duckduckgo.com/?q={flights_q}&ia=web"

        # Hotels: Booking.com — loads fully in Playwright with real hotel names and prices.
        # Test confirmed 16k+ chars of hotel listing content loaded without bot detection.
        hotel_location = urllib.parse.quote(f"{venue_for_hotels}, {destination_city}")
        if checkin and checkout:
            hotels_search = (
                f"https://www.booking.com/searchresults.html"
                f"?ss={hotel_location}"
                f"&checkin={checkin}&checkout={checkout}"
                f"&group_adults=1&no_rooms=1&order=price"
            )
        else:
            hotels_search = (
                f"https://www.booking.com/searchresults.html"
                f"?ss={hotel_location}"
                f"&group_adults=1&no_rooms=1&order=price"
            )

        # Tickets: DuckDuckGo — returns Ticketmaster/Viagogo/StubHub links without blocking.
        tickets_q = urllib.parse.quote(f"{event_name} tickets {travel_date} buy")
        tickets_search = f"https://duckduckgo.com/?q={tickets_q}&ia=web"

        fl_file = f"{slug}-flights.png"
        ht_file = f"{slug}-hotels.png"
        tk_file = f"{slug}-tickets.png"
        fl_img = f"{_SCREENSHOTS_URL}/{fl_file}"
        ht_img = f"{_SCREENSHOTS_URL}/{ht_file}"
        tk_img = f"{_SCREENSHOTS_URL}/{tk_file}"

        fl_path = f"{_SCREENSHOTS_DIR}/{fl_file}"
        ht_path = f"{_SCREENSHOTS_DIR}/{ht_file}"
        tk_path = f"{_SCREENSHOTS_DIR}/{tk_file}"

        # Use direct Playwright Python (not MCP) so screenshots are guaranteed sequential.
        # MCP/subagent approach caused concurrency issues (shared browser, LLM batching).
        import asyncio
        from playwright.async_api import async_playwright

        logger.info("travel_screenshots: launching direct Playwright for '{}'", slug)

        os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

        fl_content = ""
        ht_content = ""
        tk_content = ""

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                page = await browser.new_page()

                # --- Flights ---
                logger.info("travel_screenshots: navigating to flights: {}", flights_search)
                try:
                    await page.goto(flights_search, timeout=20_000, wait_until="domcontentloaded")
                    await asyncio.sleep(5)
                    fl_content = (await page.inner_text("body"))[:4000]
                    await page.screenshot(path=fl_path, type="png", full_page=False)
                    logger.info("travel_screenshots: flights screenshot saved → {}", fl_path)
                except Exception as exc:
                    logger.warning("travel_screenshots: flights step failed: {}", exc)
                    try:
                        await page.screenshot(path=fl_path, type="png")
                    except Exception:
                        pass

                # --- Hotels ---
                logger.info("travel_screenshots: navigating to hotels: {}", hotels_search)
                try:
                    await page.goto(hotels_search, timeout=20_000, wait_until="domcontentloaded")
                    await asyncio.sleep(6)
                    ht_content = (await page.inner_text("body"))[:5000]
                    await page.screenshot(path=ht_path, type="png", full_page=False)
                    logger.info("travel_screenshots: hotels screenshot saved → {}", ht_path)
                except Exception as exc:
                    logger.warning("travel_screenshots: hotels step failed: {}", exc)
                    try:
                        await page.screenshot(path=ht_path, type="png")
                    except Exception:
                        pass

                # --- Tickets ---
                logger.info("travel_screenshots: navigating to tickets: {}", tickets_search)
                try:
                    await page.goto(tickets_search, timeout=20_000, wait_until="domcontentloaded")
                    await asyncio.sleep(4)
                    tk_content = (await page.inner_text("body"))[:3000]
                    await page.screenshot(path=tk_path, type="png", full_page=False)
                    logger.info("travel_screenshots: tickets screenshot saved → {}", tk_path)
                except Exception as exc:
                    logger.warning("travel_screenshots: tickets step failed: {}", exc)
                    try:
                        await page.screenshot(path=tk_path, type="png")
                    except Exception:
                        pass

                await browser.close()

        except Exception as exc:
            logger.error("travel_screenshots: Playwright session failed: {}", exc)

        # Return everything directly to the main agent — no subagent spawn needed.
        # The agent uses fl_content/ht_content/tk_content to fill in real prices immediately.
        ok_fl = "✅" if fl_content else "⚠️ no content"
        ok_ht = "✅" if ht_content else "⚠️ no content"
        ok_tk = "✅" if tk_content else "⚠️ no content"

        logger.info(
            "travel_screenshots: returning results to main agent — fl={} ht={} tk={}",
            ok_fl, ok_ht, ok_tk,
        )

        return (
            f"## travel_screenshots results for '{slug}'\n\n"
            f"Screenshots saved. Use the image URLs and page content below to write your "
            f"itinerary with REAL prices — do NOT use placeholders.\n\n"
            f"### Image URLs (embed these in your response)\n"
            f"- Flights:  {fl_img}\n"
            f"- Hotels:   {ht_img}\n"
            f"- Tickets:  {tk_img}\n\n"
            f"### FLIGHTS page content ({ok_fl})\n"
            f"Source: {flights_search}\n"
            f"```\n{fl_content or '(failed to load)'}\n```\n\n"
            f"### HOTELS page content ({ok_ht})\n"
            f"Source: {hotels_search}\n"
            f"```\n{ht_content or '(failed to load)'}\n```\n\n"
            f"### TICKETS page content ({ok_tk})\n"
            f"Source: {tickets_search}\n"
            f"```\n{tk_content or '(failed to load)'}\n```\n\n"
            f"Extract all prices, hotel names, and ticket options from the content above "
            f"and use them directly in your itinerary. Embed all three images.\n"
        )
