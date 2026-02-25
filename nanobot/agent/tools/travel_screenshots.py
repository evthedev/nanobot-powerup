"""Travel screenshots tool — spawns a Playwright subagent to capture travel research screenshots."""

import os
import re
from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

_SCREENSHOTS_DIR = "/root/.nanobot/workspace/screenshots"
_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "http://localhost:3001/api/screenshots")


class TravelScreenshotsTool(Tool):
    """
    Capture Playwright screenshots of travel research pages (flights, hotels, event info)
    and post them as inline images in the chat.

    This tool spawns a subagent internally. Call it BEFORE writing the itinerary text
    so screenshots appear as a follow-up message while you compile the response.
    """

    def __init__(self, manager: "SubagentManager", screenshots_dir: str = _SCREENSHOTS_DIR):
        self._manager = manager
        self._screenshots_dir = screenshots_dir
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "travel_screenshots"

    @property
    def description(self) -> str:
        return (
            "Capture browser screenshots of travel research pages — flights, hotels, and event info — "
            "then post them as inline images. Call this during travel research BEFORE writing the itinerary. "
            "It spawns a background subagent that navigates to each URL, saves screenshots, and posts them."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trip_slug": {
                    "type": "string",
                    "description": (
                        "Lowercase hyphenated identifier for the trip, used as filename prefix. "
                        "Examples: 'bts-busan-jun26', 'paris-trip', 'tokyo-concert'."
                    ),
                },
                "flights_url": {
                    "type": "string",
                    "description": (
                        "URL of a flights search page. Use Skyscanner: "
                        "https://www.skyscanner.com.au/routes/syd/<destination-iata>/ "
                        "e.g. https://www.skyscanner.com.au/routes/syd/pus/ for Busan."
                    ),
                },
                "hotels_url": {
                    "type": "string",
                    "description": (
                        "URL of a hotel search page. Use Booking.com: "
                        "https://www.booking.com/searchresults.en-gb.html?ss=<city> "
                        "e.g. https://www.booking.com/searchresults.en-gb.html?ss=Busan"
                    ),
                },
                "event_url": {
                    "type": "string",
                    "description": (
                        "URL of the event info page — concert/festival page, Weverse, Ticketmaster, "
                        "or the top search result about the event. "
                        "Use https://weverse.io or https://bts.ibighit.com if no specific event page exists."
                    ),
                },
            },
            "required": ["trip_slug", "flights_url", "hotels_url", "event_url"],
        }

    async def execute(  # pylint: disable=arguments-differ
        self,
        trip_slug: str,
        flights_url: str,
        hotels_url: str,
        event_url: str,
        **kwargs: Any,
    ) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", trip_slug.lower()).strip("-")
        fl_file  = f"{self._screenshots_dir}/{slug}-flights.png"
        ht_file  = f"{self._screenshots_dir}/{slug}-hotels.png"
        ev_file  = f"{self._screenshots_dir}/{slug}-event.png"
        fl_img   = f"{_SCREENSHOTS_URL}/{slug}-flights.png"
        ht_img   = f"{_SCREENSHOTS_URL}/{slug}-hotels.png"
        ev_img   = f"{_SCREENSHOTS_URL}/{slug}-event.png"

        # Flight booking sites (Skyscanner, Kayak, etc.) block headless Chromium.
        # Use Brave Search results instead — reliable, no bot detection.
        def _to_brave(url: str, fallback_query: str) -> str:
            blocked = ("skyscanner", "kayak", "expedia", "google.com/travel",
                       "booking.com", "agoda", "airbnb", "hotels.com", "tripadvisor.com")
            if any(d in url.lower() for d in blocked):
                import urllib.parse  # noqa: PLC0415
                return "https://search.brave.com/search?q=" + urllib.parse.quote(fallback_query)
            return url

        safe_flights_url = _to_brave(flights_url, f"{slug} flights Sydney prices 2026")
        safe_hotels_url  = _to_brave(hotels_url,  f"{slug} hotels near venue rates 2026")

        script = (
            "import sys, time\n"
            "from playwright.sync_api import sync_playwright\n"
            f"urls = [{safe_flights_url!r}, {safe_hotels_url!r}, {event_url!r}]\n"
            f"files = [{fl_file!r}, {ht_file!r}, {ev_file!r}]\n"
            "_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '\n"
            "       'AppleWebKit/537.36 (KHTML, like Gecko) '\n"
            "       'Chrome/122.0.0.0 Safari/537.36')\n"
            "with sync_playwright() as p:\n"
            "    browser = p.chromium.launch(\n"
            "        headless=True,\n"
            "        args=['--disable-blink-features=AutomationControlled',\n"
            "              '--no-sandbox', '--disable-dev-shm-usage']\n"
            "    )\n"
            "    ctx = browser.new_context(\n"
            "        user_agent=_UA,\n"
            "        viewport={'width': 1280, 'height': 900},\n"
            "        locale='en-AU',\n"
            "    )\n"
            "    ctx.add_init_script('Object.defineProperty(navigator,\"webdriver\",{get:()=>undefined})')\n"
            "    page = ctx.new_page()\n"
            "    for url, path in zip(urls, files):\n"
            "        try:\n"
            "            page.goto(url, timeout=20000, wait_until='domcontentloaded')\n"
            "            time.sleep(4)\n"
            "            page.screenshot(path=path, full_page=False)\n"
            "            print(f'OK: {path}')\n"
            "        except Exception as e:\n"
            "            print(f'WARN: {url} -> {e}', file=sys.stderr)\n"
            "    browser.close()\n"
            "print('done')\n"
        )

        task = (
            f"Run the following Python script to capture travel research screenshots, "
            f"then post the images inline.\n\n"
            f"Step 1 — exec: mkdir -p {self._screenshots_dir}\n\n"
            f"Step 2 — Write this script to /tmp/travel_ss.py with write_file, then run it:\n"
            f"```python\n{script}```\n\n"
            f"exec(command=\"python3 /tmp/travel_ss.py\")\n\n"
            f"Step 3 — After the script succeeds, your ONLY output must be "
            f"exactly these three markdown image lines (no other text):\n\n"
            f"![Flights]({fl_img})\n\n"
            f"![Hotels]({ht_img})\n\n"
            f"![Event]({ev_img})\n\n"
            f"RULES:\n"
            f"- message content must contain ONLY those three markdown image lines\n"
            f"- DO NOT add explanation text or file paths\n"
        )

        result = await self._manager.spawn(
            task=task,
            label=f"travel-screenshots:{slug}",
            model=None,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
        return f"Travel screenshot subagent launched for '{slug}' (flights + hotels + event). {result}"
