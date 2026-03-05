---
name: whatsapp-monitor
description: Monitor incoming WhatsApp messages and send batched summaries to Telegram via the heartbeat. All WhatsApp activity is persisted to the unified chat.db for cross-channel recall.
---

# WhatsApp Monitor

This skill powers the periodic WhatsApp→Telegram summary pipeline. Every 30 minutes (on the heartbeat cycle), the agent checks for new WhatsApp messages and delivers a concise digest to Telegram.

## How It Works

1. All inbound and outbound WhatsApp messages are persisted to `~/.nanobot/chat.db` → `whatsapp_messages` table.
2. The heartbeat checks for new messages since the last check.
3. If new messages exist, the agent summarises them and returns the summary as the heartbeat response.
4. The heartbeat system automatically delivers the response to the last known Telegram chat.

## Query New Messages (heartbeat use)

```bash
python3 ~/.nanobot/workspace/skills/whatsapp-monitor/query_recent.py
```

- Returns messages since the last `whatsapp` check in `heartbeat-state.json`
- Returns `NO_NEW_WHATSAPP_MESSAGES` if nothing new

Other modes:
```bash
python3 query_recent.py --minutes 60   # last 60 minutes
python3 query_recent.py --all          # last 50 messages ever
```

## Summary Format for Telegram

When new messages are found, produce a summary like:

```
📱 WhatsApp digest (last 30 min):

• +61401234567 → 3 messages: asked about calendar, confirmed meeting at 3pm, sent a photo
• +61498765432 → 1 message: "Can you call me back?"
• nanobot replied to 2 chats
```

Keep it tight — 1 line per contact. If only 1–2 messages total, just quote them directly.

## Update State After Check

Always update `last_whatsapp` in heartbeat-state.json after processing:

```bash
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['whatsapp']=int(time.time()); p.write_text(json.dumps(s))\"")
```

## WhatsApp Table Schema

```sql
CREATE TABLE whatsapp_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    chat_id TEXT NOT NULL,       -- full JID e.g. 61401234567@s.whatsapp.net
    phone_number TEXT DEFAULT '', -- extracted number e.g. 61401234567
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

## Cross-Channel Recall

WhatsApp messages are searchable via the unified cross-chat-memory skill:

```bash
python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py <keyword>
```

This always searches web chat + Telegram + WhatsApp simultaneously.
