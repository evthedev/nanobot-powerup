#!/usr/bin/env python3
"""Write .env.docker for docker compose.
Reads from config.json after inject_keys. Emits BRIDGE_TOKEN, EDGE_DEVICES_ENABLED.
Device secrets are read from config.json directly by the bridge — not passed as env vars.
"""
import json

with open("/opt/nanobot/config.json") as f:
    cfg = json.load(f)

wa = cfg.get("channels", {}).get("whatsapp", {})
token = wa.get("bridge_token", "") or wa.get("bridgeToken", "")

edge = cfg.get("channels", {}).get("edgeDevices", {})
reachy = cfg.get("channels", {}).get("reachyBridge", {})
edge_enabled = "true" if (edge.get("enabled") or reachy.get("enabled")) else "false"

github_token = cfg.get("tools", {}).get("github", {}).get("token", "")
github_repo = cfg.get("tools", {}).get("github", {}).get("repo", "")

lines = [
    f"BRIDGE_TOKEN={token}",
    f"EDGE_DEVICES_ENABLED={edge_enabled}",
    f"GITHUB_TOKEN={github_token}",
    f"GH_REPO={github_repo}",
]

open("/opt/nanobot-app/.env.docker", "w").write("\n".join(lines) + "\n")
print(f"  .env.docker written (BRIDGE_TOKEN, EDGE_DEVICES_ENABLED={edge_enabled}, GITHUB_TOKEN={'set' if github_token else 'unset'}, GH_REPO={github_repo})")
