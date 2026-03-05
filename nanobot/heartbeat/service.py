"""Heartbeat service - periodic agent wake-up to check for tasks."""

import asyncio
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

        # Track multi-line HTML comment blocks
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue

        # Only unchecked task items with actual text are actionable
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

    # Tick timeout: 80% of the interval, so a hung tick can't swallow the next cycle.
    # E.g. 30-min interval → 24-min tick timeout.
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
        """Read HEARTBEAT.md content."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None
    
    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)
    
    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
    
    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
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
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        
        # Skip if HEARTBEAT.md is empty or doesn't exist
        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat: no tasks (HEARTBEAT.md empty)")
            return
        
        logger.info("Heartbeat: checking for tasks...")
        
        if self.on_heartbeat:
            try:
                response = await self.on_heartbeat(HEARTBEAT_PROMPT)
                
                # Check if agent said "nothing to do"
                if HEARTBEAT_OK_TOKEN.replace("_", "") in response.upper().replace("_", ""):
                    logger.info("Heartbeat: OK (no action needed)")
                else:
                    logger.info("Heartbeat: completed task")
                    
            except Exception as e:
                logger.error("Heartbeat execution failed: {}", e)
    
    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        if self.on_heartbeat:
            return await self.on_heartbeat(HEARTBEAT_PROMPT)
        return None
