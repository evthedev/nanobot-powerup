#!/usr/bin/env python3
"""
Query recent WhatsApp messages since the last heartbeat check.

Usage:
    python3 query_recent.py                  # since last heartbeat check
    python3 query_recent.py --minutes 60     # last N minutes
    python3 query_recent.py --all            # all messages (last 50)

Output is designed to be read by the agent in the heartbeat context.
If no new messages, prints: NO_NEW_WHATSAPP_MESSAGES
"""

import sys
import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone

DB = Path.home() / ".nanobot" / "chat.db"
STATE_FILE = Path.home() / ".nanobot" / "workspace" / "heartbeat-state.json"


def load_last_check() -> int:
    """Return unix timestamp of last whatsapp check (0 = never)."""
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            return int(state.get("whatsapp", 0))
        except Exception:
            pass
    return 0


def run(since_ts: int | None = None, limit: int = 50) -> None:
    if not DB.exists():
        print(f"Database not found: {DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Check table exists
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='whatsapp_messages'"
    ).fetchone()
    if not has_table:
        print("NO_NEW_WHATSAPP_MESSAGES")
        conn.close()
        return

    if since_ts is not None and since_ts > 0:
        since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute("""
            SELECT direction, phone_number, content, created_at
            FROM whatsapp_messages
            WHERE created_at > ?
            ORDER BY id ASC
            LIMIT ?
        """, (since_dt, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT direction, phone_number, content, created_at
            FROM whatsapp_messages
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        rows = list(reversed(rows))

    conn.close()

    if not rows:
        print("NO_NEW_WHATSAPP_MESSAGES")
        return

    print(f"=== WhatsApp — {len(rows)} new message(s) ===")
    for r in rows:
        label = r["phone_number"] if r["phone_number"] else r["direction"]
        direction_tag = "→ nanobot" if r["direction"] == "inbound" else "← nanobot"
        content_preview = r["content"][:300].replace("\n", " ")
        print(f"[{r['created_at']}] {direction_tag} ({label}): {content_preview}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    all_mode = "--all" in args

    minutes: int | None = None
    if "--minutes" in args:
        idx = args.index("--minutes")
        try:
            minutes = int(args[idx + 1])
        except (IndexError, ValueError):
            minutes = 60

    if all_mode:
        run(since_ts=None, limit=50)
    elif minutes is not None:
        since = int(time.time()) - minutes * 60
        run(since_ts=since)
    else:
        since = load_last_check()
        run(since_ts=since)
