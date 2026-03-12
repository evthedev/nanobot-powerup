#!/usr/bin/env python3
"""Local test: WhatsApp channel passes media from bridge payload to InboundMessage."""

import asyncio
import json
import sys
from pathlib import Path

# Run from repo root so nanobot is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.whatsapp import WhatsAppChannel
from nanobot.config.schema import WhatsAppConfig


async def main() -> None:
    config = WhatsAppConfig(enabled=True, bridge_url="ws://localhost:3001", allow_from=[])
    bus = MessageBus()
    channel = WhatsAppChannel(config, bus)

    # Payload like the bridge sends when user sends an image (with media path)
    payload = {
        "type": "message",
        "id": "test-msg-1",
        "sender": "61434992528@s.whatsapp.net",
        "pn": "",
        "direction": "inbound",
        "content": "[Image] Use the picture I sent you",
        "timestamp": 1234567890,
        "isGroup": False,
        "media": ["/tmp/.nanobot/media/wa_abc123_999.jpg"],
    }

    async def consume():
        return await asyncio.wait_for(bus.consume_inbound(), timeout=5.0)

    consumer = asyncio.create_task(consume())
    await channel._handle_bridge_message(json.dumps(payload))
    msg: InboundMessage = await consumer

    assert msg.channel == "whatsapp"
    assert msg.content == "[Image] Use the picture I sent you"
    assert msg.media == ["/tmp/.nanobot/media/wa_abc123_999.jpg"], f"expected media in message, got media={msg.media!r}"
    print("OK: WhatsApp channel forwards media to InboundMessage")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)
