#!/usr/bin/env python3
"""Idempotent cron job migrations run on every deploy.

Migration 1: Convert agent_turn jobs whose payload is a shell command into
exec jobs so they run directly without an LLM call.

Migration 2: Disable agent_turn jobs whose message is exactly "edge sync".
Those are redundant with the exec job that runs the sync script and cause
an LLM call every minute.

Migration 3: Fix malformed jobs — agent_turn with command set should be exec.

Migration 4: Deduplicate exec jobs — keep one per unique command, remove rest.
"""
import json
import os
import sys
from pathlib import Path

# Must match nanobot.cron.types.SHELL_PREFIXES — kept local to avoid pulling in nanobot
# (deploy runs this before/without full nanobot deps e.g. loguru)
_SHELL_PREFIXES = ("python3 ", "python ", "bash ", "sh ", "node ", "npx ", "/usr/bin/", "/usr/local/bin/")

CRON_PATH = os.environ.get("CRON_PATH", "/opt/nanobot/cron/jobs.json")
_EDGE_SYNC_MESSAGE = "edge sync"

if not os.path.exists(CRON_PATH):
    print(f"migrate_cron: {CRON_PATH} not found — skipping (likely fresh instance)")
    sys.exit(0)

data = json.loads(Path(CRON_PATH).read_text())
jobs = data.get("jobs", [])
changed = 0

# ── Migrations 1–3: fix individual jobs ─────────────────────────────────────
for job in jobs:
    payload = job.get("payload", {})

    # Migration 3: malformed — agent_turn but command is set (should be exec)
    if payload.get("kind") == "agent_turn" and (payload.get("command") or "").strip():
        payload["kind"] = "exec"
        payload["message"] = ""
        job["payload"] = payload
        changed += 1
        print(f"migrate_cron: fixed malformed job '{job.get('id', '?')}' → exec")
        continue

    if payload.get("kind") != "agent_turn":
        continue
    message = (payload.get("message") or "").strip()

    # Migration 1: shell command → exec
    if any(message.startswith(p) for p in _SHELL_PREFIXES):
        payload["kind"] = "exec"
        payload["command"] = message
        payload["message"] = ""
        job["payload"] = payload
        changed += 1
        print(f"migrate_cron: converted job '{job.get('id', '?')}' ({job.get('name', job.get('id', '?'))!r}) → exec")
        continue

    # Migration 2: redundant "edge sync" agent_turn → disable
    if message == _EDGE_SYNC_MESSAGE and job.get("enabled", True):
        job["enabled"] = False
        state = job.get("state") or {}
        state["nextRunAtMs"] = None
        job["state"] = state
        changed += 1
        print(f"migrate_cron: disabled job '{job.get('id', '?')}' ({job.get('name', job.get('id', '?'))!r}) — redundant with exec edge-sync")

# ── Migration 4: deduplicate exec jobs (same command → keep first) ───────────
seen_commands = {}
to_remove = []
for i, job in enumerate(jobs):
    payload = job.get("payload", {})
    if payload.get("kind") != "exec":
        continue
    cmd = (payload.get("command") or "").strip()
    if not cmd:
        continue
    # Normalise for comparison: strip trailing redirect variations
    key = cmd.split(">>")[0].strip() if ">>" in cmd else cmd
    if key in seen_commands:
        to_remove.append(i)
        changed += 1
        print(f"migrate_cron: removed duplicate exec job '{job.get('id', '?')}' (same as {seen_commands[key]})")
    else:
        seen_commands[key] = job.get("id", "?")

for i in reversed(to_remove):
    jobs.pop(i)
data["jobs"] = jobs

if changed:
    Path(CRON_PATH).write_text(json.dumps(data, indent=2))
    print(f"migrate_cron: {changed} job(s) updated")
else:
    print("migrate_cron: no agent_turn shell jobs or edge sync jobs found — nothing to do")
