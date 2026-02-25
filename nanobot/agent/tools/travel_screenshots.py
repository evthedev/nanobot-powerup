"""Travel screenshots tool — spawns a subagent with Playwright MCP tools.

Uses individual MCP navigate/wait/screenshot tools with strict sequential
instructions to prevent the LLM from batching all navigations together
(which would result in all screenshots showing the last page only).

Key design: numbered pages, explicit CHECKPOINT markers, and "one tool at a time"
instructions force true sequential execution.
"""

import os
import re
import urllib.parse
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "http://localhost:3001/api/screenshots")
_SCREENSHOTS_DIR = os.path.expanduser("~/.nanobot/workspace/screenshots")


class TravelScreenshotsTool(Tool):
    """
    Spawns a Playwright subagent that captures screenshots of live flight, hotel
    and ticket pages as visual proof, and extracts real prices for the itinerary.

    Each page is screenshotted individually before moving to the next.
    """

    def __init__(self, manager: "SubagentManager", screenshots_dir: str = "", send_callback=None):
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
            "Spawns a Playwright subagent that navigates to live flight search, hotel listings "
            "and ticket pages, captures a screenshot of each, and extracts real prices. "
            "Screenshots + prices arrive as a follow-up message. "
            "Write the itinerary now using web_search results — follow-up fills in live prices."
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

        task = (
            f"You are a browser automation agent. Your ONLY job is to take 3 screenshots, "
            f"read the prices, and call `message`. Nothing else.\n\n"
            f"🚫 BANNED ACTIONS (never call these, ever):\n"
            f"- mcp_playwright_browser_install\n"
            f"- Any action not in the numbered list below\n\n"
            f"⚠️ ERROR RULE: If any navigate call shows a captcha, error page, or blank page — "
            f"take the screenshot ANYWAY (it documents what happened) and continue to the next step. "
            f"Never loop. Never retry a step. Execute each step exactly once.\n\n"
            f"⚠️ SEQUENCING RULE: After each tool call completes, IMMEDIATELY call the next step. "
            f"Do NOT produce any text between steps 1–11. "
            f"The ONLY allowed text output is the final `message` call at step 12.\n\n"
            f"Execute EXACTLY these steps in order:\n\n"
            f"STEP 1: mcp_playwright_browser_navigate url=\"{flights_search}\"\n"
            f"STEP 2: mcp_playwright_browser_wait_for time=5\n"
            f"STEP 3: mcp_playwright_browser_take_screenshot filename=\"{fl_path}\"\n"
            f"STEP 4: mcp_playwright_browser_navigate url=\"{hotels_search}\"\n"
            f"STEP 5: mcp_playwright_browser_wait_for time=5\n"
            f"STEP 6: mcp_playwright_browser_take_screenshot filename=\"{ht_path}\"\n"
            f"STEP 7: mcp_playwright_browser_navigate url=\"{tickets_search}\"\n"
            f"STEP 8: mcp_playwright_browser_wait_for time=4\n"
            f"STEP 9: mcp_playwright_browser_take_screenshot filename=\"{tk_path}\"\n"
            f"STEP 10: mcp_playwright_browser_snapshot\n"
            f"STEP 11: mcp_playwright_browser_navigate url=\"{hotels_search}\"\n"
            f"STEP 12: mcp_playwright_browser_snapshot\n\n"
            f"After step 12, call `message` with EXACTLY this format "
            f"(fill in real data extracted from the snapshots — no TBD, no placeholders):\n\n"
            f"```\n"
            f"![Flights — {origin_city} → {destination_city}]({fl_img})\n\n"
            f"![Hotels — {destination_city}]({ht_img})\n\n"
            f"![Tickets — {event_name}]({tk_img})\n\n"
            f"---\n"
            f"**Real prices from live browser:**\n\n"
            f"✈️ FLIGHTS ({origin_city} → {destination_city}, {travel_date}):\n"
            f"[List actual airlines and prices from the flights screenshot/snapshot]\n\n"
            f"🏨 HOTELS (near {venue_for_hotels}, {destination_city}):\n"
            f"[List actual hotel names and prices per night from the hotels snapshot]\n\n"
            f"🎫 TICKETS ({event_name}):\n"
            f"[List actual ticket prices, sections/categories, and purchase URLs from the tickets snapshot]\n"
            f"```\n"
        )

        logger.info("travel_screenshots: spawning Playwright subagent for '{}'", slug)
        result = await self._manager.spawn(
            task=task,
            label=f"travel-screenshots:{slug}",
            model=None,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
        return (
            f"Playwright subagent launched for '{slug}'. "
            f"Will navigate to live booking pages one at a time, extract prices and post 3 screenshots. "
            f"Write your complete itinerary now using web_search results for hotel names and activities. "
            f"{result}"
        )
