#!/usr/bin/env python3
"""Write .env on EC2 from the already-injected config.json.
Replaces the printf approach which broke on special chars in secret values."""
import json
from pathlib import Path

cfg = json.loads(Path("/opt/nanobot/config.json").read_text())

gc = cfg.get("tools", {}).get("google_calendar", {})
maps = cfg.get("tools", {}).get("google", {}).get("mapsApiKey", "")

Path("/opt/nanobot-app/.env").write_text(
    f"GOOGLE_CLIENT_ID={gc.get('clientId', '')}\n"
    f"GOOGLE_CLIENT_SECRET={gc.get('clientSecret', '')}\n"
    f"GOOGLE_STATIC_MAPS_API_KEY={maps}\n"
)
print("  .env written")
