"""Tool for querying Reachy's sync history from reachy_sync_log."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ReachyStatusTool(Tool):
    name = "reachy_status"
    description = (
        "Query Reachy's recent sync history and status. "
        "Returns the latest inbound syncs (what Reachy reported) and any outbound commands sent. "
        "Use this when asked about what Reachy has been doing, her current state, or recent activity."
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of recent log entries to return (default 10, max 50)",
                "minimum": 1,
                "maximum": 50,
            }
        },
        "required": [],
    }

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(Path.home() / ".nanobot" / "chat.db")

    async def execute(self, limit: int = 10, **_: Any) -> str:
        limit = min(limit, 50)
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT direction, event_type, payload, created_at "
                "FROM reachy_sync_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        except Exception as e:
            return f"Error reading reachy_sync_log: {e}"

        if not rows:
            return "No Reachy sync history found."

        lines = []
        for row in reversed(rows):
            payload = json.loads(row["payload"])
            direction = "Reachy→Bridge" if row["direction"] == "inbound" else "Bridge→Reachy"
            lines.append(f"[{row['created_at']}] {direction} ({row['event_type']}): {json.dumps(payload)}")

        return "\n".join(lines)
