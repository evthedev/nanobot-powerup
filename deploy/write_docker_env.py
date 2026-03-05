#!/usr/bin/env python3
"""Write .env.docker for docker compose (BRIDGE_TOKEN for WhatsApp bridge).
Reads from config.json after inject_keys has run."""
import json
from pathlib import Path

cfg = json.loads(Path("/opt/nanobot/config.json").read_text())
wa = cfg.get("channels", {}).get("whatsapp", {})
token = wa.get("bridge_token", "") or wa.get("bridgeToken", "")

lines = [f"BRIDGE_TOKEN={token}"]
Path("/opt/nanobot-app/.env.docker").write_text("\n".join(lines) + "\n")
print("  .env.docker written (BRIDGE_TOKEN)")
