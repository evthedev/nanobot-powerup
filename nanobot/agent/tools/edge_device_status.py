"""Tool for querying edge device sync history from edge_sync_log."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class EdgeDeviceStatusTool(Tool):
    name = "edge_device_status"
    description = (
        "Query recent sync history and status for edge devices (cameras, sensors, robots, etc.). "
        "Omit device_id to get a summary of all devices. "
        "Use this when asked about what an edge device has been doing, its current state, or recent activity."
    )
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device ID to filter by (e.g. 'front-door-cam'). Omit for all devices.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of recent log entries to return (default 10, max 50)",
                "minimum": 1,
                "maximum": 50,
            },
        },
        "required": [],
    }

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(Path.home() / ".nanobot" / "chat.db")

    async def execute(self, device_id: str | None = None, limit: int = 10, **_: Any) -> str:
        limit = min(limit, 50)
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            if device_id:
                rows = conn.execute(
                    "SELECT device_id, direction, event_type, payload, created_at "
                    "FROM edge_sync_log WHERE device_id = ? ORDER BY id DESC LIMIT ?",
                    (device_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT device_id, direction, event_type, payload, created_at "
                    "FROM edge_sync_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            conn.close()
        except Exception as e:
            return f"Error reading edge_sync_log: {e}"

        if not rows:
            target = f"device '{device_id}'" if device_id else "any edge device"
            return f"No sync history found for {target}."

        lines = []
        for row in reversed(rows):
            payload = json.loads(row["payload"])
            direction = f"{row['device_id']}→Bridge" if row["direction"] == "inbound" else f"Bridge→{row['device_id']}"
            lines.append(f"[{row['created_at']}] {direction} ({row['event_type']}): {json.dumps(payload)}")

        return "\n".join(lines)
