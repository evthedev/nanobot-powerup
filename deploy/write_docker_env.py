#!/usr/bin/env python3
"""Write .env.docker for docker compose (BRIDGE_TOKEN, REACHY_BRIDGE_ENABLED, BRIDGE_SECRET).
Reads from config.json after inject_keys and from secrets JSON when present."""
import json
from pathlib import Path

cfg = json.loads(Path("/opt/nanobot/config.json").read_text())
wa = cfg.get("channels", {}).get("whatsapp", {})
token = wa.get("bridge_token", "") or wa.get("bridgeToken", "")

lines = [f"BRIDGE_TOKEN={token}"]

# Reachy bridge: from secrets file (written by deploy) so .env.docker gets them for compose
secrets_path = Path("/tmp/nanobot_secrets.json")
if secrets_path.exists():
    secrets = json.loads(secrets_path.read_text())
    reachy_enabled = secrets.get("REACHY_BRIDGE_ENABLED", "") or "false"
    bridge_secret = secrets.get("BRIDGE_SECRET", "")
    lines.append(f"REACHY_BRIDGE_ENABLED={reachy_enabled}")
    lines.append(f"BRIDGE_SECRET={bridge_secret}")

Path("/opt/nanobot-app/.env.docker").write_text("\n".join(lines) + "\n")
print("  .env.docker written (BRIDGE_TOKEN, REACHY_BRIDGE_ENABLED, BRIDGE_SECRET)")
