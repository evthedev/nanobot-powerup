"""WhatsApp channel implementation using Node.js bridge."""

import asyncio
import json
import sqlite3
import time as _time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WhatsAppConfig

_DB_PATH = str(Path.home() / ".nanobot" / "chat.db")


def _ensure_whatsapp_table() -> None:
    """Create whatsapp_messages table if it doesn't exist."""
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                chat_id TEXT NOT NULL,
                phone_number TEXT DEFAULT '',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("whatsapp: could not ensure whatsapp_messages table: {}", e)


def _persist_whatsapp_sync(direction: str, chat_id: str, phone_number: str, content: str) -> None:
    """Write a WhatsApp message to the shared SQLite database (called in executor)."""
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                phone_number TEXT DEFAULT '',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO whatsapp_messages (direction, chat_id, phone_number, content) VALUES (?, ?, ?, ?)",
            (direction, chat_id, phone_number, content)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("whatsapp: failed to persist message: {}", e)


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.

    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.

    Reply-allowed: only senders in config.allow_from (phone numbers) get agent
    replies; reply goes to the same chat (DM or group). See base.is_allowed().
    """
    
    name = "whatsapp"
    
    # Chat IDs we've accepted an inbound from (allowed sender). Reply is allowed to these
    # even when chat_id is a LID (e.g. 158149403226136@lid) and not in allow_from as a number.
    _MAX_ALLOWED_CHATS = 100

    def __init__(self, config: WhatsAppConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self._ws = None
        self._connected = False
        self._allowed_chat_ids: set[str] = set()
    
    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        import websockets
        
        bridge_url = self.config.bridge_url
        
        _ensure_whatsapp_table()
        logger.info("Connecting to WhatsApp bridge at {}...", bridge_url)
        
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    # Send auth token if configured
                    if self.config.bridge_token:
                        await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")
                    
                    # Listen for messages
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error("Error handling bridge message: {}", e)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("WhatsApp bridge connection error: {}", e)
                
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a reply via the WhatsApp bridge. Only sends to destinations on the allow list."""
        # Dual-response diagnostic
        _send_key = f"{msg.chat_id}:{int(_time.time()) // 30}"
        if not hasattr(self, "_send_counter"):
            self._send_counter: dict[str, int] = {}
        self._send_counter[_send_key] = self._send_counter.get(_send_key, 0) + 1
        if self._send_counter[_send_key] > 1:
            logger.warning(
                "DUAL RESPONSE DETECTED: {} sends to {} in 30s window",
                self._send_counter[_send_key], msg.chat_id,
            )
        if len(self._send_counter) > 20:
            for k in sorted(self._send_counter)[:-20]:
                del self._send_counter[k]
        logger.info("send() called: chat_id={} content_len={}", msg.chat_id, len(msg.content))

        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return
        # Enforce allow list: reply only if destination is in allow_from OR is a chat we
        # already accepted (e.g. LID for self-messages, where the sender number was allowed).
        destination_id = msg.chat_id.split("@")[0] if "@" in msg.chat_id else msg.chat_id
        allowed = self.is_allowed(destination_id) or msg.chat_id in self._allowed_chat_ids
        if not allowed:
            logger.warning(
                "WhatsApp outbound blocked: destination {} not in allowFrom. Message not sent.",
                destination_id,
            )
            return
        try:
            payload = {"type": "send", "to": msg.chat_id, "text": msg.content}
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            phone = msg.chat_id.split("@")[0] if "@" in msg.chat_id else msg.chat_id
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _persist_whatsapp_sync,
                "outbound", msg.chat_id, phone, msg.content
            )
        except Exception as e:
            logger.error("Error sending WhatsApp message: {}", e)

    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from bridge: {}", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "message":
            sender = data.get("sender", "")
            content = data.get("content", "")
            direction = data.get("direction", "inbound")
            if not content:
                return

            pn = data.get("pn", "")
            user_id = pn if pn else sender
            phone_number = user_id.split("@")[0] if "@" in user_id else user_id

            logger.info(
                "whatsapp: {} from {} — persisting to DB",
                direction, phone_number
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _persist_whatsapp_sync,
                direction, sender, phone_number, content
            )

            # Only route to agent if sender is on allow list; track this chat_id so we can reply to it.
            if self.is_allowed(phone_number):
                self._allowed_chat_ids.add(sender)
                while len(self._allowed_chat_ids) > self._MAX_ALLOWED_CHATS:
                    self._allowed_chat_ids.pop()

                # Optional Reachy command interception (requires channels.reachy_bridge.enabled)
                from nanobot.config.loader import load_config
                _cfg = load_config()
                _rb = _cfg.channels.reachy_bridge
                if _rb.enabled:
                    from nanobot.channels.reachy_bridge import handle_reachy_command, enrich_via_bridge
                    reachy_resp = await handle_reachy_command(content, _rb)
                    if reachy_resp:
                        logger.info("Reachy command intercepted: {}", content[:40])
                        if self._ws and self._connected:
                            await self._ws.send(json.dumps({"type": "send", "to": sender, "text": reachy_resp}))
                        return
                    enrichment = await enrich_via_bridge(content, phone_number, _rb)
                    content = enrichment + content if enrichment else content

                await self._handle_message(
                    sender_id=phone_number,
                    chat_id=sender,
                    content=content,
                    metadata={
                        "message_id": data.get("id"),
                        "timestamp": data.get("timestamp"),
                        "is_group": data.get("isGroup", False),
                    },
                )
        
        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info("WhatsApp status: {}", status)
            
            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False
        
        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")
        
        elif msg_type == "error":
            logger.error("WhatsApp bridge error: {}", data.get('error'))
