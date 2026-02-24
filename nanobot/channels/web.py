"""Web channel — WebSocket server bridging the chat dashboard to the nanobot agent loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebConfig


class WebChannel(BaseChannel):
    """
    WebSocket channel that lets the chat dashboard talk to the nanobot agent loop.

    Protocol (JSON over WebSocket):
      Client → nanobot:  {"session_id": "<id>", "content": "<text>"}
      Nanobot → client:  {"type": "message", "content": "<text>"}
                         {"type": "error",   "content": "<text>"}
                         {"type": "done"}

    "done" is sent N seconds after the last message so that subagents running
    asynchronously after the main agent's reply can still deliver their response
    into the same open connection.
    """

    name = "web"
    # How long to wait after the last message before declaring the session done.
    # Subagents typically complete within 60 s; 90 s is a safe upper bound.
    _DONE_DELAY = 90.0

    def __init__(self, config: WebConfig, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.config: WebConfig = config
        # Map chat_id (session_id from client) → open WebSocket connection
        self._connections: dict[str, Any] = {}
        self._server: Any = None
        # Pending asyncio tasks that will send "done" after the idle timeout
        self._done_timers: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not available — web channel cannot start")
            return

        self._running = True
        logger.info("Web channel starting on ws://0.0.0.0:{}", self.config.port)

        self._server = await websockets.serve(
            self._handle_connection,
            "0.0.0.0",
            self.config.port,
        )
        await self._server.wait_closed()

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Web channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        # Progress messages (tool-call hints emitted mid-loop) are for Telegram typing
        # indicators only — ignore them here so the connection stays open until the
        # agent produces its real final answer.
        if msg.metadata and msg.metadata.get("_progress"):
            return

        ws = self._connections.get(msg.chat_id)
        if ws is None:
            logger.warning("Web channel: no active connection for session {}", msg.chat_id)
            return
        try:
            await ws.send(json.dumps({"type": "message", "content": msg.content}))
            logger.debug("Web channel: sent message to session {}", msg.chat_id)
        except Exception as exc:
            logger.warning("Web channel: failed to send to session {}: {}", msg.chat_id, exc)
            return

        # Cancel any existing idle timer and start a fresh one.
        # "done" is deferred so subagents have time to deliver their response
        # before the Express server closes the WebSocket.
        existing = self._done_timers.pop(msg.chat_id, None)
        if existing:
            existing.cancel()

        chat_id = msg.chat_id

        async def _deferred_done() -> None:
            try:
                await asyncio.sleep(self._DONE_DELAY)
                ws_now = self._connections.get(chat_id)
                if ws_now is not None:
                    await ws_now.send(json.dumps({"type": "done"}))
                    logger.debug("Web channel: sent deferred done to session {}", chat_id)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Web channel: deferred done error for {}: {}", chat_id, exc)
            finally:
                self._done_timers.pop(chat_id, None)

        self._done_timers[chat_id] = asyncio.create_task(_deferred_done())

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a single WebSocket client connection."""
        remote = getattr(websocket, "remote_address", "unknown")
        logger.debug("Web channel: new connection from {}", remote)

        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"type": "error", "content": "Invalid JSON"}))
                    continue

                session_id = data.get("session_id", "")
                content = data.get("content", "").strip()

                if not session_id or not content:
                    await websocket.send(json.dumps({"type": "error", "content": "Missing session_id or content"}))
                    continue

                # Register (or re-register) this WebSocket under the session_id
                self._connections[session_id] = websocket
                logger.info("Web channel inbound [{}]: {}", session_id, content[:120])

                await self._handle_message(
                    sender_id="web_user",
                    chat_id=session_id,
                    content=content,
                )
        except Exception as exc:
            logger.debug("Web channel: connection closed: {}", exc)
        finally:
            # Clean up stale connection references and any pending done timers
            stale = [k for k, v in self._connections.items() if v is websocket]
            for k in stale:
                del self._connections[k]
                timer = self._done_timers.pop(k, None)
                if timer:
                    timer.cancel()
            logger.debug("Web channel: connection from {} removed", remote)
