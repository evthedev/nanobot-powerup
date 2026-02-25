"""Review screenshots tool — spawns a Playwright subagent to capture review page screenshots."""

import os
import re
from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

_SCREENSHOTS_DIR = "/root/.nanobot/workspace/screenshots"
# Allow override for local dev (http://localhost:3001) vs Docker (relative via nginx)
_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "http://localhost:3001/api/screenshots")


class ReviewScreenshotsTool(Tool):
    """
    Capture Playwright screenshots of a product's Reddit, Trustpilot, and editorial
    review pages, then post all of them as inline images in the chat.

    This tool spawns a subagent internally — you do not need to call spawn separately.
    Call this tool BEFORE producing your text response so the screenshots appear
    as a follow-up message while you write the review.
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
        return "review_screenshots"

    @property
    def description(self) -> str:
        return (
            "Capture browser screenshots of a product's Reddit discussion, Trustpilot page, "
            "and top editorial review, then post all three as inline images. "
            "Call this during the review workflow BEFORE writing the review text. "
            "It launches a background subagent that navigates to each URL, saves screenshots, "
            "and posts them in the chat."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "company_slug": {
                    "type": "string",
                    "description": (
                        "Lowercase hyphenated identifier for the company, used as the filename prefix. "
                        "Examples: 'notion', 'monday-com', 'atlassian', 'figma', 'linear-app'."
                    ),
                },
                "reddit_url": {
                    "type": "string",
                    "description": (
                        "URL of the most relevant Reddit thread or search results page from Step 1. "
                        "Use the permalink of the top Reddit post, or "
                        "https://www.reddit.com/search/?q=<company>+review if no specific post was found."
                    ),
                },
                "trustpilot_url": {
                    "type": "string",
                    "description": (
                        "Full Trustpilot review URL for the company. "
                        "Format: https://www.trustpilot.com/review/<domain> "
                        "(e.g. https://www.trustpilot.com/review/notion.so). "
                        "Use this even if trustpilot_search returned no results — the page may still exist."
                    ),
                },
                "editorial_url": {
                    "type": "string",
                    "description": (
                        "URL of the best editorial or blog review fetched in Step 3 "
                        "(e.g. a Forbes, PCMag, G2, or KDNuggets review page)."
                    ),
                },
            },
            "required": ["company_slug", "reddit_url", "trustpilot_url", "editorial_url"],
        }

    async def execute(
        self,
        company_slug: str,
        reddit_url: str,
        trustpilot_url: str,
        editorial_url: str,
        **kwargs: Any,
    ) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", company_slug.lower()).strip("-")
        rd_file  = f"{self._screenshots_dir}/{slug}-reddit.png"
        tp_file  = f"{self._screenshots_dir}/{slug}-trustpilot.png"
        rev_file = f"{self._screenshots_dir}/{slug}-review.png"
        rd_img   = f"{_SCREENSHOTS_URL}/{slug}-reddit.png"
        tp_img   = f"{_SCREENSHOTS_URL}/{slug}-trustpilot.png"
        rev_img  = f"{_SCREENSHOTS_URL}/{slug}-review.png"

        # Use old.reddit.com — avoids the aggressive anti-bot blocking on www.reddit.com.
        safe_reddit_url = reddit_url.replace("www.reddit.com", "old.reddit.com")

        # Derive a clean search query for Brave Search (company name from slug).
        search_query = company_slug.replace("-", " ")
        brave_url = f"https://search.brave.com/search?q={search_query}+review+pros+cons"

        # Build a Python script that captures all 3 screenshots sequentially in one exec call.
        # This avoids the LLM batching multiple browser_navigate calls and losing page context.
        # For the editorial screenshot we use Brave Search — Cloudflare blocks direct navigation
        # to most editorial sites in headless mode, but Brave Search is always accessible.
        script = (
            "import sys, time\n"
            "from playwright.sync_api import sync_playwright\n"
            f"urls = [{safe_reddit_url!r}, {trustpilot_url!r}, {brave_url!r}]\n"
            f"files = [{rd_file!r}, {tp_file!r}, {rev_file!r}]\n"
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
            f"Run the following Python script to capture review screenshots, "
            f"then post the images inline.\n\n"
            f"Step 1 — Run this exact script:\n"
            f"```python\n{script}```\n\n"
            f"Use exec to run it: exec(command=\"python3 -c '<script>'\")\n"
            f"Or write it to a temp file first with write_file and run with exec.\n\n"
            f"Step 2 — After the script succeeds, your ONLY output must be "
            f"exactly these three markdown image lines (no other text):\n\n"
            f"![Reddit]({rd_img})\n\n"
            f"![Trustpilot]({tp_img})\n\n"
            f"![Web reviews]({rev_img})\n\n"
            f"RULES:\n"
            f"- Do NOT use mcp_playwright tools — use exec + Python script only\n"
            f"- message content must contain ONLY those three markdown image lines\n"
            f"- DO NOT list file paths or add explanation text\n"
        )

        result = await self._manager.spawn(
            task=task,
            label=f"screenshots:{slug}",
            model=None,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
        return f"Screenshot subagent launched for '{slug}' (reddit + trustpilot + editorial). {result}"
