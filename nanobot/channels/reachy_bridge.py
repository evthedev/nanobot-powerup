"""Edge device bridge helpers — command interception for edge devices.

Only active when channels.edge_devices.enabled = true. Imported optionally
by whatsapp.py; no other channel needs to know about this.

Legacy: also handles channels.reachy_bridge.enabled for backward compat.
"""

from __future__ import annotations

import json
import time

import aiohttp
from loguru import logger

from nanobot.config.schema import EdgeDevicesConfig, ReachyBridgeConfig

import re as _re

_DEVICE_COMMANDS = [
    {
        "pattern": _re.compile(
            r"\b(wake\s*up|start|turn\s*on|boot\s*up|power\s*on)\b.*\breachy\b"
            r"|\breachy\b.*\b(wake\s*up|start|turn\s*on|boot\s*up|power\s*on)\b",
            _re.IGNORECASE,
        ),
        "device_id": "reachy",
        "command": "wake",
        "response": "Waking up Reachy... she'll be listening in about 30 seconds. 🤖",
    },
    {
        "pattern": _re.compile(
            r"\b(sleep|stop|turn\s*off|shut\s*down|power\s*off)\b.*\breachy\b"
            r"|\breachy\b.*\b(sleep|stop|turn\s*off|shut\s*down|power\s*off)\b",
            _re.IGNORECASE,
        ),
        "device_id": "reachy",
        "command": "sleep",
        "response": "Putting Reachy to sleep... 😴",
    },
    {
        "pattern": _re.compile(
            r"\b(restart|reboot)\b.*\breachy\b"
            r"|\breachy\b.*\b(restart|reboot)\b",
            _re.IGNORECASE,
        ),
        "device_id": "reachy",
        "command": "restart_app",
        "response": "Restarting Reachy's conversation app... give her about 30 seconds. 🔄",
    },
    {
        "pattern": _re.compile(
            r"\b(status|check)\b.*\breachy\b"
            r"|\breachy\b.*\b(status|check)\b"
            r"|\bis\s+reachy\s+(on|up|running|alive|awake)\b",
            _re.IGNORECASE,
        ),
        "device_id": "reachy",
        "command": "status",
        "response": None,  # built dynamically
    },
]


def _bridge_url(cfg: EdgeDevicesConfig | ReachyBridgeConfig) -> str:
    return cfg.url if hasattr(cfg, "url") else "http://localhost:18790"


async def handle_edge_command(
    message: str,
    cfg: EdgeDevicesConfig | ReachyBridgeConfig,
) -> str | None:
    """Check if message is an edge device command. Returns response string or None."""
    for entry in _DEVICE_COMMANDS:
        if not entry["pattern"].search(message):
            continue
        device_id = entry["device_id"]
        cmd = entry["command"]
        base_url = _bridge_url(cfg)

        if cmd == "status":
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"{base_url}/api/devices/{device_id}/status",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            st = data.get("status", {})
                            age = time.time() - st.get("last_seen", 0) if st.get("last_seen") else 99999
                            if age > 600:
                                return f"Haven't heard from {device_id} in a while ({age/60:.0f}m ago). It might be offline. 🚨"
                            status_lines = "\n".join(
                                f"  {k}: {v}" for k, v in st.items() if k != "last_seen"
                            )
                            return (
                                f"{device_id} status (updated {age:.0f}s ago):\n"
                                f"{status_lines}"
                            )
            except Exception as e:
                logger.warning("Edge device status check failed for {}: {}", device_id, e)
                return f"Couldn't reach the bridge to check {device_id} status."
        else:
            try:
                payload = json.dumps({"command": cmd}).encode()
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        f"{base_url}/api/devices/{device_id}/command",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            return entry["response"]
                        return f"Failed to queue {cmd} directive for {device_id} (HTTP {resp.status})"
            except Exception as e:
                logger.warning("Edge device command failed for {}: {}", device_id, e)
                return f"Couldn't reach the bridge to send {cmd} to {device_id}."
    return None


# Legacy alias
async def handle_reachy_command(message: str, cfg: ReachyBridgeConfig) -> str | None:
    return await handle_edge_command(message, cfg)
