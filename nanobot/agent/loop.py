"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.reddit import RedditSearchTool
from nanobot.agent.tools.review_screenshots import ReviewScreenshotsTool
from nanobot.agent.tools.travel_screenshots import TravelScreenshotsTool
from nanobot.agent.tools.trustpilot import TrustpilotSearchTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.agent.tools.yelp import YelpSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, ToolCallRequest
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig
    from nanobot.cron.service import CronService


# ---------------------------------------------------------------------------
# Travel-screenshots auto-injection
# ---------------------------------------------------------------------------
# gpt-4o-mini stops following skill MANDATORY RULES at ~15k+ input tokens.
# This guard detects travel-related web_searches that omit travel_screenshots
# and synthesises the call so it always fires, regardless of context depth.

_TRAVEL_DEST = {
    "busan":     ("pus", "Busan"),
    "seoul":     ("icn", "Seoul"),
    "tokyo":     ("nrt", "Tokyo"),
    "osaka":     ("kix", "Osaka"),
    "kyoto":     ("itm", "Kyoto"),
    "paris":     ("cdg", "Paris"),
    "london":    ("lhr", "London"),
    "bali":      ("dps", "Bali"),
    "singapore": ("sin", "Singapore"),
    "bangkok":   ("bkk", "Bangkok"),
    "hong kong": ("hkg", "Hong Kong"),
    "new york":  ("jfk", "New York"),
    "dubai":     ("dxb", "Dubai"),
}

_TRAVEL_SIGNALS = frozenset({
    "flight", "flights", "hotel", "hotels", "accommodation",
    "hostel", "itinerary", "concert", "trip to", "travel to",
    *_TRAVEL_DEST,
})


def _maybe_inject_travel_screenshots(
    calls: list[ToolCallRequest],
    messages: list[dict],
    tools,
) -> list[ToolCallRequest]:
    """Return calls unchanged, or with a synthetic travel_screenshots prepended."""
    # Only act when there are web_searches but no travel_screenshots.
    if any(tc.name == "travel_screenshots" for tc in calls):
        return calls
    if not any(tc.name == "web_search" for tc in calls):
        return calls

    # Check recent tool results — skip if travel_screenshots already fired this turn.
    for msg in reversed(messages[-10:]):
        if msg.get("role") == "tool" and msg.get("name") == "travel_screenshots":
            return calls

    # Scan search queries for travel signals + a known destination.
    all_queries = " ".join(
        json.dumps(tc.arguments).lower()
        for tc in calls
        if tc.name == "web_search"
    )
    if not any(sig in all_queries for sig in _TRAVEL_SIGNALS):
        return calls

    dest_key = next((k for k in _TRAVEL_DEST if k in all_queries), None)
    if not dest_key:
        return calls

    _iata, dest_name = _TRAVEL_DEST[dest_key]

    # Extract year/month hints — check queries first, then scan message history
    # (covers "March 21" stored in memory but not repeated in every search query).
    yr_m = re.search(r"20(\d{2})", all_queries)
    yr_sfx = yr_m.group(1) if yr_m else "26"
    mo_map = {"jan": "jan", "feb": "feb", "mar": "mar", "apr": "apr",
              "may": "may", "jun": "jun", "jul": "jul", "aug": "aug",
              "sep": "sep", "oct": "oct", "nov": "nov", "dec": "dec"}
    mo_sfx = next((v for k, v in mo_map.items() if k in all_queries), "")
    if not mo_sfx:
        # Fallback: scan recent messages/tool-results for month hints (e.g. from MEMORY.md)
        history_text = " ".join(
            str(m.get("content", "")).lower()
            for m in messages[-20:]
            if m.get("role") in ("tool", "user", "assistant")
        )
        mo_sfx = next((v for k, v in mo_map.items() if k in history_text), "")

    # Extract event hint.
    event_words = ["bts", "coldplay", "taylor swift", "concert", "festival"]
    event_name_raw = next((e for e in event_words if e in all_queries), dest_name)
    event_slug = event_name_raw.replace(" ", "-")

    slug_parts = [p for p in [event_slug, dest_name.lower().replace(" ", "-"), f"{mo_sfx}{yr_sfx}"] if p]
    trip_slug = "-".join(slug_parts)

    # Build a human-readable travel date for Google Search queries
    mo_full_map = {
        "jan": "January", "feb": "February", "mar": "March", "apr": "April",
        "may": "May", "jun": "June", "jul": "July", "aug": "August",
        "sep": "September", "oct": "October", "nov": "November", "dec": "December",
    }
    mo_full = mo_full_map.get(mo_sfx, mo_sfx) if mo_sfx else ""
    travel_date = f"{mo_full} 20{yr_sfx}" if mo_full else f"20{yr_sfx}"

    event_name_display = f"{event_name_raw.title()} {dest_name} {travel_date} concert"

    args = {
        "trip_slug":        trip_slug,
        "destination_city": dest_name,
        "travel_date":      travel_date,
        "event_name":       event_name_display,
        "origin_city":      "Sydney",
    }
    synthetic = ToolCallRequest(id="auto-ts-inject", name="travel_screenshots", arguments=args)
    logger.info("Auto-injected travel_screenshots for '{}' — date: {}", trip_slug, travel_date)
    return [synthetic, *calls]


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        memory_window: int = 50,
        brave_api_key: str | None = None,
        yelp_api_key: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.yelp_api_key = yelp_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            yelp_api_key=yelp_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        # Tracks the last Telegram chat_id seen so heartbeat can deliver there.
        # Persisted across restarts via a small file in the workspace.
        self._tg_chat_id_file = workspace / ".last_telegram_chat_id"
        self.last_telegram_chat_id: str | None = (
            self._tg_chat_id_file.read_text().strip()
            if self._tg_chat_id_file.exists()
            else None
        )
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(RedditSearchTool())
        self.tools.register(TrustpilotSearchTool())
        self.tools.register(YelpSearchTool(api_key=self.yelp_api_key))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        screenshots_dir = str(self.workspace / "screenshots")
        self.tools.register(ReviewScreenshotsTool(manager=self.subagents, screenshots_dir=screenshots_dir))
        self.tools.register(TravelScreenshotsTool(
            manager=self.subagents,
            screenshots_dir=screenshots_dir,
            send_callback=self.bus.publish_outbound,
        ))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            # Strip Playwright tools from main agent — it's too weak to sequence
            # navigate→screenshot correctly. Pass them to subagents instead.
            playwright_tools = [n for n in self.tools.tool_names if n.startswith("mcp_playwright_")]
            mcp_tool_objects = [self.tools.get(n) for n in playwright_tools]
            for tool_name in playwright_tools:
                self.tools.unregister(tool_name)
            if playwright_tools:
                logger.info("Main agent: removed {} Playwright tools → passed to subagents", len(playwright_tools))
                self.subagents.set_mcp_tools(mcp_tool_objects)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id, message_id)

        if spawn_tool := self.tools.get("spawn"):
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(channel, chat_id)

        if rs_tool := self.tools.get("review_screenshots"):
            if isinstance(rs_tool, ReviewScreenshotsTool):
                rs_tool.set_context(channel, chat_id)
        if ts_tool := self.tools.get("travel_screenshots"):
            if isinstance(ts_tool, TravelScreenshotsTool):
                ts_tool.set_context(channel, chat_id)
                ts_tool.set_send_callback(self.bus.publish_outbound)

        if cron_tool := self.tools.get("cron"):
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(channel, chat_id)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str]]:
        """Run the agent iteration loop. Returns (final_content, tools_used)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            if response.usage:
                u = response.usage
                logger.info(
                    "LLM usage | model={} tokens_in={} tokens_out={} total={}",
                    self.model,
                    u.get("prompt_tokens", 0),
                    u.get("completion_tokens", 0),
                    u.get("total_tokens", 0),
                )

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
                    await on_progress(self._tool_hint(response.tool_calls))

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                # Orchestration mode:
                # - Read-only search tools (reddit, trustpilot, web_search, web_fetch, read, list)
                #   are safe to run in parallel — their inputs are independent.
                # - Side-effect tools (spawn, message, write, edit) must be serialised: only one
                #   runs per turn so the agent sees results before proceeding.
                _PARALLEL_SAFE = {
                    "reddit_search", "trustpilot_search", "yelp_search",
                    "web_search", "web_fetch",
                    "read_file", "list_files", "list_directory",
                    # Screenshot tools spawn background subagents (non-blocking)
                    # and can fire alongside search tools in the same round
                    "review_screenshots", "travel_screenshots",
                }
                calls_to_run = response.tool_calls

                # Auto-inject travel_screenshots when the model calls travel-related
                # web_searches but omits travel_screenshots (happens at high context depth).
                calls_to_run = _maybe_inject_travel_screenshots(
                    calls_to_run, messages, self.tools,
                )

                if len(calls_to_run) > 1:
                    call_names = {tc.name for tc in calls_to_run}
                    if any(tc.name == "spawn" for tc in calls_to_run):
                        # spawn takes full priority — run only spawns
                        calls_to_run = [tc for tc in calls_to_run if tc.name == "spawn"]
                        dropped = [tc.name for tc in response.tool_calls if tc.name != "spawn"]
                        logger.info("Sequential mode — running 1 tool, deferring: {}", dropped)
                    elif call_names <= _PARALLEL_SAFE:
                        # All calls are read-only search tools — run in parallel
                        logger.info("Parallel search mode — running {} tools simultaneously: {}",
                                    len(calls_to_run), sorted(call_names))
                        dropped = []
                    else:
                        # Mixed or side-effect tools — run only the first
                        calls_to_run = [response.tool_calls[0]]
                        dropped = [tc.name for tc in response.tool_calls[1:]]
                        logger.info("Sequential mode — running 1 tool, deferring: {}", dropped)
                    for tc in response.tool_calls:
                        if tc not in calls_to_run:
                            messages = self.context.add_tool_result(
                                messages, tc.id, tc.name,
                                "(deferred — run sequentially after seeing previous result)"
                            )

                if len(calls_to_run) > 1:
                    # Run all calls concurrently (only reached when all are parallel-safe)
                    async def _run_one(tc) -> tuple:
                        args_str = json.dumps(tc.arguments, ensure_ascii=False)
                        logger.info("Tool call: {}({})", tc.name, args_str[:200])
                        result = await self.tools.execute(tc.name, tc.arguments)
                        return tc, result

                    results_pairs = await asyncio.gather(*[_run_one(tc) for tc in calls_to_run])
                    for tc, result in results_pairs:
                        tools_used.append(tc.name)
                        messages = self.context.add_tool_result(messages, tc.id, tc.name, result)
                else:
                    for tool_call in calls_to_run:
                        tools_used.append(tool_call.name)
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name, result
                        )
            else:
                final_content = self._strip_think(response.content)
                break

        return final_content, tools_used

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                if msg.channel == "telegram" and msg.chat_id:
                    if msg.chat_id != self.last_telegram_chat_id:
                        self.last_telegram_chat_id = msg.chat_id
                        try:
                            self._tg_chat_id_file.write_text(msg.chat_id)
                        except Exception:
                            pass

                try:
                    response = await self._process_message(msg)
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id, content="", metadata=msg.metadata or {},
                        ))
                except Exception as e:
                    logger.error("Error processing message: {}", e)
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            messages = self.context.build_messages(
                history=session.get_history(max_messages=self.memory_window),
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _ = await self._run_agent_loop(messages)
            session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
            session.add_message("assistant", final_content or "Background task completed.")
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        logger.info(">>> INBOUND [{}:{}]: {}", msg.channel, msg.sender_id, msg.content)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            messages_to_archive = session.messages.copy()
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)

            async def _consolidate_and_cleanup():
                temp = Session(key=session.key)
                temp.messages = messages_to_archive
                await self._consolidate_memory(temp, archive_all=True)

            asyncio.create_task(_consolidate_and_cleanup())
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started. Memory consolidation in progress.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/help — Show available commands")

        if len(session.messages) > self.memory_window and session.key not in self._consolidating:
            self._consolidating.add(session.key)

            async def _consolidate_and_unlock():
                try:
                    await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)

            asyncio.create_task(_consolidate_and_unlock())

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        initial_messages = self.context.build_messages(
            history=session.get_history(max_messages=self.memory_window),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, tools_used = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        logger.info("<<< OUTBOUND [{}:{}]: {}", msg.channel, msg.sender_id, final_content)

        session.add_message("user", msg.content)
        session.add_message("assistant", final_content,
                            tools_used=tools_used if tools_used else None)
        self.sessions.save(session)

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return None

        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    async def _consolidate_memory(self, session, archive_all: bool = False) -> None:
        """Delegate to MemoryStore.consolidate()."""
        await MemoryStore(self.workspace).consolidate(
            session, self.provider, self.model,
            archive_all=archive_all, memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
