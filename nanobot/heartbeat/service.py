"""Heartbeat service - periodic agent wake-up to check for tasks."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

# Default interval: 30 minutes
DEFAULT_HEARTBEAT_INTERVAL_S = 30 * 60

# The prompt sent to agent during heartbeat
HEARTBEAT_PROMPT = """Read HEARTBEAT.md in your workspace (if it exists).
Follow any instructions or tasks listed there.
If nothing needs attention, reply with just: HEARTBEAT_OK"""

# Token that indicates "nothing to do"
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

# Per-check thresholds (seconds) — must stay in sync with HEARTBEAT.md.
# reddit has an additional hour constraint enforced in _is_check_due().
_CHECK_THRESHOLDS: dict[str, int] = {
    "calendar": 7200,   # 2 hours
    "whatsapp": 1800,   # 30 minutes
    "todos":    1800,   # 30 minutes
    "reddit":   82800,  # 23 hours, only 07:00–10:00 local
}
_REDDIT_HOUR_RANGE = (7, 10)


def _is_heartbeat_empty(content: str | None) -> bool:
    """Check if HEARTBEAT.md has no actionable tasks.

    Only open checkbox items with non-empty text are considered actionable,
    e.g. ``- [ ] Check calendar``.  Headers, HTML comments (including
    multi-line blocks), blank lines, prose, and completed/empty checkboxes
    are all ignored.
    """
    if not content:
        return True

    in_comment = False
    for line in content.split("\n"):
        stripped = line.strip()

        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue

        if stripped.startswith("- [ ]") or stripped.startswith("* [ ]"):
            task_text = stripped[5:].strip()
            if task_text:
                return False

    return True


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    The agent reads HEARTBEAT.md from the workspace and executes any
    tasks listed there. If nothing needs attention, it replies HEARTBEAT_OK.
    """

    _TICK_TIMEOUT_RATIO = 0.8

    def __init__(
        self,
        workspace: Path,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.on_heartbeat = on_heartbeat
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _is_check_due(self) -> bool:
        """Return True if any check in heartbeat-state.json is past its threshold.

        Reads the state file written by the agent after each check. If the file
        is missing or a key is absent, that check is treated as never run (due).

        NOTE: _CHECK_THRESHOLDS must be kept in sync with HEARTBEAT.md.
        """
        state_file = self.workspace / "heartbeat-state.json"
        try:
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
        except Exception:
            return True  # unreadable — let agent run

        now = int(time.time())
        hour = time.localtime(now).tm_hour

        for check, threshold in _CHECK_THRESHOLDS.items():
            elapsed = now - state.get(check, 0)
            if elapsed < threshold:
                continue
            if check == "reddit" and not (_REDDIT_HOUR_RANGE[0] <= hour <= _REDDIT_HOUR_RANGE[1]):
                continue
            logger.info("Heartbeat: '{}' due ({}s elapsed, threshold {}s)", check, elapsed, threshold)
            return True

        return False

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        tick_timeout = max(60, int(self.interval_s * self._TICK_TIMEOUT_RATIO))
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    try:
                        await asyncio.wait_for(self._tick(), timeout=tick_timeout)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Heartbeat tick timed out after {}s — skipping to next cycle",
                            tick_timeout,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        content = self._read_heartbeat_file()

        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat: no tasks (HEARTBEAT.md empty)")
            return

        if not self._is_check_due():
            logger.debug("Heartbeat: no checks due — skipping LLM call")
            return

        logger.info("Heartbeat: check due, invoking agent...")

        if self.on_heartbeat:
            try:
                response = await self.on_heartbeat(HEARTBEAT_PROMPT)

                if HEARTBEAT_OK_TOKEN.replace("_", "") in response.upper().replace("_", ""):
                    logger.info("Heartbeat: OK (no action needed)")
                else:
                    logger.info("Heartbeat: completed task")

            except Exception as e:
                logger.error("Heartbeat execution failed: {}", e)

    async def trigger_now(self) -> str | None:
        if self.on_heartbeat:
            return await self.on_heartbeat(HEARTBEAT_PROMPT)
        return None
