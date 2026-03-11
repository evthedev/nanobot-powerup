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
edge_enabled = "true" if edge.get("enabled") else "false"

# Legacy reachy bridge fallback — keep REACHY_BRIDGE_ENABLED for any old bridge code
# still reading it, but EDGE_DEVICES_ENABLED is the canonical var going forward.
reachy = cfg.get("channels", {}).get("reachyBridge", {})
reachy_enabled = "true" if reachy.get("enabled") else edge_enabled

lines = [
    f"BRIDGE_TOKEN={token}",
    f"EDGE_DEVICES_ENABLED={edge_enabled}",
    f"REACHY_BRIDGE_ENABLED={reachy_enabled}",  # legacy compat
]

open("/opt/nanobot-app/.env.docker", "w").write("\n".join(lines) + "\n")
print(f"  .env.docker written (BRIDGE_TOKEN, EDGE_DEVICES_ENABLED={edge_enabled}, REACHY_BRIDGE_ENABLED={reachy_enabled})")
