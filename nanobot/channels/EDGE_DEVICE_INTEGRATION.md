# PicoClaw → Bridge Integration Guide

Connect your PicoClaw-powered edge device (e.g. Reachy Mini) to the nanobot AI agent via the Reachy bridge.

---

## How it works

```
Your device  ──POST /api/sync──►  Bridge (EC2)  ──WebSocket──►  Agent (Shantelle)
             ◄──pending_commands──               ◄──reply──
```

1. Your device POSTs to `/api/sync` every ~30 seconds
2. If you include messages in `pending_feedback`, the bridge forwards them to the AI agent
3. The agent's reply is queued and returned to your device as a `reply:` command on the **next** sync
4. Your device reads the reply from `pending_commands` and acts on it (speak it, display it, etc.)

**This is the primary way your device talks to the agent.** Status fields are secondary.

---

## Prerequisites

Get these from your deploy operator:

| Variable | Example |
|----------|---------|
| `BRIDGE_URL` | `https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com/picoclaw` |
| `BRIDGE_SECRET` | shared HMAC secret |

---

## Sync request

```
POST <BRIDGE_URL>/api/sync
Content-Type: application/json
X-Bridge-Signature: <hmac-sha256-hex>
```

```json
{
  "reachy_status": {
    "daemon": "running",
    "conversation_app": "running",
    "picoclaw": "1.2.3"
  },
  "pending_feedback": [
    "Good morning! What's on the agenda today?"
  ]
}
```

### Fields

| Field | Type | Purpose |
|-------|------|---------|
| `reachy_status` | object | Device health — shown in the dashboard |
| `pending_feedback` | array of strings | **Messages to send to the agent.** Each string is delivered as a separate message. |

`pending_feedback` is the key field. Leave it as `[]` if you have nothing to say this cycle.

---

## Sync response

```json
{
  "status": "synced",
  "pending_commands": [
    {"command": "reply:Good morning! You have a physio appointment at 10am.", "queued_at": 1718000000.0},
    {"command": "wake", "queued_at": 1718000001.0}
  ]
}
```

`pending_commands` is **drained on every sync** — each command is delivered exactly once.

### Command types

| Prefix / value | Meaning | What to do |
|----------------|---------|------------|
| `reply:<text>` | Agent's response to your `pending_feedback` | Speak it, display it, or pass it to the conversation app |
| `wake` | Power on / wake from sleep | Wake hardware |
| `sleep` | Power off / enter sleep mode | Sleep hardware |
| `restart_app` | Restart the conversation app | Restart process |

**Always handle `reply:` commands.** Strip the `reply:` prefix to get the text:
```python
if command.startswith("reply:"):
    text = command[len("reply:"):]
    speak(text)  # or display, or pass to conversation app
```

Log and ignore any command you don't recognise.

---

## HMAC signing

Every request must include `X-Bridge-Signature` — HMAC-SHA256 of the raw request body:

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

## Full working example (Python)

```python
import hashlib, hmac, json, time, os
import requests

BRIDGE_URL = os.environ["BRIDGE_URL"]      # e.g. https://ec2-xxx.compute.amazonaws.com/picoclaw
BRIDGE_SECRET = os.environ["BRIDGE_SECRET"]
SYNC_INTERVAL = 30

_pending_feedback = []  # populated by your conversation app


def signed_post(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = requests.post(
        f"{BRIDGE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_status() -> dict:
    return {"daemon": "running", "conversation_app": "running", "picoclaw": "1.0.0"}


def handle_command(command: str) -> None:
    if command.startswith("reply:"):
        text = command[len("reply:"):]
        print(f"Agent says: {text}")
        speak(text)  # implement this — TTS, display, etc.
    elif command == "wake":
        wake_hardware()
    elif command == "sleep":
        sleep_hardware()
    elif command == "restart_app":
        restart_conversation_app()
    else:
        print(f"Unknown command (ignored): {command}")


while True:
    try:
        # Drain the local feedback queue each cycle
        feedback = _pending_feedback[:]
        _pending_feedback.clear()

        result = signed_post("/api/sync", {
            "reachy_status": get_status(),
            "pending_feedback": feedback,
        })

        for cmd in result.get("pending_commands", []):
            handle_command(cmd["command"])

    except Exception as e:
        print(f"Sync error: {e}")

    time.sleep(SYNC_INTERVAL)
```

To send a message to the agent from anywhere in your app:
```python
_pending_feedback.append("The user just said: hello!")
# It will be delivered on the next sync cycle (within 30s)
```

---

## Timing

- Your device syncs every ~30s
- The agent typically responds within 5–30 seconds depending on complexity
- So end-to-end latency is **30–60 seconds** (one sync to send, next sync to receive reply)
- If you need faster responses, reduce `SYNC_INTERVAL` (minimum ~10s recommended)

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | `BRIDGE_SECRET` mismatch | Confirm secret with operator |
| Connection refused / timeout | Wrong `BRIDGE_URL` | Confirm URL with operator |
| Status shows "unknown" in dashboard | Missing `reachy_status` in payload | Always include it |
| Agent never replies | `pending_feedback` always empty | Make sure your app populates it |
| Reply never arrives | Device not handling `reply:` commands | Add `reply:` handler — see above |
| Duplicate syncs in dashboard | Two sync processes running on device | Kill duplicate process |
