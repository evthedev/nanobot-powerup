#!/usr/bin/env python3
"""Idempotent cron job migrations run on every deploy.

Migration 1: Convert agent_turn jobs whose payload is a shell command into
exec jobs so they run directly without an LLM call.

Migration 2: Disable agent_turn jobs whose message is exactly "edge sync".
Those are redundant with the exec job that runs the sync script and cause
an LLM call every minute.
"""
import json
import os
import sys
from pathlib import Path

# Ensure we can import from nanobot (single source of truth for SHELL_PREFIXES)
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from nanobot.cron.types import SHELL_PREFIXES

CRON_PATH = os.environ.get("CRON_PATH", "/opt/nanobot/cron/jobs.json")
_EDGE_SYNC_MESSAGE = "edge sync"

if not os.path.exists(CRON_PATH):
    print(f"migrate_cron: {CRON_PATH} not found — skipping (likely fresh instance)")
    sys.exit(0)

data = json.loads(Path(CRON_PATH).read_text())
changed = 0

for job in data.get("jobs", []):
    payload = job.get("payload", {})
    if payload.get("kind") != "agent_turn":
        continue
    message = (payload.get("message") or "").strip()

    # Migration 1: shell command → exec
    if any(message.startswith(p) for p in SHELL_PREFIXES):
        payload["kind"] = "exec"
        payload["command"] = message
        payload["message"] = ""
        job["payload"] = payload
        changed += 1
        print(f"migrate_cron: converted job '{job['id']}' ({job['name']!r}) → exec")
        continue

    # Migration 2: redundant "edge sync" agent_turn → disable
    if message == _EDGE_SYNC_MESSAGE and job.get("enabled", True):
        job["enabled"] = False
        state = job.get("state") or {}
        state["nextRunAtMs"] = None
        job["state"] = state
        changed += 1
        print(f"migrate_cron: disabled job '{job['id']}' ({job['name']!r}) — redundant with exec edge-sync")

if changed:
    Path(CRON_PATH).write_text(json.dumps(data, indent=2))
    print(f"migrate_cron: {changed} job(s) updated")
else:
    print("migrate_cron: no agent_turn shell jobs or edge sync jobs found — nothing to do")
