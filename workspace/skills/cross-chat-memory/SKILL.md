---
name: cross-chat-memory
description: Search and recall conversations from any channel (web chat, Telegram, or WhatsApp) regardless of which channel you are currently operating in.
---

# Cross-Chat Memory

Every conversation — whether from the **web dashboard**, **Telegram**, or **WhatsApp** — is stored in a single SQLite database at `~/.nanobot/chat.db`. This skill teaches you to query it so that knowledge from one channel is fully available in another.

## When to Use This Skill

Activate this skill whenever:
- The user refers to something discussed previously ("remember when we talked about…", "like we discussed", "from our earlier chat", "what did we say about…")
- The user asks you to act on something from Telegram while you're in web chat, or vice versa
- The user asks what was said on WhatsApp
- A request seems to have missing context that a recent conversation would explain
- The user says "you should know this already" — they're probably right, search first

**Do not ask the user to repeat themselves.** Search the DB proactively before responding.

## Database Location

```
~/.nanobot/chat.db
```

## Schema

### Web chat conversations (`conversations` + `messages`)

```sql
-- List recent conversations (newest first)
SELECT id, title, updated_at, message_count FROM conversations ORDER BY updated_at DESC LIMIT 20;

-- Search web chat messages by keyword
SELECT c.title, m.role, m.content, m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.content LIKE '%<keyword>%'
ORDER BY m.created_at DESC
LIMIT 20;
```

### Telegram messages (`telegram_messages`)

```sql
-- Recent Telegram conversation (newest first)
SELECT direction, sender_name, content, created_at FROM telegram_messages
ORDER BY id DESC LIMIT 40;

-- Search Telegram messages by keyword
SELECT direction, sender_name, content, created_at FROM telegram_messages
WHERE content LIKE '%<keyword>%'
ORDER BY id DESC LIMIT 20;
```

### WhatsApp messages (`whatsapp_messages`)

```sql
-- Recent WhatsApp messages (newest first)
SELECT direction, phone_number, content, created_at FROM whatsapp_messages
ORDER BY id DESC LIMIT 40;

-- Search WhatsApp messages by keyword
SELECT direction, phone_number, content, created_at FROM whatsapp_messages
WHERE content LIKE '%<keyword>%'
ORDER BY id DESC LIMIT 20;

-- Messages since a specific time (use for batch summaries)
SELECT direction, phone_number, content, created_at FROM whatsapp_messages
WHERE created_at > datetime(<unix_ts>, 'unixepoch')
ORDER BY id ASC;
```

## Canonical Query Script

Run this to do a cross-channel keyword search in one shot (web + Telegram + WhatsApp):

```bash
python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py <keyword>
# e.g.:
python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py "gwm tank"
python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py flight --full
```

Or inline:

```python
exec("""
import sqlite3
from pathlib import Path
conn = sqlite3.connect(str(Path.home() / '.nanobot/chat.db'))
rows = conn.execute("SELECT role, substr(content,1,400) FROM messages WHERE lower(content) LIKE '%gwm%' ORDER BY created_at DESC LIMIT 5").fetchall()
conn.close()
for r in rows: print(r[0], ':', r[1], '\\n---')
""")
```

## Context-Aware Recall

When the user gives you a vague cross-channel reference, identify the most likely keyword(s) from their current message and search immediately. Present what you find concisely before responding to the actual request — don't wait to be asked twice.

If nothing is found, say so briefly and continue.
