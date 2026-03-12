---
name: trip-mapper
description: Generate a map image with numbered pins for a list of locations, plus a clickable Google Maps directions link.
note: Max 25 stops. Stops beyond 25 will be silently dropped.
triggers:
  - "map these locations"
  - "show on a map"
  - "map out my itinerary"
  - "visualise these stops"
  - "route between"
---

# Trip Mapper Skill

**Note: Max 25 stops. Stops beyond 25 will be silently dropped.**

Generate a map image with numbered pins for a list of locations, plus a clickable Google Maps directions link.

## When to use

**Use this skill (via `exec`) for ANY of:**
- "Generate a map with these points/locations"
- "Show all these places on a map"
- "Map out my itinerary"
- "Visualise these stops on a map"
- "Show the route between X, Y, Z"
- Any request to plot multiple locations on a map

**Do NOT spawn a subagent. Do NOT write HTML. Use `exec` directly.**

## How to use — EXACT COMMAND

```
exec: python3 ~/.nanobot/workspace/skills/trip-mapper/trip-mapper.py "Stop 1" "Stop 2" "Stop 3" ...
```

- Each stop is a quoted string — be specific enough to geocode (e.g. `"Gamcheon Culture Village, Busan"` not `"Gamcheon"`)
- Minimum 2 stops, maximum 25 stops
- If the user gives more than 25, pick the 25 most important

## Reading the output

The script prints to stdout:
```
IMAGE:/path/to/trip-map.png
IMAGE_URL:/api/screenshots/trip-map.png
URL:https://www.google.com/maps/dir/...
STOPS:
  1. Gamcheon Culture Village, Busan (35.0970, 129.0147)
  2. ...
```

## After running — MANDATORY

**You MUST do all three:**

1. **Embed the map image** in your response using the `IMAGE_URL` from the output:
   `![Trip Map](IMAGE_URL_HERE)`

2. **Send the Google Maps URL** as a clickable link:
   `[Open in Google Maps](URL_HERE)`

3. **List all stops** with their pin numbers so the user knows what each marker represents

## Environment variables (auto-injected by gateway)

- `GOOGLE_STATIC_MAPS_API_KEY` — auto-set from config, no action needed
- Geocoding uses Nominatim (OpenStreetMap) — no API key needed

## Error handling

| Error | Action |
|---|---|
| `GOOGLE_STATIC_MAPS_API_KEY not set` | Add `mapsApiKey` to config.json under `tools.google` |
| `Could not geocode: <stop>` | Make the stop name more specific (add city/country) |
| Static Maps API error | Check the API key is valid and Maps Static API is enabled |
