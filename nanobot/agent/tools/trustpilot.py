"""TrustpilotSearchTool — search businesses and fetch reviews via public Trustpilot pages."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
_BASE = "https://www.trustpilot.com"

_STAR_LABELS = {1: "Bad", 2: "Poor", 3: "Average", 4: "Good", 5: "Excellent"}


def _next_data(html: str) -> dict:
    """Extract the __NEXT_DATA__ JSON payload embedded in Trustpilot pages."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


class TrustpilotSearchTool(Tool):
    """
    Search Trustpilot for businesses by name, then optionally pull recent reviews.
    Uses Trustpilot's public website (no API key required).
    """

    name = "trustpilot_search"
    description = (
        "Search Trustpilot for businesses and check their reputation and customer satisfaction. "
        "Use this when the user wants to know if a company is trustworthy, legitimate, or has good customer service — "
        "e.g. 'is X a good company?', 'are they reliable?', 'what is the reputation of Y?', "
        "'should I use Z?', or any question about a business's track record with real customers. "
        "Returns verified trust scores, review counts, categories, and optionally real recent reviews. "
        "No API key required."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Business name or domain (e.g. 'airbnb' or 'airbnb.com')",
            },
            "include_reviews": {
                "type": "boolean",
                "description": "Also fetch recent English reviews for the top result (default: false)",
            },
            "review_count": {
                "type": "integer",
                "description": "How many reviews to return (1-10, default: 5). Only used when include_reviews is true.",
                "minimum": 1,
                "maximum": 10,
            },
            "limit": {
                "type": "integer",
                "description": "Max business results to return (1-10, default: 5)",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        include_reviews: bool = False,
        review_count: int = 5,
        limit: int = 5,
        **kwargs: Any,
    ) -> str:
        limit = max(1, min(limit, 10))
        review_count = max(1, min(review_count, 10))

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            # ── 1. Search for businesses ──────────────────────────────────────
            try:
                resp = await client.get(
                    f"{_BASE}/search",
                    params={"query": query},
                    headers={"User-Agent": _UA},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                return f"Error: Trustpilot returned HTTP {e.response.status_code}"
            except Exception as e:
                return f"Error fetching Trustpilot search: {e}"

            page_data = _next_data(resp.text)
            props = page_data.get("props", {}).get("pageProps", {})
            units = props.get("businessUnits", [])

            if not units:
                return f"No Trustpilot results for: {query}"

            lines = [f"Trustpilot results for \"{query}\":\n"]
            for i, u in enumerate(units[:limit], 1):
                name    = u.get("displayName", "")
                domain  = u.get("identifyingName", "")
                score   = u.get("trustScore", 0)
                stars   = u.get("stars", 0)
                n_rev   = u.get("numberOfReviews", 0)
                country = (u.get("location") or {}).get("country", "")
                cats    = ", ".join(c.get("displayName", "") for c in u.get("categories", []))
                label   = _STAR_LABELS.get(round(stars), "")
                url     = f"{_BASE}/review/{domain}"

                lines.append(
                    f"{i}. {name} ({domain})\n"
                    f"   ⭐ {score}/5 — {label}  |  {n_rev:,} reviews  |  {country}\n"
                    f"   Categories: {cats or 'n/a'}\n"
                    f"   {url}"
                )

            # ── 2. Optional: pull reviews for the top result ──────────────────
            if include_reviews and units:
                top_domain = units[0].get("identifyingName", "")
                if top_domain:
                    lines.append(f"\n--- Recent reviews for {top_domain} ---\n")
                    try:
                        rev_resp = await client.get(
                            f"{_BASE}/review/{top_domain}",
                            params={"languages": "en"},
                            headers={"User-Agent": _UA},
                        )
                        rev_resp.raise_for_status()
                        rev_data = _next_data(rev_resp.text)
                        reviews  = rev_data.get("props", {}).get("pageProps", {}).get("reviews", [])

                        if not reviews:
                            lines.append("No recent reviews found.")
                        else:
                            for j, rv in enumerate(reviews[:review_count], 1):
                                rating = rv.get("rating", 0)
                                title  = rv.get("title", "").strip()
                                text   = (rv.get("text") or "").strip()
                                author = (rv.get("consumer") or {}).get("displayName", "Anonymous")
                                date   = (rv.get("dates") or {}).get("publishedDate", "")[:10]
                                snippet = (text[:250] + "…") if len(text) > 250 else text

                                lines.append(
                                    f"{j}. [{rating}★] {title}\n"
                                    f"   {author} — {date}\n"
                                    f"   {snippet}"
                                )
                    except Exception as e:
                        lines.append(f"Could not load reviews: {e}")

            return "\n".join(lines)
