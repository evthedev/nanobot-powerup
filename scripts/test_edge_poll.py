#!/usr/bin/env python3
"""
Test edge bridge poll + receive flow.

1. Queue a message via bridge command API (simulates dashboard sending)
2. Poll via sync endpoint (simulates Jethexa spider)
3. Assert the poller receives the queued message

Usage:
    python scripts/test_edge_poll.py
    BRIDGE_URL=http://localhost:18790 DEVICE_ID=test-poll-device python scripts/test_edge_poll.py
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://localhost:18790")
DEVICE_ID = os.environ.get("DEVICE_ID", "test-poll-device")
DEVICE_SECRET = os.environ.get("DEVICE_SECRET", "")  # empty when device auto-created


def sync(bridge_url: str, device_id: str, secret: str, telemetry: list | None = None) -> dict:
    """Poll the bridge sync endpoint. Returns response JSON with directives."""
    payload = {
        "status": {"daemon": "running", "test": "poll"},
        "telemetry": telemetry or [],
    }
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        f"{bridge_url}/api/devices/{device_id}/sync",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def queue_command(bridge_url: str, device_id: str, command: str) -> dict:
    """Queue a directive for the device (simulates dashboard send)."""
    body = json.dumps({"command": command}).encode()
    req = urllib.request.Request(
        f"{bridge_url}/api/devices/{device_id}/command",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    print(f"Bridge: {BRIDGE_URL}  Device: {DEVICE_ID}")
    print("-" * 50)

    # 1. Queue a test message (simulates dashboard / bridge sending to device)
    test_command = "walk forward and wave"
    print(f"1. Queuing command: {test_command!r}")
    try:
        qr = queue_command(BRIDGE_URL, DEVICE_ID, test_command)
        print(f"   Response: {qr}")
    except urllib.error.HTTPError as e:
        print(f"   ERROR: {e.code} {e.reason}")
        if e.fp:
            print(f"   Body: {e.fp.read().decode()}")
        return 1

    # 2. Poll sync and drain directives
    print("\n2. Polling sync (device drains queue)...")
    try:
        result = sync(BRIDGE_URL, DEVICE_ID, DEVICE_SECRET)
    except urllib.error.HTTPError as e:
        print(f"   ERROR: {e.code} {e.reason}")
        if e.fp:
            print(f"   Body: {e.fp.read().decode()}")
        return 1

    directives = result.get("directives", [])
    print(f"   Directives received: {len(directives)}")
    for i, d in enumerate(directives):
        print(f"     [{i}] {d.get('command', d)!r}")

    # 3. Assert we received our message
    commands = [d.get("command", d) for d in directives if isinstance(d, dict)]
    commands = commands + [d for d in directives if isinstance(d, str)]

    if test_command not in commands:
        print(f"\nFAIL: Expected directive {test_command!r} in {commands}")
        return 1

    print(f"\nPASS: Poller received queued message {test_command!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
