#!/usr/bin/env python3
"""
Cross-channel keyword search across web chat + Telegram.

Usage:
    python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py <keyword>
    python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py "gwm tank"
    python3 ~/.nanobot/workspace/skills/cross-chat-memory/query.py tank --full

Flags:
    --full      Print full message content (default: 400-char snippet)
    --limit N   Max results per channel (default: 10)
"""

import sys
import sqlite3
from pathlib import Path

DB = Path.home() / ".nanobot" / "chat.db"

def run(keyword: str, full: bool = False, limit: int = 10) -> None:
    if not DB.exists():
        print(f"Database not found: {DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    snippet_len = 9999 if full else 400
    kw = f"%{keyword}%"

    # ── Web chat ──────────────────────────────────────────────────────────
    web_rows = conn.execute(f"""
        SELECT c.title, m.role, substr(m.content, 1, {snippet_len}) AS snippet, m.created_at
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE lower(m.content) LIKE lower(?)
        ORDER BY m.created_at DESC
        LIMIT ?
    """, (kw, limit)).fetchall()

    # ── Telegram ──────────────────────────────────────────────────────────
    tg_rows = conn.execute(f"""
        SELECT direction, sender_name, substr(content, 1, {snippet_len}) AS snippet, created_at
        FROM telegram_messages
        WHERE lower(content) LIKE lower(?)
        ORDER BY id DESC
        LIMIT ?
    """, (kw, limit)).fetchall()

    conn.close()

    print(f"=== Web chat — {len(web_rows)} hit(s) for '{keyword}' ===")
    for r in web_rows:
        print(f"[{r['created_at']}] [{r['title']}] {r['role']}:")
        print(f"  {r['snippet']}")
        print()

    print(f"=== Telegram — {len(tg_rows)} hit(s) for '{keyword}' ===")
    for r in tg_rows:
        name = r['sender_name'] or r['direction']
        print(f"[{r['created_at']}] {r['direction']} ({name}):")
        print(f"  {r['snippet']}")
        print()

    if not web_rows and not tg_rows:
        print("No results found.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = sys.argv[1:]
    if not args:
        print("Usage: query.py <keyword> [--full] [--limit N]")
        sys.exit(1)

    keyword = " ".join(args)
    full = "--full" in flags
    limit = 10
    if "--limit" in flags:
        idx = flags.index("--limit")
        try:
            limit = int(flags[idx + 1])
        except (IndexError, ValueError):
            pass

    run(keyword, full=full, limit=limit)
