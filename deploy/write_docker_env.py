#!/usr/bin/env python3
"""Write .env.docker for docker compose (BRIDGE_TOKEN, REACHY_BRIDGE_ENABLED, BRIDGE_SECRET).
Reads from config.json after inject_keys and from secrets JSON when present."""
import json

cfg = json.loads(Path("/opt/nanobot/config.json").read_text())
wa = cfg.get("channels", {}).get("whatsapp", {})
token = wa.get("bridge_token", "") or wa.get("bridgeToken", "")

reachy = cfg.get("channels", {}).get("reachyBridge", {})
reachy_enabled = "true" if reachy.get("enabled") else "false"
bridge_secret = reachy.get("secret", "")

lines = [
    f"BRIDGE_TOKEN={token}",
    f"REACHY_BRIDGE_ENABLED={reachy_enabled}",
    f"BRIDGE_SECRET={bridge_secret}",
]

Path("/opt/nanobot-app/.env.docker").write_text("\n".join(lines) + "\n")
print("  .env.docker written (BRIDGE_TOKEN, REACHY_BRIDGE_ENABLED, BRIDGE_SECRET)")
