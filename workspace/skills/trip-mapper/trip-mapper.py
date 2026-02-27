#!/usr/bin/env python3
"""trip-mapper.py — geocode a list of stop names, generate a static map image,
and produce a clickable Google Maps directions URL.

Usage:
    python3 trip-mapper.py "Paris, France" "London, UK" "Amsterdam, Netherlands"

Output (stdout):
    IMAGE:/path/to/trip-map.png
    IMAGE_URL:/api/screenshots/trip-map.png
    URL:https://www.google.com/maps/dir/...
    STOPS:
    1. Paris, France (48.8566, 2.3522)
    ...
"""

import json
import os
import sys
from urllib.parse import quote_plus
import requests

# Save to the screenshots directory so the dashboard can serve the image directly
_SCREENSHOTS_DIR = os.path.expanduser(
    os.environ.get("SCREENSHOTS_DIR", "~/.nanobot/workspace/screenshots")
)
_SCREENSHOTS_URL = os.environ.get("SCREENSHOTS_BASE_URL", "/api/screenshots")


def get_maps_api_key() -> str:
    """Return the Google Static Maps API key.

    Checks environment variable first, then falls back to nanobot's config.json.
    On EC2 the key lives in config.json (injected by deploy), not in the container env.
    """
    key = os.environ.get("GOOGLE_STATIC_MAPS_API_KEY", "").strip()
    if key:
        return key

    config_path = os.path.expanduser("~/.nanobot/config.json")
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        key = cfg.get("tools", {}).get("google", {}).get("mapsApiKey", "").strip()
        if key:
            return key
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    print(
        "Error: GOOGLE_STATIC_MAPS_API_KEY not set "
        "(tried env var and ~/.nanobot/config.json)",
        file=sys.stderr,
    )
    sys.exit(1)


def geocode(stop: str) -> tuple[float, float]:
    """Geocode via Nominatim (OpenStreetMap) — free, no API key required.
    Falls back to Google Geocoding API if GOOGLE_GEOCODING_API_KEY is set."""
    google_key = os.environ.get("GOOGLE_GEOCODING_API_KEY", "").strip()

    if google_key:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        resp = requests.get(url, params={"address": stop, "key": google_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
        # Fall through to Nominatim if Google fails/denied
        print(f"Warning: Google Geocoding failed for '{stop}' (status={data.get('status')}), trying Nominatim...", file=sys.stderr)

    # Nominatim (OpenStreetMap) — always available, no key needed
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": stop, "format": "json", "limit": 1},
        headers={"User-Agent": "nanobot-trip-mapper/1.0"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        print(f"Error: Could not geocode: {stop}", file=sys.stderr)
        sys.exit(1)  # caught by main loop for per-stop skipping
    return float(results[0]["lat"]), float(results[0]["lon"])


def build_static_map_url(stops: list[tuple[str, float, float]], maps_key: str, use_path: bool = True) -> str:
    base = "https://maps.googleapis.com/maps/api/staticmap"
    params: list[str] = [
        "size=800x600",
        "maptype=roadmap",
    ]
    # Use single-digit labels for stops 1-9, letters A-Z for 10+
    for i, (_, lat, lng) in enumerate(stops, 1):
        label = str(i) if i <= 9 else chr(ord("A") + i - 10)
        params.append(f"markers=color:red|label:{label}|{lat},{lng}")

    if use_path:
        path_coords = "|".join(f"{lat},{lng}" for _, lat, lng in stops)
        params.append(f"path=color:0x0000ff|weight:3|{path_coords}")

    params.append(f"key={maps_key}")
    return f"{base}?{'&'.join(params)}"


def build_directions_url(stops: list[tuple[str, float, float]]) -> str:
    coord_parts = "/".join(f"{lat},{lng}" for _, lat, lng in stops)
    return f"https://www.google.com/maps/dir/{coord_parts}/"


def download_image(url: str, dest: str, maps_key: str) -> None:
    resp = requests.get(url, timeout=20)
    if resp.status_code != 200:
        print(f"Error: Static Maps API returned {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)
    with open(dest, "wb") as f:
        f.write(resp.content)


def main() -> None:
    stop_names = sys.argv[1:]

    if len(stop_names) < 2:
        print("Error: At least 2 stops are required", file=sys.stderr)
        sys.exit(1)
    if len(stop_names) > 25:
        print("Error: Maximum 25 stops allowed", file=sys.stderr)
        sys.exit(1)

    maps_key = get_maps_api_key()

    stops: list[tuple[str, float, float]] = []
    skipped: list[str] = []
    for name in stop_names:
        try:
            lat, lng = geocode(name)
            stops.append((name, lat, lng))
        except SystemExit:
            skipped.append(name)
            print(f"⚠️  Skipping '{name}' — could not geocode (too specific or not in Nominatim)", file=sys.stderr)

    if skipped:
        print(f"\nSkipped {len(skipped)} stop(s) that could not be geocoded: {', '.join(skipped)}", file=sys.stderr)

    if len(stops) < 2:
        print("Error: Fewer than 2 stops could be geocoded — cannot generate map", file=sys.stderr)
        sys.exit(1)

    # If more than 10 stops, the Static Maps path string gets very long —
    # use only markers (no path line) for large stop counts to stay under URL limits
    use_path = len(stops) <= 15

    static_map_url = build_static_map_url(stops, maps_key, use_path=use_path)
    directions_url = build_directions_url(stops)

    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
    image_filename = "trip-map.png"
    image_path = os.path.join(_SCREENSHOTS_DIR, image_filename)
    image_url = f"{_SCREENSHOTS_URL}/{image_filename}"

    download_image(static_map_url, image_path, maps_key)

    # Output ready-to-embed markdown so the agent doesn't have to parse key:value lines.
    # Just copy these lines verbatim into the response.
    print("✅ Trip map generated. Copy this EXACT markdown into your response:")
    print(f"![Trip Map]({image_url})")
    print(f"[Open in Google Maps]({directions_url})")
    print()
    print(f"IMAGE_PATH:{image_path}")
    print("STOPS:")
    for i, (name, lat, lng) in enumerate(stops, 1):
        print(f"  {i}. {name} ({lat:.4f}, {lng:.4f})")


if __name__ == "__main__":
    main()
