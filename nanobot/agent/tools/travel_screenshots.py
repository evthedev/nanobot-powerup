"""Travel screenshots tool — spawns a subagent with Playwright MCP tools to:
1. Navigate to live booking sites using a single run_code call (bypasses multi-step sequencing issues)
2. Screenshot each page at the right moment
3. Extract real prices via page.innerText
4. Post screenshots + extracted prices back to the main agent"""

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
    Spawns a Playwright subagent that uses a single run_code call to navigate
    to live booking sites, extract real prices, and screenshot each page at the
    right moment. Extracts prices and posts screenshots as follow-up messages.
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
            "Spawns a Playwright subagent that navigates to live flight, hotel and ticket pages, "
            "captures screenshots as visual proof, and extracts real prices. "
            "Screenshots and prices arrive as a follow-up message. "
            "Write the itinerary structure now — a follow-up with real prices will arrive shortly."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trip_slug": {
                    "type": "string",
                    "description": "Lowercase hyphenated trip ID, e.g. 'bts-busan-jun26'",
                },
                "destination_city": {
                    "type": "string",
                    "description": "Destination city, e.g. 'Busan', 'Tokyo'",
                },
                "travel_date": {
                    "type": "string",
                    "description": "Concert/event date, e.g. 'June 12 2026'",
                },
                "checkin": {
                    "type": "string",
                    "description": "Hotel check-in YYYY-MM-DD, e.g. '2026-06-10'",
                },
                "checkout": {
                    "type": "string",
                    "description": "Hotel check-out YYYY-MM-DD, e.g. '2026-06-14'",
                },
                "event_name": {
                    "type": "string",
                    "description": "Event for ticket search, e.g. 'BTS World Tour 2026'",
                },
                "origin_city": {
                    "type": "string",
                    "description": "Departure city, default: Sydney",
                    "default": "Sydney",
                },
                "budget_per_night": {
                    "type": "string",
                    "description": "Max hotel budget, e.g. '$200'",
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
        origin_city: str = "Sydney",
        budget_per_night: str = "$200",
        flights_url: str = "",  # legacy
        hotels_url: str = "",   # legacy
        event_url: str = "",    # legacy
        **kwargs: Any,
    ) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", trip_slug.lower()).strip("-")

        flights_q = urllib.parse.quote(
            f"return flights {origin_city} to {destination_city} {travel_date} price AUD"
        )
        flights_url_built = f"https://www.google.com/search?q={flights_q}&gl=au&hl=en"

        if checkin and checkout:
            hotels_url_built = (
                f"https://www.booking.com/searchresults.html"
                f"?ss={urllib.parse.quote(destination_city)}"
                f"&checkin={checkin}&checkout={checkout}"
                f"&group_adults=1&nflt=price_usd-max%3D200&order=price"
            )
        else:
            hotels_q = urllib.parse.quote(
                f"hotels {destination_city} {travel_date} under {budget_per_night} per night near venue"
            )
            hotels_url_built = f"https://www.google.com/search?q={hotels_q}&gl=au&hl=en"

        tickets_q = urllib.parse.quote(f"{event_name} tickets buy official {travel_date}")
        tickets_url_built = f"https://www.google.com/search?q={tickets_q}&gl=au&hl=en"

        fl_path = f"{_SCREENSHOTS_DIR}/{slug}-flights.png"
        ht_path = f"{_SCREENSHOTS_DIR}/{slug}-hotels.png"
        tk_path = f"{_SCREENSHOTS_DIR}/{slug}-tickets.png"
        fl_img = f"{_SCREENSHOTS_URL}/{slug}-flights.png"
        ht_img = f"{_SCREENSHOTS_URL}/{slug}-hotels.png"
        tk_img = f"{_SCREENSHOTS_URL}/{slug}-tickets.png"

        # Single run_code JS function: handles navigate + screenshot + text extraction
        # This avoids multi-step LLM coordination which fails at high context
        js_code = (
            f"async (page) => {{\n"
            f"  const results = {{}};\n"
            f"\n"
            f"  // === FLIGHTS ===\n"
            f"  await page.goto('{flights_url_built}', {{waitUntil: 'domcontentloaded'}});\n"
            f"  await page.waitForTimeout(4000);\n"
            f"  await page.screenshot({{path: '{fl_path}'}});\n"
            f"  results.flights = (await page.innerText('body')).slice(0, 2000);\n"
            f"\n"
            f"  // === HOTELS ===\n"
            f"  await page.goto('{hotels_url_built}', {{waitUntil: 'domcontentloaded'}});\n"
            f"  await page.waitForTimeout(5000);\n"
            f"  await page.screenshot({{path: '{ht_path}'}});\n"
            f"  results.hotels = (await page.innerText('body')).slice(0, 2000);\n"
            f"\n"
            f"  // === TICKETS ===\n"
            f"  await page.goto('{tickets_url_built}', {{waitUntil: 'domcontentloaded'}});\n"
            f"  await page.waitForTimeout(4000);\n"
            f"  await page.screenshot({{path: '{tk_path}'}});\n"
            f"  results.tickets = (await page.innerText('body')).slice(0, 2000);\n"
            f"\n"
            f"  return results;\n"
            f"}}"
        )

        task = f"""You are a travel price assistant. Use ONE tool call to capture 3 screenshots and extract real prices.

## YOUR ONLY JOB: Call mcp_playwright_browser_run_code with this exact function

```javascript
{js_code}
```

The function will:
1. Navigate to flights page → screenshot → extract price text
2. Navigate to hotels page → screenshot → extract price text
3. Navigate to tickets page → screenshot → extract price text
4. Return all extracted text

## AFTER getting the result from run_code, call `message` tool with:

```
![Flights — {origin_city} → {destination_city}]({fl_img})

![Hotels — {destination_city}]({ht_img})

![Tickets — {event_name}]({tk_img})

---
**Real prices from live browser:**

✈️ FLIGHTS ({origin_city} → {destination_city}, {travel_date}):
[list every airline and price you saw in the flights text]

🏨 HOTELS ({destination_city} {checkin or travel_date}–{checkout}):
[list every hotel name and price you saw in the hotels text]

🎫 TICKETS ({event_name}):
[list ticket prices and where to buy from the tickets text]
```

RULES:
- Call run_code FIRST — this takes all 3 screenshots atomically
- Then call message ONCE with the 3 images + price data from the run_code result
- Only 2 tool calls total
"""

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
            f"Will capture 3 screenshots and extract real prices — arriving shortly as follow-up. "
            f"Write your complete itinerary structure now. "
            f"{result}"
        )
