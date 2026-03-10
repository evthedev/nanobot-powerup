# PicoClaw → Bridge Integration

Connect your PicoClaw-powered edge device (e.g. Reachy Mini) to the nanobot Reachy bridge. The bridge queues commands from Shantelle; your device polls to pick them up.

---

## Prerequisites

Get these from whoever runs the bridge (your deploy operator):

| Variable | Description |
|----------|-------------|
| `BRIDGE_URL` | Full base URL including scheme and path (e.g. `https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com/picoclaw`) |
| `BRIDGE_SECRET` | Shared secret for HMAC signing. Must match the bridge's `BRIDGE_SECRET`. |

---

## Architecture

```
Boss (WhatsApp) → Shantelle → Bridge (queues commands)
                                    ▲
PicoClaw (polls every ~30s) ────────┘  POST <BRIDGE_URL>/api/sync
```

Communication is **polling, not push**. Your device POSTs to `/api/sync` every ~30 seconds to report status and receive pending commands.

---

## Sync cycle

Every ~30 seconds, POST to the bridge:

```
POST <BRIDGE_URL>/api/sync
Content-Type: application/json
X-Bridge-Signature: <hmac-sha256-hex>
```

**Request body:**
```json
{
  "reachy_status": {
    "daemon": "running",
    "conversation_app": "running",
    "picoclaw": "1.2.3"
  },
  "vision_status": null,
  "pending_facts": [],
  "pending_feedback": [],
  "local_memory": null
}
```

All fields are optional. Only `reachy_status` is used by the bridge currently.

**Response:**
```json
{
  "pending_commands": [
    {"command": "wake", "queued_at": 1718000000.0}
  ],
  "knowledge_update": [],
  "trust_config": {}
}
```

`pending_commands` is drained on each sync — commands are delivered exactly once. Execute each in order, then wait for the next cycle.

---

## HMAC signing

Every request must include `X-Bridge-Signature`:

```python
import hashlib, hmac, json

body = json.dumps(payload).encode()
sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
headers = {
    "Content-Type": "application/json",
    "X-Bridge-Signature": sig,
}
```

Missing or invalid signature → `401 Unauthorized`.

---

## Commands

| `command` | Meaning |
|-----------|---------|
| `wake` | Power on / wake from sleep |
| `sleep` | Power off / enter sleep mode |
| `restart_app` | Restart the conversation app only |

Log and ignore unknown commands.

---

## Minimal sync loop (Python)

```python
import hashlib, hmac, json, time, os
import requests

BRIDGE_URL = os.environ.get("BRIDGE_URL", "")   # e.g. https://ec2-xxx.compute.amazonaws.com/picoclaw
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")  # from operator
SYNC_INTERVAL = 30


def signed_post(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = requests.post(
        f"{BRIDGE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_reachy_status() -> dict:
    return {"daemon": "running", "conversation_app": "running", "picoclaw": "1.0.0"}


def execute_command(command: str) -> None:
    if command == "wake":
        pass  # power on hardware
    elif command == "sleep":
        pass  # power off hardware
    elif command == "restart_app":
        pass  # restart conversation process
    else:
        print(f"Unknown command: {command}")


while True:
    try:
        result = signed_post("/api/sync", {"reachy_status": get_reachy_status()})
        for cmd in result.get("pending_commands", []):
            execute_command(cmd["command"])
    except Exception as e:
        print(f"Sync failed: {e}")
    time.sleep(SYNC_INTERVAL)
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `401 Unauthorized` | `BRIDGE_SECRET` mismatch — confirm with operator |
| Connection refused / timeout | `BRIDGE_URL` wrong or unreachable — ask operator |
| Status shows "unknown" | Include `reachy_status` in your sync payload |
| Commands never arrive | Bridge may not be enabled — ask operator to verify |
