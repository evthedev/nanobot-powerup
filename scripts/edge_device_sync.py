#!/usr/bin/env python3 -u
"""
Edge device bridge sync — DETERMINISTIC, VERSION-CONTROLLED.

Copy this file into your edge device. Do not modify the sync logic.
Workflow: poll (telemetry=[] ONLY) → drain directives → extract reply → send to PicoClaw → sleep → repeat.

CRITICAL: telemetry MUST be empty for routine polls. Zero tokens.
Only add {"kind": "message", "content": "..."} when the user actually speaks.

reply: directives are extracted and sent to PicoClaw via PICOCLAW_REPLY_CMD.
Other directives (wake, walk forward, etc.) — override process_directive for robot commands.

Version: 1.0.0
Bridge: https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com
"""
from typing import Optional
import hashlib
import hmac
import json
import os
import shlex
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# ── CONFIG (edit per device) ─────────────────────────────────────────────────
BRIDGE_URL = os.environ.get("BRIDGE_URL") or "https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com"
DEVICE_ID = os.environ.get("DEVICE_ID") or "spidey"
DEVICE_SECRET = os.environ.get("DEVICE_SECRET") or "Nb9kQmX3pL7!"
LOG_PATH = os.path.expanduser(os.environ.get("EDGE_SYNC_LOG") or "~/.edge-sync/directives.log")
# Command to send text to PicoClaw as a message prompt.
# Default: picoclaw agent -m "{text}"  (one-shot, no interactive shell needed)
# Override with PICOCLAW_REPLY_CMD env var if your setup differs.
PICOCLAW_REPLY_CMD = os.environ.get("PICOCLAW_REPLY_CMD", 'picoclaw agent -m "{text}"')
# ─────────────────────────────────────────────────────────────────────────────

# No /bridge suffix. No trailing slash.
BRIDGE_URL = BRIDGE_URL.rstrip("/")


def _signed_post(path: str, payload: dict) -> dict:
    """POST to bridge with HMAC. Raises on error."""
    body = json.dumps(payload).encode()
    sig = hmac.new(DEVICE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"{BRIDGE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        method="POST",
    )
    # Only pass SSL context for HTTPS; HTTP hangs on some Python versions with an SSL ctx
    kwargs: dict = {"timeout": 15}
    if BRIDGE_URL.startswith("https://"):
        kwargs["context"] = _SSL_CTX
    with urllib.request.urlopen(req, **kwargs) as resp:
        return json.loads(resp.read().decode())


def sync(telemetry: Optional[list] = None) -> dict:
    """
    Poll the bridge. Returns {directives, poll_interval_seconds, context, ...}.

    telemetry: [] for routine poll (ZERO TOKENS). Only add
    [{"kind": "message", "content": "..."}] when user actually speaks.
    """
    payload = {
        "status": {"daemon": "running"},
        "telemetry": telemetry if telemetry is not None else [],
    }
    return _signed_post(f"/api/devices/{DEVICE_ID}/sync", payload)


def _log_directive(cmd: str) -> None:
    """Append directive to log file for later inspection."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {cmd}\n")
    except OSError:
        pass


def _send_to_picoclaw(text: str) -> None:
    """
    Send reply text to PicoClaw. Set PICOCLAW_REPLY_CMD:
    - Template: 'picoclaw tts "{text}"' — {text} replaced, then run via shell
    - Or prefix: 'picoclaw tts' — text appended as final arg (no shell, safer)
    """
    if not PICOCLAW_REPLY_CMD:
        return
    try:
        if "{text}" in PICOCLAW_REPLY_CMD:
            cmd_str = PICOCLAW_REPLY_CMD.replace("{text}", text)
            subprocess.run(shlex.split(cmd_str), timeout=30, capture_output=True)
        else:
            parts = shlex.split(PICOCLAW_REPLY_CMD) + [text]
            subprocess.run(parts, timeout=30, capture_output=True)
    except (subprocess.TimeoutExpired, OSError):
        pass


def process_directive(cmd: str) -> None:
    """
    Poll → drain → extract → send to PicoClaw.
    reply:<text> → strip prefix, send text to PicoClaw.
    Any other directive → send raw text directly to PicoClaw as a message.
    PicoClaw handles all interpretation (TTS, LLM calls, robot SDK, etc.).
    """
    _log_directive(cmd)
    if cmd.startswith("reply:"):
        text = cmd[len("reply:"):].strip()
        print("Agent:", text, flush=True)
        _send_to_picoclaw(text)
    else:
        print("Directive:", cmd, flush=True)
        _send_to_picoclaw(cmd)


def run_once(user_message: Optional[str] = None) -> dict:
    """
    Single sync cycle. If user_message is set, sends it (uses tokens).
    Otherwise telemetry=[] (zero tokens).
    """
    telemetry = [{"kind": "message", "content": user_message}] if user_message else []
    result = sync(telemetry)
    for d in result.get("directives", []):
        process_directive(d.get("command", ""))
    return result


POLL_INTERVAL = 5  # seconds — always poll every 5s, no tokens used


def poll_loop() -> None:
    """
    Infinite poll loop. ZERO TOKENS per cycle.
    telemetry is always [] — no message forwarding.
    Only process_directive() calls picoclaw and uses tokens.
    """
    backoff = 0
    cycle = 0
    while True:
        cycle += 1
        ts = time.strftime("%H:%M:%S")
        try:
            result = sync()  # telemetry=[] — no tokens
            directives = result.get("directives", [])
            backoff = 0
            if directives:
                print(f"[{ts}] poll #{cycle} — {len(directives)} directive(s)", flush=True)
            for d in directives:
                process_directive(d.get("command", ""))
        except urllib.error.HTTPError as e:
            body = (e.fp.read() if e.fp else b"").decode(errors="replace")
            print(f"[{ts}] poll #{cycle} ERROR {e.code}: {body}", flush=True)
            backoff = min(backoff + 30, 300)
        except Exception as e:
            print(f"[{ts}] poll #{cycle} ERROR: {e}", flush=True)
            backoff = min(backoff + 30, 300)
        time.sleep(POLL_INTERVAL + backoff)


if __name__ == "__main__":
    # --once: single sync, exit. With message arg: send (tokens), then exit.
    # Default: infinite poll loop (ZERO TOKENS per cycle).
    args = sys.argv[1:]
    if "--once" in args:
        args.remove("--once")
        msg = " ".join(args).strip() or None
        run_once(msg)
    else:
        poll_loop()
