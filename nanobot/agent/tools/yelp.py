"""YelpSearchTool — business search via the Yelp Fusion API (requires API key)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

_API_BASE = "https://api.yelp.com/v3"
_PRICE_MAP = {"1": "$", "2": "$$", "3": "$$$", "4": "$$$$"}


class YelpSearchTool(Tool):
    """
    Search for local businesses using the Yelp Fusion API.

    Requires a Yelp API key set in config or the YELP_API_KEY environment variable.
    Get a free key at https://docs.developer.yelp.com/docs/fusion-intro
    (50 req/day on the free tier, 500 req/day on the basic tier).
    """

    name = "yelp_search"
    description = (
        "Search for local businesses on Yelp near a specific location. "
        "Use this when the user wants to find a place to eat, drink, or use a local service — "
        "e.g. 'find a good sushi place in Surry Hills', 'best bars near me in Sydney CBD', "
        "'where can I get a haircut in Newtown?', 'recommend a plumber in Bondi'. "
        "Returns ratings, review counts, price tier, address, opening status, and Yelp URL. "
        "Requires a Yelp API key in config (tools.yelp.api_key)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "term": {
                "type": "string",
                "description": "Search term (e.g. 'sushi restaurants', 'plumber', 'yoga studio')",
            },
            "location": {
                "type": "string",
                "description": "City, suburb, or address (e.g. 'Sydney NSW', '2000', 'Surry Hills')",
            },
            "latitude": {
                "type": "number",
                "description": "Latitude for geo-based search (use instead of location)",
            },
            "longitude": {
                "type": "number",
                "description": "Longitude for geo-based search (use instead of location)",
            },
            "categories": {
                "type": "string",
                "description": "Yelp category filter (e.g. 'restaurants', 'bars', 'health'). See Yelp category list.",
            },
            "sort_by": {
                "type": "string",
                "enum": ["best_match", "rating", "review_count", "distance"],
                "description": "Sort order (default: best_match)",
            },
            "price": {
                "type": "string",
                "description": "Price filter: '1' ($), '2' ($$), '3' ($$$), '4' ($$$$). Comma-separated for multiple.",
            },
            "open_now": {
                "type": "boolean",
                "description": "Only return businesses currently open (default: false)",
            },
            "radius": {
                "type": "integer",
                "description": "Search radius in metres (max 40000, default: 5000)",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results (1-20, default: 10)",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["term"],
    }

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("YELP_API_KEY", "")

    async def execute(
        self,
        term: str,
        location: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        categories: str | None = None,
        sort_by: str = "best_match",
        price: str | None = None,
        open_now: bool = False,
        radius: int = 5000,
        limit: int = 10,
        **kwargs: Any,
    ) -> str:
        if not self.api_key:
            return (
                "Error: Yelp API key not configured. "
                "Get a free key at https://docs.developer.yelp.com/docs/fusion-intro "
                "then add it to config.json under tools.yelp.apiKey or set YELP_API_KEY."
            )

        if not location and not (latitude and longitude):
            return "Error: Provide either 'location' (city/address) or 'latitude' + 'longitude'."

        limit = max(1, min(limit, 20))
        radius = max(100, min(radius, 40000))
        sort_by = sort_by if sort_by in {"best_match", "rating", "review_count", "distance"} else "best_match"

        params: dict[str, Any] = {
            "term": term,
            "limit": limit,
            "sort_by": sort_by,
            "radius": radius,
        }
        if location:
            params["location"] = location
        if latitude and longitude:
            params["latitude"] = latitude
            params["longitude"] = longitude
        if categories:
            params["categories"] = categories
        if price:
            params["price"] = price
        if open_now:
            params["open_now"] = True

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{_API_BASE}/businesses/search",
                    params=params,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if r.status_code == 401:
                    return "Error: Invalid Yelp API key."
                if r.status_code == 400:
                    detail = r.json().get("error", {}).get("description", r.text[:200])
                    return f"Error: Bad request — {detail}"
                r.raise_for_status()

            businesses = r.json().get("businesses", [])
            if not businesses:
                return f"No Yelp results for '{term}'" + (f" near {location}" if location else "")

            loc_str = location or f"{latitude:.4f},{longitude:.4f}"
            lines = [f"Yelp results for \"{term}\" near {loc_str}:\n"]

            for i, biz in enumerate(businesses, 1):
                name       = biz.get("name", "")
                rating     = biz.get("rating", 0)
                n_reviews  = biz.get("review_count", 0)
                price_tier = _PRICE_MAP.get(str(biz.get("price", "")), biz.get("price", ""))
                is_closed  = biz.get("is_closed", False)
                url        = biz.get("url", "").split("?")[0]
                distance_m = biz.get("distance", 0)
                distance_s = f"{distance_m / 1000:.1f}km" if distance_m else ""
                addr_parts = biz.get("location", {}).get("display_address", [])
                address    = ", ".join(addr_parts)
                cats       = ", ".join(c.get("title", "") for c in biz.get("categories", []))
                status     = "🔴 Closed" if is_closed else "🟢 Open"

                lines.append(
                    f"{i}. {name} {price_tier}\n"
                    f"   ⭐ {rating}/5  |  {n_reviews:,} reviews  |  {distance_s}  |  {status}\n"
                    f"   {cats}\n"
                    f"   {address}\n"
                    f"   {url}"
                )

            return "\n".join(lines)

        except httpx.HTTPStatusError as e:
            return f"Error: Yelp API returned HTTP {e.response.status_code}"
        except Exception as e:
            return f"Error: {e}"
