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

openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
brave_key      = os.environ.get("BRAVE_API_KEY", "")
tavily_key     = os.environ.get("TAVILY_API_KEY", "")
maps_key       = os.environ.get("GOOGLE_STATIC_MAPS_API_KEY", "")

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

set_nested(cfg, "agents.defaults.model", "google/gemini-3-flash-preview")
print("  agent model: google/gemini-3-flash-preview")

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

print("config.json updated.")
