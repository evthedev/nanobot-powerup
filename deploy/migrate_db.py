#!/usr/bin/env python3
"""Idempotent DB migrations run on every deploy.

1. Replace hardcoded localhost:3001 screenshot URLs with relative paths.
2. Migrate reachy_sync_log → edge_sync_log (add device_id column, copy rows).
"""
import sqlite3
import sys
import os

DB_PATH = os.environ.get("DB_PATH", "/opt/nanobot/chat.db")

if not os.path.exists(DB_PATH):
    print(f"migrate_db: {DB_PATH} not found — skipping (likely fresh instance)")
    sys.exit(0)

# ── Migration 1: localhost screenshot URLs ────────────────────────────────────
OLD = "http://localhost:3001/api/screenshots/"
NEW = "/api/screenshots/"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
if not cur.fetchone():
    print("migrate_db: 'messages' table not found — skipping URL migration")
else:
    cur.execute("SELECT COUNT(*) FROM messages WHERE content LIKE ?", (f"%{OLD}%",))
    (count,) = cur.fetchone()
    if count == 0:
        print("migrate_db: no rows contain old localhost URL — nothing to do")
    else:
        cur.execute(
            "UPDATE messages SET content = REPLACE(content, ?, ?) WHERE content LIKE ?",
            (OLD, NEW, f"%{OLD}%"),
        )
        conn.commit()
        print(f"migrate_db: patched {cur.rowcount} message(s) — replaced '{OLD}' with '{NEW}'")

conn.close()

# ── Migration 2: reachy_sync_log → edge_sync_log ─────────────────────────────
conn2 = sqlite3.connect(DB_PATH)
cur2 = conn2.cursor()

cur2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edge_sync_log'")
if not cur2.fetchone():
    cur2.execute("""
        CREATE TABLE edge_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL DEFAULT 'reachy',
            direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reachy_sync_log'")
    if cur2.fetchone():
        cur2.execute("""
            INSERT INTO edge_sync_log (id, device_id, direction, event_type, payload, created_at)
            SELECT id, 'reachy', direction, event_type, payload, created_at
            FROM reachy_sync_log
        """)
        print(f"migrate_db: edge_sync_log created, copied {cur2.rowcount} rows from reachy_sync_log")
    else:
        print("migrate_db: edge_sync_log created (no reachy_sync_log to migrate)")
    conn2.commit()
else:
    print("migrate_db: edge_sync_log already exists — skipping")

conn2.close()

# ── Migration 3: activity_log table ──────────────────────────────────────────
conn3 = sqlite3.connect(DB_PATH)
cur3 = conn3.cursor()

cur3.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='activity_log'")
if not cur3.fetchone():
    cur3.execute("""
        CREATE TABLE activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            sender TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur3.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON activity_log (created_at)")
    print("migrate_db: activity_log created")
    conn3.commit()
else:
    print("migrate_db: activity_log already exists — skipping")

conn3.close()
