---
name: whatsapp-monitor
description: Monitor incoming WhatsApp messages, triage for attention, and notify via Telegram. Never reply on WhatsApp.
---

# WhatsApp Monitor

WhatsApp is **monitor-only**. The agent reads messages and forwards anything needing attention to Telegram. It never replies via WhatsApp — not even to acknowledge receipt.

## How it works

All inbound WhatsApp messages are persisted to `~/.nanobot/chat.db` → `whatsapp_messages` table by the bridge. The heartbeat queries this table, triages messages, and sends a Telegram notification for anything that needs attention.

## Fetch recent messages

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

## Triage rules — what gets forwarded

Forward to Telegram if the message contains any of:
- A direct question or request requiring a response
- Urgency signals: "urgent", "ASAP", "emergency", "call me", "need you", "important"
- Something actionable (booking, appointment, money, decision needed)
- A message from a known contact (in the allowFrom list) that isn't casual/automated

**Do NOT forward:**
- Automated notifications (OTP codes, delivery updates, bank alerts, marketing)
- Group message spam or broadcast messages
- Anything clearly not requiring a response

## Telegram notification format

```
📱 WhatsApp — {contact} ({time})
"{message content}"

→ Needs: {one line on what action, if any, the owner might want to take}
```

Keep it under 5 lines. One notification per contact thread, not per message.

If multiple contacts need attention, send one combined notification listing each.

If nothing needs attention → reply `HEARTBEAT_OK`.

## IMPORTANT

- **Never reply on WhatsApp** — not even "ok" or "seen". The channel is receive-only.
- If the owner wants to reply, they do so manually on their phone.
- Do not suggest using exec or the WhatsApp send API. It is disabled.
