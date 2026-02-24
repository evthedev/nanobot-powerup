"""RedditSearchTool — search Reddit posts via the public JSON API (no API key needed)."""

from __future__ import annotations

from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

_USER_AGENT = "nanobot/1.0 (personal assistant)"
_BASE = "https://www.reddit.com"


class RedditSearchTool(Tool):
    """
    Search Reddit posts using the public reddit.com JSON API.
    No API key required — uses the unauthenticated endpoint.
    """

    name = "reddit_search"
    description = (
        "Search Reddit for posts matching a query. "
        "Use this when the user wants community opinions, anecdotes, real-world experiences, "
        "recommendations from locals, or niche/hobby discussions — e.g. 'what do people think about X', "
        "'best Y in Sydney according to Reddit', 'is Z worth it', or any question where lived experience "
        "matters more than official sources. "
        "Optionally filter by subreddit, sort order (relevance/hot/new/top/comments), and time window. "
        "Returns post titles, scores, comment counts, URLs, and body snippets."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search terms",
            },
            "subreddit": {
                "type": "string",
                "description": "Restrict to a specific subreddit (omit 'r/'). Leave empty for all of Reddit.",
            },
            "sort": {
                "type": "string",
                "enum": ["relevance", "hot", "new", "top", "comments"],
                "description": "Sort order (default: relevance)",
            },
            "time": {
                "type": "string",
                "enum": ["hour", "day", "week", "month", "year", "all"],
                "description": "Time window for 'top'/'relevance' sorts (default: all)",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results (1-25, default: 10)",
                "minimum": 1,
                "maximum": 25,
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        subreddit: str | None = None,
        sort: str = "relevance",
        time: str = "all",
        limit: int = 10,
        **kwargs: Any,
    ) -> str:
        limit = max(1, min(limit, 25))
        sort = sort if sort in {"relevance", "hot", "new", "top", "comments"} else "relevance"
        time = time if time in {"hour", "day", "week", "month", "year", "all"} else "all"

        if subreddit:
            url = f"{_BASE}/r/{subreddit.lstrip('r/').strip()}/search.json"
            params: dict[str, Any] = {
                "q": query, "restrict_sr": 1, "sort": sort,
                "t": time, "limit": limit,
            }
        else:
            url = f"{_BASE}/search.json"
            params = {"q": query, "sort": sort, "t": time, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": _USER_AGENT},
                    follow_redirects=True,
                )
                r.raise_for_status()

            posts = r.json().get("data", {}).get("children", [])
            if not posts:
                return f"No Reddit results for: {query}"

            lines = [f"Reddit results for \"{query}\"" +
                     (f" in r/{subreddit}" if subreddit else "") + ":\n"]

            for i, child in enumerate(posts[:limit], 1):
                p = child.get("data", {})
                title    = p.get("title", "")
                score    = p.get("score", 0)
                comments = p.get("num_comments", 0)
                sub      = p.get("subreddit", "")
                permalink= f"{_BASE}{p.get('permalink', '')}"
                selftext = (p.get("selftext") or "").strip()
                snippet  = (selftext[:200] + "…") if len(selftext) > 200 else selftext

                lines.append(
                    f"{i}. [{sub}] {title}\n"
                    f"   ↑{score:,}  💬{comments:,}  {permalink}"
                )
                if snippet:
                    lines.append(f"   {snippet}")

            return "\n".join(lines)

        except httpx.HTTPStatusError as e:
            return f"Error: Reddit returned HTTP {e.response.status_code}"
        except Exception as e:
            return f"Error: {e}"
