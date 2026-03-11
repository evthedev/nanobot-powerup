# Edge Device Integration Guide

Connect any edge device — robot, camera node, sensor cluster, voice terminal — to the nanobot AI agent via the edge bridge.

---

## Architecture

```
Internet
    │  HTTPS/WSS (port 443)
    ▼
 nginx  ──── /api/devices/*  ──── auth_basic OFF ──► Bridge :18790
    │                                                     │
    │  all other routes                          HMAC auth on sync
    ▼                                            Bearer auth on WS
 Dashboard :3001                                         │
    │                                                     │
    └──────────────── WebSocket ──────────────────► Gateway :18791
                                                       (agent)
```

nginx strips basic-auth for `/api/devices/*` — the bridge handles its own auth via HMAC or Bearer token. Everything else goes through the dashboard with HTTP basic auth.

---

## Two integration modes

| Mode | Transport | Auth | Latency | Best for |
|------|-----------|------|---------|----------|
| **HTTP sync** | `POST /api/devices/{id}/sync` | HMAC-SHA256 signature | 30–60s round-trip | Battery-constrained, simple poll/command |
| **WebSocket stream** | `WS /api/devices/{id}/stream` | Bearer token | Real-time | Voice terminals, interactive devices |

---

## Step 1 — Server-side setup

### 1a. Register the device in config.json

SSH into the server and edit `/opt/nanobot/config.json`:

```json
{
  "channels": {
    "edgeDevices": {
      "enabled": true,
      "url": "http://nanobot-whatsapp-bridge:18790",
      "devices": {
        "my-device": {
          "enabled": true,
          "secret": "choose-a-strong-random-secret",
          "pollIntervalSeconds": 30
        },
        "second-device": {
          "enabled": true,
          "secret": "different-secret-per-device",
          "pollIntervalSeconds": 60
        }
      }
    }
  }
}
```

> Both camelCase (`edgeDevices`, `pollIntervalSeconds`) and snake_case (`edge_devices`, `poll_interval_seconds`) are accepted.

### 1b. Restart the bridge

```bash
sudo docker restart nanobot-whatsapp-bridge
```

### 1c. Verify the device registered

```bash
curl -u admin:password https://<your-host>/api/devices
```

Expected:
```json
{
  "devices": [
    {"device_id": "my-device", "online": false, "last_seen": 0, "pending_directives": 0}
  ]
}
```

If the device list is empty, the config wasn't read — check the JSON is valid and restart again.

---

## Step 2 — Device-side credentials

| Variable | Example | Notes |
|----------|---------|-------|
| `BRIDGE_URL` | `https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com` | No trailing slash, no port |
| `DEVICE_ID` | `my-device` | Must match exactly what's in config.json |
| `DEVICE_SECRET` | `choose-a-strong-random-secret` | Must match the `secret` field in config.json |

**Important:** The `BRIDGE_URL` is the public HTTPS endpoint — nginx proxies it to the bridge container internally. You never connect directly to port 18790 from outside.

---

## Mode 1 — HTTP Sync (Poll)

### How it works

The device POSTs to the bridge on a fixed interval. Each sync:
1. Device sends its status + any telemetry (messages, events, metrics)
2. Bridge forwards `message`-kind telemetry to the agent
3. Agent's reply is queued as a `reply:<text>` directive
4. Directives are returned in the sync response and **drained** (delivered exactly once)
5. Bridge returns `context` — recent activity from other channels since last sync

### HMAC signing

Every sync request must include an `X-Bridge-Signature` header. This is an HMAC-SHA256 hex digest of the **raw request body** using `DEVICE_SECRET` as the key.

```python
import hashlib, hmac, json

body = json.dumps(payload).encode()   # must be the exact bytes you POST
sig  = hmac.new(DEVICE_SECRET.encode(), body, hashlib.sha256).hexdigest()
headers = {
    "Content-Type":       "application/json",
    "X-Bridge-Signature": sig,
}
```

Missing or wrong signature → `401 Unauthorized`.
No secret configured in config.json → auth bypassed (any request accepted).

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
    "firmware": "1.2.3",
    "battery_pct": 87
  },
  "telemetry": [
    {"kind": "message", "content": "Good morning! What's on the agenda?"},
    {"kind": "event",   "type": "motion_detected", "zone": "front_door"},
    {"kind": "metric",  "name": "cpu_temp", "value": 42.1}
  ]
}
```

### Telemetry kinds

| `kind` | Forwarded to agent? | Required fields |
|--------|-------------------|-----------------|
| `message` | ✅ Yes | `content` |
| `event` | ❌ Logged only | `type` |
| `metric` | ❌ Logged only | `name`, `value` |
| `snapshot` | ❌ Logged only | any |

### Response

```json
{
  "status": "synced",
  "directives": [
    {"command": "reply:Good morning! Physio at 10am, team meeting at 2pm.", "queued_at": 1741600000.0},
    {"command": "wake", "queued_at": 1741600001.0}
  ],
  "context": [
    {
      "source": "telegram",
      "sender": "Shantelle",
      "summary": "Remind me about dinner at 7pm",
      "at": "2026-03-11 05:49:40"
    }
  ],
  "poll_interval_seconds": 30
}
```

`directives` — drained on every sync. Process them all before sleeping.
`context` — activity from other channels (Telegram, web, other devices) since your last sync. Empty on first sync.
`poll_interval_seconds` — use this as your sleep interval. The server may change it.

### Directives reference

| Command | Action |
|---------|--------|
| `reply:<text>` | The agent's reply — strip prefix, speak or display the text |
| `wake` | Wake hardware from sleep |
| `sleep` | Enter sleep/low-power mode |
| `restart_app` | Restart the conversation process |
| `restart_picoclaw` | Restart the picoclaw service |
| `set_volume` | Adjust volume (value passed as `set_volume:<0-100>`) |
| `capture_frame` | Capture a camera frame and include it in next sync telemetry |

Unknown directives should be logged and ignored — new ones may be added without notice.

```python
def handle_directive(cmd):
    if cmd.startswith("reply:"):
        speak(cmd[len("reply:"):])
    elif cmd == "wake":
        wake_hardware()
    elif cmd == "sleep":
        sleep_hardware()
    elif cmd == "capture_frame":
        pending_telemetry.append({"kind": "snapshot", "frame": capture_camera()})
    elif cmd == "restart_app":
        restart_conversation_process()
    else:
        print(f"Unknown directive (ignored): {cmd}")
```

### Full working example (Python)

```python
import hashlib, hmac, json, time, os
import requests

BRIDGE_URL    = os.environ["BRIDGE_URL"]     # e.g. https://ec2-x.compute.amazonaws.com
DEVICE_ID     = os.environ["DEVICE_ID"]      # e.g. my-device
DEVICE_SECRET = os.environ["DEVICE_SECRET"]  # must match config.json

pending_telemetry = []

def signed_post(path, payload):
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig  = hmac.new(DEVICE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(
        f"{BRIDGE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        timeout=15,
        verify=False,  # remove if using a valid TLS cert
    )
    r.raise_for_status()
    return r.json()

def handle_directive(cmd):
    if cmd.startswith("reply:"):
        speak(cmd[len("reply:"):])
    elif cmd == "wake":
        wake_hardware()
    elif cmd == "sleep":
        sleep_hardware()
    elif cmd == "capture_frame":
        pending_telemetry.append({"kind": "snapshot", "frame": capture_camera()})
    else:
        print(f"Unknown directive (ignored): {cmd}")

# To send a message to the agent at next sync:
def send_message(text):
    pending_telemetry.append({"kind": "message", "content": text})

poll_interval = 30
while True:
    try:
        telemetry, pending_telemetry[:] = pending_telemetry[:], []
        result = signed_post(f"/api/devices/{DEVICE_ID}/sync", {
            "status": {"daemon": "running", "firmware": "1.0.0"},
            "telemetry": telemetry,
        })
        for d in result.get("directives", []):
            handle_directive(d["command"])
        poll_interval = result.get("poll_interval_seconds", poll_interval)
    except requests.HTTPError as e:
        print(f"HTTP {e.response.status_code}: {e.response.text}")
    except Exception as e:
        print(f"Sync error: {e}")
    time.sleep(poll_interval)
```

### Full working example (MicroPython / CircuitPython)

```python
import json, time, hashlib, hmac, binascii
import urequests as requests

BRIDGE_URL    = "https://ec2-x.compute.amazonaws.com"
DEVICE_ID     = "my-device"
DEVICE_SECRET = "choose-a-strong-random-secret"

def sign(body_bytes):
    h = hmac.new(DEVICE_SECRET.encode(), body_bytes, hashlib.sha256)
    return binascii.hexlify(h.digest()).decode()

def sync(telemetry=None):
    payload = json.dumps({"status": {"fw": "1.0"}, "telemetry": telemetry or []})
    body    = payload.encode()
    r = requests.post(
        f"{BRIDGE_URL}/api/devices/{DEVICE_ID}/sync",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sign(body)},
    )
    return json.loads(r.text)

while True:
    result = sync()
    for d in result.get("directives", []):
        print("Directive:", d["command"])
    time.sleep(result.get("poll_interval_seconds", 30))
```

---

## Mode 2 — WebSocket Stream

For real-time bidirectional communication. The device maintains a persistent WebSocket connection and sends/receives messages without polling delays.

### Connect

```
WS  <BRIDGE_URL>/api/devices/<DEVICE_ID>/stream
WSS <BRIDGE_URL>/api/devices/<DEVICE_ID>/stream   (use wss:// for HTTPS hosts)

Authorization: Bearer <DEVICE_SECRET>
```

On success: server sends a `hello` frame.
On bad/missing secret: server sends `{"type":"error","code":"auth_failed"}` then closes with code 1008.

### Wire format

All frames are JSON text frames with this envelope:

```json
{"type": "<string>", "id": "<uuid>", "ts": <unix_ms>}
```

Type-specific fields are at the top level. Ignore unknown `type` values — new ones may be added.

### Send a message

```json
{"type": "message.send", "id": "550e8400-...", "ts": 1741600000000, "content": "Turn on the lights"}
```

`content` is required and non-empty.

### Receive a response (streaming)

```json
{"type": "typing.start", "id": "...", "ts": ...}
{"type": "message.create", "id": "...", "ts": ..., "content": "Done,",      "done": false}
{"type": "message.create", "id": "...", "ts": ..., "content": " lights on.", "done": false}
{"type": "message.create", "id": "...", "ts": ..., "content": "",            "done": true}
{"type": "typing.stop",    "id": "...", "ts": ...}
```

Concatenate `content` deltas until `done: true`. Wait for `done: true` before sending the next `message.send`.

### Keepalive

Send a ping every 30s. If no pong within 10s, close and reconnect.

```json
→  {"type": "ping", "id": "...", "ts": ...}
←  {"type": "pong", "id": "<your-id-echoed>", "ts": ...}
```

### Error frame

```json
{"type": "error", "id": "...", "ts": ..., "code": "internal_error", "message": "agent loop failed"}
```

Error codes: `auth_failed`, `empty_content`, `internal_error`.
Connection stays open after non-auth errors. An error during a turn is always followed by `message.create {done: true}`.

### Full working example (Python)

```python
import asyncio, json, uuid, time, os
import websockets

BRIDGE_URL    = os.environ["BRIDGE_URL"].replace("https://", "wss://").replace("http://", "ws://")
DEVICE_ID     = os.environ["DEVICE_ID"]
DEVICE_SECRET = os.environ["DEVICE_SECRET"]

def frame(type_, **kwargs):
    return json.dumps({"type": type_, "id": str(uuid.uuid4()), "ts": int(time.time() * 1000), **kwargs})

async def stream():
    uri = f"{BRIDGE_URL}/api/devices/{DEVICE_ID}/stream"
    while True:
        try:
            async with websockets.connect(
                uri,
                extra_headers={"Authorization": f"Bearer {DEVICE_SECRET}"},
                ssl=True,
            ) as ws:
                hello = json.loads(await ws.recv())
                assert hello["type"] == "hello", f"Expected hello, got {hello}"
                print("Connected.")

                # Keepalive task
                async def ping_loop():
                    while True:
                        await asyncio.sleep(30)
                        await ws.send(frame("ping"))

                asyncio.create_task(ping_loop())

                # Example: send one message and print response
                await ws.send(frame("message.send", content="What time is it?"))
                reply_parts = []
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg["type"] == "message.create":
                        reply_parts.append(msg["content"])
                        if msg.get("done"):
                            print("Agent:", "".join(reply_parts))
                            reply_parts = []
                    elif msg["type"] == "pong":
                        pass  # keepalive ack
                    elif msg["type"] == "error":
                        print(f"Error: {msg.get('code')} — {msg.get('message')}")

        except Exception as e:
            print(f"Connection error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)

asyncio.run(stream())
```

---

## Checking device status

```bash
# List all registered devices and their online state
curl -u admin:password https://<your-host>/api/devices

# Single device status + pending directive queue
curl -u admin:password https://<your-host>/api/devices/my-device/status
```

`online` is `true` if the device synced within `poll_interval_seconds × 3`. A device is considered offline if it misses 3 consecutive polls.

---

## Queueing directives from the server (dashboard or agent)

The agent and dashboard can push directives to a device without waiting for a sync:

```bash
# Queue a directive via dashboard API (no auth required — internal only)
curl -X POST https://<your-host>/api/devices/my-device/command \
  -H "Content-Type: application/json" \
  -d '{"command": "wake"}'
```

Allowed directives: `wake`, `sleep`, `restart_app`, `restart_picoclaw`, `set_volume`, `capture_frame`.

The device receives them in the next sync response (HTTP mode) or immediately if connected via WebSocket stream.

---

## Migrating from legacy `reachy_bridge`

If your config.json has `channels.reachyBridge` (or `channels.reachy_bridge`):

**Old config:**
```json
{
  "channels": {
    "reachyBridge": {
      "enabled": true,
      "url": "http://nanobot-whatsapp-bridge:18790",
      "secret": "my-old-secret"
    }
  }
}
```

**New config:**
```json
{
  "channels": {
    "edgeDevices": {
      "enabled": true,
      "url": "http://nanobot-whatsapp-bridge:18790",
      "devices": {
        "reachy": {
          "enabled": true,
          "secret": "my-old-secret",
          "pollIntervalSeconds": 30
        }
      }
    }
  }
}
```

**The legacy `POST /api/sync` endpoint still works** — it routes to device_id `"reachy"`. If you have no `edgeDevices` config but do have `reachyBridge`, the bridge auto-registers a device called `"reachy"` using the legacy secret. You can migrate gradually.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `401 Unauthorized` on sync | HMAC signature wrong | Verify `DEVICE_SECRET` matches `config.json`; check you're signing the exact body bytes you POST |
| `401 Unauthorized` on first-ever request | nginx basic-auth blocking it | Ensure nginx has `auth_basic off` in the `/api/devices/` block — deploy from latest `main` |
| `401 Unauthorized` on WS connect | Wrong Bearer token | Ensure header is exactly `Authorization: Bearer <DEVICE_SECRET>` |
| Connection refused | Wrong `BRIDGE_URL` | Use the public HTTPS hostname — no port suffix, no `/bridge` path |
| `devices` list empty in `/api/devices` | Config not read | Check `edgeDevices.enabled: true` in config.json; validate JSON; restart bridge |
| `directives` always empty | Agent not replying | Check `telemetry` contains items with `"kind": "message"` — other kinds are not forwarded |
| `reply:` directive arrives but device ignores it | Missing handler | Add `if cmd.startswith("reply:"): speak(cmd[len("reply:"):])` |
| `context` always empty | First sync only | Context populates from second sync onward (built from activity since `last_seen`) |
| WS closes immediately after connect | Bad auth header | `Authorization: Bearer <secret>` — note the capital B, space after Bearer |
| Device shows `online: false` despite syncing | Poll interval too long | Bridge marks offline after `poll_interval_seconds × 3` — shorten interval or check it's syncing |
| HMAC mismatch despite correct secret | Body encoding mismatch | Use `json.dumps(payload, separators=(",",":")).encode()` — no extra whitespace |

---

## Security notes

- Each device gets its own `secret` — compromising one doesn't affect others
- HMAC uses constant-time comparison to prevent timing attacks
- nginx strips basic-auth before `/api/devices/*` reaches the bridge — device firmware doesn't need dashboard credentials
- The command-queueing endpoint (`POST /api/devices/{id}/command`) is **not HMAC-protected** — it is only accessible from inside the Docker network (dashboard → bridge), never from the public internet
- Use a minimum 32-character random secret: `python3 -c "import secrets; print(secrets.token_hex(24))"`
