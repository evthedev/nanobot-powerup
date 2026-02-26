#!/usr/bin/env python3
"""One-time migration: replace hardcoded localhost:3001 screenshot URLs with relative paths.

Safe to run multiple times (idempotent) — only patches rows that contain the old URL.
Called by deploy.yml after every deploy to ensure all existing messages use relative paths.
"""
import sqlite3
import sys
import os

DB_PATH = os.environ.get("DB_PATH", "/opt/nanobot/chat.db")

if not os.path.exists(DB_PATH):
    print(f"migrate_db: {DB_PATH} not found — skipping (likely fresh instance)")
    sys.exit(0)

OLD = "http://localhost:3001/api/screenshots/"
NEW = "/api/screenshots/"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Find rows needing update
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
if not cur.fetchone():
    print("migrate_db: 'messages' table not found — skipping")
    conn.close()
    sys.exit(0)

cur.execute("SELECT COUNT(*) FROM messages WHERE content LIKE ?", (f"%{OLD}%",))
(count,) = cur.fetchone()

if count == 0:
    print(f"migrate_db: no rows contain old localhost URL — nothing to do")
    conn.close()
    sys.exit(0)

cur.execute(
    "UPDATE messages SET content = REPLACE(content, ?, ?) WHERE content LIKE ?",
    (OLD, NEW, f"%{OLD}%"),
)
conn.commit()
print(f"migrate_db: patched {cur.rowcount} message(s) — replaced '{OLD}' with '{NEW}'")
conn.close()
