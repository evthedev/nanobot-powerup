"""Picoclaw channel — accepts WebSocket connections from picoclaw edge devices."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import PicoClawConfig

_DB_PATH = str(Path.home() / ".nanobot" / "chat.db")


def _ensure_table() -> None:
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS picoclaw_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                device_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("picoclaw: could not ensure table: {}", e)


def _persist(direction: str, device_id: str, content: str) -> None:
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO picoclaw_messages (direction, device_id, content) VALUES (?, ?, ?)",
            (direction, device_id, content),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("picoclaw: failed to persist message: {}", e)


class PicoClawChannel(BaseChannel):
    """WebSocket server channel for picoclaw edge devices."""

    name = "picoclaw"
    _DONE_DELAY = 90.0

    def __init__(self, config: PicoClawConfig, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.config: PicoClawConfig = config
        self._connections: dict[str, Any] = {}   # device_id → websocket
        self._server: Any = None
        self._done_timers: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        import websockets
        _ensure_table()
        self._running = True
        logger.info("Picoclaw channel starting on ws://0.0.0.0:{}", self.config.port)
        self._server = await websockets.serve(self._handle_connection, "0.0.0.0", self.config.port)
        await self._server.wait_closed()

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def send(self, msg: OutboundMessage) -> None:
        ws = self._connections.get(msg.chat_id)
        if not ws:
            logger.warning("picoclaw: no connection for device {}", msg.chat_id)
            return
        try:
            await ws.send(json.dumps({"type": "message", "content": msg.content}))
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _persist, "outbound", msg.chat_id, msg.content)
            self._reschedule_done(msg.chat_id, ws)
        except Exception as e:
            logger.warning("picoclaw: send failed for {}: {}", msg.chat_id, e)

    def _reschedule_done(self, device_id: str, ws: Any) -> None:
        existing = self._done_timers.pop(device_id, None)
        if existing:
            existing.cancel()

        async def _deferred() -> None:
            try:
                await asyncio.sleep(self._DONE_DELAY)
                if self._connections.get(device_id) is ws:
                    await ws.send(json.dumps({"type": "done"}))
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                self._done_timers.pop(device_id, None)

        self._done_timers[device_id] = asyncio.create_task(_deferred())

    async def _handle_connection(self, websocket: Any) -> None:
        # Bearer token auth
        if self.config.token:
            auth = getattr(websocket, "request_headers", {}).get("Authorization", "")
            if auth != f"Bearer {self.config.token}":
                await websocket.close(4401, "unauthorized")
                return

        # device_id from query param, default to "default"
        try:
            qs = websocket.request.path.split("?", 1)[1] if "?" in websocket.request.path else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            device_id = params.get("device_id", "default")
        except Exception:
            device_id = "default"

        self._connections[device_id] = websocket
        logger.info("picoclaw: device '{}' connected", device_id)

        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                content = data.get("content", "").strip()
                if not content:
                    continue

                # Cancel pending done timer for this device
                existing = self._done_timers.pop(device_id, None)
                if existing:
                    existing.cancel()

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _persist, "inbound", device_id, content)
                await self._handle_message(sender_id=device_id, chat_id=device_id, content=content)
        except Exception as exc:
            logger.debug("picoclaw: connection closed: {}", exc)
        finally:
            if self._connections.get(device_id) is websocket:
                del self._connections[device_id]
            timer = self._done_timers.pop(device_id, None)
            if timer:
                timer.cancel()
            logger.info("picoclaw: device '{}' disconnected", device_id)
