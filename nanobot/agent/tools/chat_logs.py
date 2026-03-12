"""ChatLogsTool — fetch logs for the current conversation."""

import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _nanobot_logs_path() -> Path:
    return Path(os.environ.get("NANOBOT_HOME", str(Path.home() / ".nanobot"))) / "logs" / "gateway.log"


def _filter_lines_for_chat(chat_id: str, lines: list[str]) -> list[str]:
    """Include lines between INBOUND and OUTBOUND that mention chat=chat_id."""
    escaped = re.escape(str(chat_id))
    chat_re = re.compile(rf"chat={escaped}(?=[\s:]|$)")
    active = False
    result: list[str] = []
    for line in lines:
        has_chat = bool(chat_re.search(line))
        if ">>> INBOUND" in line and has_chat:
            active = True
        if active:
            result.append(line)
        if "<<< OUTBOUND" in line and has_chat:
            active = False
    return result


class ChatLogsTool(Tool):
    """Tool to fetch logs for the current chat. Use when the user asks to see logs for this conversation."""

    def __init__(self) -> None:
        self._channel = ""
        self._chat_id = ""

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "get_chat_logs"

    @property
    def description(self) -> str:
        return (
            "Fetch the agent logs for the current conversation. Use when the user asks to "
            "'show me logs for this chat', 'what happened in this conversation', or similar. "
            "Returns INBOUND/OUTBOUND messages, tool calls, and LLM usage for this chat."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of log lines to return (default 100)",
                    "default": 100,
                },
            },
            "required": [],
        }

    async def execute(self, limit: int = 100, **kwargs: Any) -> str:
        if not self._chat_id:
            return "Error: No chat context. This tool only works when the user is in an active conversation."
        log_path = _nanobot_logs_path()
        if not log_path.exists():
            return f"Error: Log file not found at {log_path}"
        try:
            # Read last N lines (tail-like)
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail = lines[-min(limit * 3, len(lines)) :]  # Read extra to filter
            filtered = _filter_lines_for_chat(self._chat_id, tail)
            if not filtered:
                return f"No logs found for this chat (chat_id={self._chat_id}). Logs are written when messages are processed."
            # Strip timestamps for brevity; keep the message part
            out: list[str] = []
            for line in filtered[-limit:]:
                line = line.rstrip()
                if " - " in line:
                    # Loguru format: "timestamp | level | module - message"
                    msg = line.split(" - ", 1)[-1]
                    out.append(msg)
                else:
                    out.append(line)
            return "\n".join(out)
        except Exception as e:
            return f"Error reading logs: {e}"
