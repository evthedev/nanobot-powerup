"""Reachy bridge helpers — Reachy command interception.

Only active when channels.reachy_bridge.enabled = true. Imported optionally
by whatsapp.py; no other channel needs to know about this.
"""

from __future__ import annotations

import json
import time

import aiohttp
from loguru import logger

from nanobot.config.schema import ReachyBridgeConfig

import re as _re

_REACHY_COMMANDS = [
    {
        "pattern": _re.compile(
            r"\b(wake\s*up|start|turn\s*on|boot\s*up|power\s*on)\b.*\breachy\b"
            r"|\breachy\b.*\b(wake\s*up|start|turn\s*on|boot\s*up|power\s*on)\b",
            _re.IGNORECASE,
        ),
        "command": "wake",
        "response": "Waking up Reachy... she'll be listening in about 30 seconds. 🤖",
    },
    {
        "pattern": _re.compile(
            r"\b(sleep|stop|turn\s*off|shut\s*down|power\s*off)\b.*\breachy\b"
            r"|\breachy\b.*\b(sleep|stop|turn\s*off|shut\s*down|power\s*off)\b",
            _re.IGNORECASE,
        ),
        "command": "sleep",
        "response": "Putting Reachy to sleep... 😴",
    },
    {
        "pattern": _re.compile(
            r"\b(restart|reboot)\b.*\breachy\b"
            r"|\breachy\b.*\b(restart|reboot)\b",
            _re.IGNORECASE,
        ),
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
        "command": "status",
        "response": None,  # built dynamically
    },
]


async def handle_reachy_command(message: str, cfg: ReachyBridgeConfig) -> str | None:
    """Check if message is a Reachy system command. Returns response string or None."""
    for entry in _REACHY_COMMANDS:
        if not entry["pattern"].search(message):
            continue
        cmd = entry["command"]
        if cmd == "status":
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"{cfg.url}/api/dashboard/status",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            rs = data.get("reachy", {})
                            age = time.time() - rs.get("last_seen", 0) if rs.get("last_seen") else 99999
                            if age > 600:
                                return f"Haven't heard from Reachy in a while ({age/60:.0f}m ago). She might be offline. 🚨"
                            return (
                                f"Reachy status (updated {age:.0f}s ago):\n"
                                f"  Daemon: {rs.get('daemon', 'unknown')}\n"
                                f"  Conversation app: {rs.get('conversation_app', 'unknown')}\n"
                                f"  PicoClaw: {rs.get('picoclaw', 'unknown')}"
                            )
            except Exception as e:
                logger.warning("Reachy status check failed: {}", e)
                return "Couldn't reach the bridge to check Reachy status."
        else:
            try:
                payload = json.dumps({"command": cmd}).encode()
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        f"{cfg.url}/api/dashboard/command",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            return entry["response"]
                        return f"Failed to queue {cmd} command (HTTP {resp.status})"
            except Exception as e:
                logger.warning("Reachy command queue failed: {}", e)
                return f"Couldn't reach the bridge to send {cmd} command."
    return None


