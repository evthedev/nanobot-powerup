# Edge Device Integration Guide

Connect any edge device (camera, sensor node, robot, etc.) to the nanobot AI agent via the edge bridge.

---

## How it works

```
Your device  ──POST /api/devices/{id}/sync──►  Bridge  ──WebSocket──►  Agent
             ◄──directives──                            ◄──reply──

             ── OR ──

Your device  ══WS /api/devices/{id}/stream══►  Bridge  ──WebSocket──►  Agent
             ◄──streaming deltas──
```

Two integration modes:

| Mode | Latency | Best for |
|------|---------|----------|
| **HTTP sync** (poll) | 30–60s round-trip | Battery-constrained devices, simple command/reply |
| **WebSocket stream** | Real-time | Devices that need instant responses |

---

## Prerequisites

Get these from your deploy operator:

| Variable | Example |
|----------|---------| 
| `BRIDGE_URL` | `https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com` |
| `DEVICE_ID` | `my-device` (any unique string — unknown devices auto-register on first sync) |
| `DEVICE_SECRET` | shared HMAC secret (get from deploy operator) |

---

## Mode 1 — HTTP Sync (Poll)

### Request

```
POST <BRIDGE_URL>/api/devices/<DEVICE_ID>/sync
Content-Type: application/json
X-Bridge-Signature: <hmac-sha256-hex>
```

```json
{
  "status": {
    "daemon": "running",
    "conversation_app": "running",
    "firmware": "1.2.3"
  },
  "telemetry": [
    {"kind": "message", "content": "Good morning! What's on the agenda today?"},
    {"kind": "event",   "type": "motion_detected", "zone": "front"},
    {"kind": "metric",  "name": "cpu_temp", "value": 42.1}
  ]
}
```

### Telemetry kinds

| `kind` | Purpose | Required fields |
|--------|---------|-----------------|
| `message` | Send a message to the agent | `content` |
| `event` | Report a discrete event | `type` |
| `metric` | Report a numeric measurement | `name`, `value` |
| `snapshot` | Report a state snapshot | any fields |

Only `message` items are forwarded to the agent. Other kinds are logged for the activity digest.

### Response

```json
{
  "status": "synced",
  "directives": [
    {"command": "reply:Good morning! You have physio at 10am.", "queued_at": 1718000000.0},
    {"command": "wake", "queued_at": 1718000001.0}
  ],
  "context": [
    {"source": "telegram", "sender": "Shantelle", "summary": "Remind me about dinner at 7pm", "at": "2026-03-11 05:49:40"}
  ],
  "poll_interval_seconds": 30
}
```

`directives` is **drained on every sync** — each directive delivered exactly once.

`context` contains recent activity from other channels (web, Telegram) since your last sync. Use it to keep the device aware of what's happening elsewhere.

`poll_interval_seconds` — use this as your sleep interval between syncs.

### Directives

| Command | What to do |
|---------|------------|
| `reply:<text>` | Strip prefix, speak/display the text |
| `wake` | Wake hardware |
| `sleep` | Enter sleep mode |
| `restart_app` | Restart conversation process |
| `restart_device` | Full device restart |
| `set_volume` | Adjust volume |
| `capture_frame` | Capture and return a camera frame |

```python
for d in result["directives"]:
    cmd = d["command"]
    if cmd.startswith("reply:"):
        speak(cmd[len("reply:"):])
    elif cmd == "wake":
        wake_hardware()
    elif cmd == "capture_frame":
        send_frame_on_next_sync()
    else:
        print(f"Unknown directive (ignored): {cmd}")
```

### HMAC signing

```python
import hashlib, hmac, json

body = json.dumps(payload).encode()
sig = hmac.new(DEVICE_SECRET.encode(), body, hashlib.sha256).hexdigest()
headers = {"Content-Type": "application/json", "X-Bridge-Signature": sig}
```

Missing or invalid signature → `401 Unauthorized`.

### Full example (Python)

```python
import hashlib, hmac, json, time, os
import requests

BRIDGE_URL    = os.environ["BRIDGE_URL"]
DEVICE_ID     = os.environ["DEVICE_ID"]
DEVICE_SECRET = os.environ["DEVICE_SECRET"]

_pending_telemetry = []

def signed_post(path, payload):
    body = json.dumps(payload).encode()
    sig = hmac.new(DEVICE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return requests.post(
        f"{BRIDGE_URL}{path}", data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        timeout=15,
    ).json()

def handle_directive(cmd):
    if cmd.startswith("reply:"):
        speak(cmd[len("reply:"):])
    elif cmd == "wake":
        wake_hardware()
    elif cmd == "sleep":
        sleep_hardware()
    elif cmd == "capture_frame":
        _pending_telemetry.append({"kind": "snapshot", "frame": capture_camera()})
    else:
        print(f"Unknown directive (ignored): {cmd}")

poll_interval = 30
while True:
    try:
        telemetry, _pending_telemetry[:] = _pending_telemetry[:], []
        result = signed_post(f"/api/devices/{DEVICE_ID}/sync", {
            "status": {"daemon": "running", "firmware": "1.0.0"},
            "telemetry": telemetry,
        })
        for d in result.get("directives", []):
            handle_directive(d["command"])
        poll_interval = result.get("poll_interval_seconds", 30)
    except Exception as e:
        print(f"Sync error: {e}")
    time.sleep(poll_interval)
```

To send a message to the agent:
```python
_pending_telemetry.append({"kind": "message", "content": "The user just said: hello!"})
```

---

## Mode 2 — WebSocket Stream

For real-time bidirectional communication. See `PICO_PROTOCOL.md` for the full wire format.

### Connect

```
WS <BRIDGE_URL>/api/devices/<DEVICE_ID>/stream
Authorization: Bearer <DEVICE_SECRET>
```

On connect the server sends a `hello` frame. On bad/missing secret: connection closed with 1008.

### Send a message

```json
{"type": "message.send", "id": "<uuid>", "ts": <unix_ms>, "content": "turn on the lights"}
```

### Receive response (streaming)

```json
{"type": "message.create", "id": "...", "ts": ..., "content": "Done,", "done": false}
{"type": "message.create", "id": "...", "ts": ..., "content": " lights are on.", "done": false}
{"type": "message.create", "id": "...", "ts": ..., "content": "", "done": true}
```

Concatenate `content` deltas. `done: true` signals turn complete.

### Keepalive

```json
{"type": "ping", "id": "<uuid>", "ts": <unix_ms>}
```

Server replies with `{"type": "pong", "id": "<your-id>", ...}`. Send every 30s.

### Quick example (Python)

```python
import asyncio, json, uuid, time
import websockets

BRIDGE_URL    = "wss://ec2-xxx.compute.amazonaws.com"
DEVICE_ID     = "my-device"
DEVICE_SECRET = "your-secret"

async def stream():
    uri = f"{BRIDGE_URL}/api/devices/{DEVICE_ID}/stream"
    async with websockets.connect(uri, extra_headers={"Authorization": f"Bearer {DEVICE_SECRET}"}) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "hello"

        # Send a message
        await ws.send(json.dumps({"type": "message.send", "id": str(uuid.uuid4()), "ts": int(time.time()*1000), "content": "What time is it?"}))

        # Collect response
        reply = []
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "message.create":
                reply.append(msg["content"])
                if msg.get("done"):
                    break
        print("Agent:", "".join(reply))

asyncio.run(stream())
```

---

## Legacy endpoints (backward compat)

The old `pending_feedback` / `pending_commands` field names still work:

```json
{"status": {...}, "telemetry": [{"kind": "message", "content": "hello"}]}
```

Response still includes `pending_commands` and `knowledge_update` alongside the new names. Migrate when convenient.

Legacy sync endpoint also still works: `POST /api/sync` → routes to the default device.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | `DEVICE_SECRET` mismatch | Confirm secret with operator |
| `401 Unauthorized` on new device | nginx missing `auth_basic off` for `/api/devices/` | Ensure nginx config has the `/api/devices/` block (deploy from latest `main`) |
| Connection refused | Wrong `BRIDGE_URL` | Use the bare EC2 hostname — no `/bridge` suffix |
| `directives` always empty | Agent not replying | Check `telemetry` contains `kind=message` items |
| Reply never acted on | Missing `reply:` handler | Add it — see directive table above |
| WS closes immediately | Bad `Authorization` header | Use `Bearer <secret>` format |
| Context always empty | First sync ever | Context populates from second sync onward |
