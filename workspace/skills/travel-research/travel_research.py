#!/usr/bin/env python3
"""
Travel Research Skill — Enhanced with Screenshot Capture
Researches travel plans including flights, accommodation, and itineraries.
Captures screenshots of booking sites, flight search tools, and info sources.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

SCREENSHOTS_DIR = Path("/Users/ev/.nanobot/workspace/skills/travel-research/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

RESEARCH_DIR = Path("/Users/ev/.nanobot/workspace/skills/travel-research")


def get_screenshot_path(topic: str, source: str) -> str:
    """Generate a timestamped screenshot path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = topic.lower().replace(" ", "-")
    safe_source = source.lower().replace(" ", "-").replace(".", "-").replace("/", "-")
    filename = f"{safe_topic}-{safe_source}-{timestamp}.png"
    return str(SCREENSHOTS_DIR / filename)


def list_screenshots() -> list:
    """List all captured screenshots."""
    return sorted([str(p) for p in SCREENSHOTS_DIR.glob("*.png")])


def save_research(topic: str, data: dict) -> str:
    """Save research results to a JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = topic.lower().replace(" ", "-")
    filename = f"{safe_topic}-research-{timestamp}.json"
    path = RESEARCH_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return str(path)


def load_latest_research(topic: str) -> dict:
    """Load the most recent research file for a topic."""
    safe_topic = topic.lower().replace(" ", "-")
    files = sorted(RESEARCH_DIR.glob(f"{safe_topic}-research-*.json"), reverse=True)
    if files:
        with open(files[0]) as f:
            return json.load(f)
    return {}


# Screenshot URL registry — common travel/booking sites
BOOKING_SITES = {
    "google_flights": "https://www.google.com/travel/flights",
    "skyscanner": "https://www.skyscanner.com.au",
    "kayak": "https://www.kayak.com.au/flights",
    "booking_com": "https://www.booking.com",
    "agoda": "https://www.agoda.com",
    "airbnb": "https://www.airbnb.com.au",
    "expedia": "https://www.expedia.com.au",
}

# BTS / Kpop concert info sites
INFO_SITES = {
    "bts_official": "https://bts.ibighit.com",
    "weverse": "https://weverse.io",
    "ticketmaster_kr": "https://www.ticketmaster.co.kr",
    "interpark": "https://ticket.interpark.com",
    "kpop_concerts": "https://www.kpopmap.com/category/concert/",
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Travel Research Skill")
    parser.add_argument("--list-screenshots", action="store_true",
                        help="List all captured screenshots")
    parser.add_argument("--screenshot-path", nargs=2, metavar=("TOPIC", "SOURCE"),
                        help="Get a screenshot path for a topic and source")
    parser.add_argument("--list-sites", action="store_true",
                        help="List known booking and info sites")
    parser.add_argument("--save-research", nargs=2, metavar=("TOPIC", "JSON_DATA"),
                        help="Save research data (JSON string) for a topic")
    parser.add_argument("--load-research", metavar="TOPIC",
                        help="Load most recent research for a topic")
    args = parser.parse_args()

    if args.list_screenshots:
        shots = list_screenshots()
        print(json.dumps(shots, indent=2))

    elif args.screenshot_path:
        path = get_screenshot_path(args.screenshot_path[0], args.screenshot_path[1])
        print(path)

    elif args.list_sites:
        print("=== Booking Sites ===")
        for name, url in BOOKING_SITES.items():
            print(f"  {name}: {url}")
        print("\n=== Info Sites ===")
        for name, url in INFO_SITES.items():
            print(f"  {name}: {url}")

    elif args.save_research:
        topic, json_str = args.save_research
        data = json.loads(json_str)
        path = save_research(topic, data)
        print(f"Research saved to: {path}")

    elif args.load_research:
        data = load_latest_research(args.load_research)
        print(json.dumps(data, indent=2))

    else:
        print("Travel Research Skill — Enhanced with Screenshot Capture")
        print(f"Screenshots directory: {SCREENSHOTS_DIR}")
        print(f"Research directory: {RESEARCH_DIR}")
        print("\nOptions:")
        print("  --list-screenshots        List all captured screenshots")
        print("  --screenshot-path T S     Get path for topic T, source S")
        print("  --list-sites              List known booking/info sites")
        print("  --save-research T JSON    Save research data for topic")
        print("  --load-research T         Load latest research for topic")
