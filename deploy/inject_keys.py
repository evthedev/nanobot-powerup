#!/usr/bin/env python3
"""Inject GitHub Secrets into /opt/nanobot/config.json on the EC2 instance.
Called by deploy.yml after git pull. Reads keys from environment variables."""
import json
import os


def set_nested(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


cfg_path = "/opt/nanobot/config.json"
with open(cfg_path) as f:
    cfg = json.load(f)

openrouter_key        = os.environ.get("OPENROUTER_API_KEY", "")
brave_key             = os.environ.get("BRAVE_API_KEY", "")
tavily_key            = os.environ.get("TAVILY_API_KEY", "")
maps_key              = os.environ.get("GOOGLE_STATIC_MAPS_API_KEY", "")
telegram_token        = os.environ.get("TELEGRAM_BOT_TOKEN", "")
google_client_id      = os.environ.get("GOOGLE_CLIENT_ID", "")
google_client_secret  = os.environ.get("GOOGLE_CLIENT_SECRET", "")
capsolver_api_key     = os.environ.get("CAPSOLVER_API_KEY", "")

if openrouter_key and not openrouter_key.startswith("REPLACE"):
    set_nested(cfg, "providers.openrouter.apiKey", openrouter_key)
    print(f"  openrouter key set ({len(openrouter_key)} chars)")

if tavily_key and not tavily_key.startswith("REPLACE"):
    set_nested(cfg, "tools.web.search.provider", "tavily")
    set_nested(cfg, "tools.web.search.tavilyApiKey", tavily_key)
    print(f"  tavily key set ({len(tavily_key)} chars)")
elif brave_key and not brave_key.startswith("REPLACE"):
    set_nested(cfg, "tools.web.search.apiKey", brave_key)
    print("  brave key set (tavily not provided, using brave)")

if maps_key and not maps_key.startswith("REPLACE"):
    set_nested(cfg, "tools.google.mapsApiKey", maps_key)
    print(f"  google maps key set ({len(maps_key)} chars)")

if telegram_token and not telegram_token.startswith("REPLACE"):
    set_nested(cfg, "channels.telegram.enabled", True)
    set_nested(cfg, "channels.telegram.token", telegram_token)
    print(f"  telegram token set, bot enabled")

if google_client_id and not google_client_id.startswith("REPLACE"):
    set_nested(cfg, "tools.google_calendar.clientId", google_client_id)
    print(f"  google client ID set")

if google_client_secret and not google_client_secret.startswith("REPLACE"):
    set_nested(cfg, "tools.google_calendar.clientSecret", google_client_secret)
    print(f"  google client secret set")

if capsolver_api_key and not capsolver_api_key.startswith("REPLACE"):
    set_nested(cfg, "tools.capsolver.api_key", capsolver_api_key)
    print(f"  capsolver key set ({len(capsolver_api_key)} chars)")

set_nested(cfg, "agents.defaults.model", "google/gemini-3-flash-preview")
print("  agent model: google/gemini-3-flash-preview")

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

print("config.json updated.")
