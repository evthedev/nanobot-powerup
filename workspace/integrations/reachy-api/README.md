---
name: reachy-api
description: Connects Reachy Mini's conversation app to NanoBot's cloud agent. Gives Reachy access to calendar, email, memory, web search, and all NanoBot capabilities via a call_nanobot tool registered in a custom profile.
---

# Architecture

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  Clients                                                                 │
 │                                                                          │
 │   📱 Telegram user          Telegram Bot API (polling)                  │
 │   📱 WhatsApp user          wa-bridge  ──── WebSocket                   │
 │   🌐 Browser                HTTPS → nginx                               │
 │   🤖 Reachy Mini RPi        HTTPS POST → nginx (SSE response)           │
 └──────────────────────┬───────────────────────┬──────────────────────────┘
                        │                       │
                        ▼                       ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  AWS EC2                                                                 │
 │                                                                          │
 │  ┌─────────────────────────────────────────────────────────────────┐    │
 │  │  nginx  (:443)                                                  │    │
 │  │  · TLS termination (self-signed)                                │    │
 │  │  · Basic auth                                                   │    │
 │  │  · Rate limiting                                                │    │
 │  └────────────────────────┬────────────────────────────────────────┘    │
 │                           │ reverse proxy                               │
 │                           ▼                                             │
 │  ┌─────────────────────────────────────────────────────────────────┐    │
 │  │  dashboard  (:3001)                                             │    │
 │  │  Express API + React UI                                         │    │
 │  │  · serves web chat                                              │    │
 │  │  · POST /api/conversations/:id/messages  (SSE stream)           │    │
 │  └────────────────────────┬────────────────────────────────────────┘    │
 │                           │ WebSocket (:18791)                          │
 │                           ▼                                             │
 │  ┌─────────────────────────────────────────────────────────────────┐    │
 │  │  nanobot agent                                                  │    │
 │  │  · Telegram channel   (Bot API polling)                         │    │
 │  │  · WhatsApp channel   (wa-bridge WebSocket)                     │    │
 │  │  · Web channel        (dashboard WebSocket)                     │    │
 │  │                                                                 │    │
 │  │  Tools:  Google Calendar · Gmail · Google Drive                 │    │
 │  │          Memory · Web search · WhatsApp send                    │    │
 │  │          Browser automation · MCP servers                       │    │
 │  └─────────────────────────────────────────────────────────────────┘    │
 └──────────────────────────────────────────────────────────────────────────┘
```

---

# Reachy Mini ↔ NanoBot Integration

---

## Reference examples from pollen-robotics

This implementation follows the official external content pattern from the repo:

| Our file | Official equivalent |
|---|---|
| `external_tools/call_nanobot.py` | [`external_content/external_tools/starter_custom_tool.py`](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/develop/external_content/external_tools/starter_custom_tool.py) |
| `profile/instructions.txt` | [`external_content/external_profiles/starter_profile/instructions.txt`](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/develop/external_content/external_profiles/starter_profile/instructions.txt) |
| `profile/tools.txt` | [`external_content/external_profiles/starter_profile/tools.txt`](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/develop/external_content/external_profiles/starter_profile/tools.txt) |

The `starter_custom_tool.py` confirms the correct Tool API:
- attribute: `parameters_schema` (not `parameters`)
- method: `async def __call__(self, deps: ToolDependencies, **kwargs)` (not `execute()`)

---

## How it works

The Reachy conversation app uses OpenAI Realtime and a tool-dispatch system.
When the LLM decides it needs cloud capabilities, it calls `call_nanobot` — which
POSTs to NanoBot's existing web dashboard API and streams back the response.

```
Reachy RPi  ──call_nanobot tool──▶  POST /api/conversations/<id>/messages
                                         (NanoBot EC2 dashboard — already running)
                                               │
                                        WebSocket → AgentLoop
                                               │
                                    memory / calendar / web / ...
                                               │
                                         SSE stream ◀─────────
```

Nothing new on EC2 — the existing NanoBot gateway and dashboard handle everything.

---

## Files in this skill

```
workspace/skills/reachy-api/
├── external_tools/
│   └── call_nanobot.py      ← Tool subclass  → external_content/external_tools/
└── profile/
    ├── instructions.txt     ← system prompt  → external_content/external_profiles/nanobot_profile/
    ├── tools.txt            ← enabled tools  → external_content/external_profiles/nanobot_profile/
    └── .env.template        ← env vars to append to the app's .env
```

The tool lives in `external_tools/` — the same place as the official
`starter_custom_tool.py` example. The profile folder holds only config files.

---

## Setup on the Reachy RPi

SSH into the RPi.

### 1. Create the directories

```bash
cd ~/reachy_mini_conversation_app
mkdir -p external_content/external_profiles/nanobot_profile
mkdir -p external_content/external_tools
```

After this the layout mirrors the official repo's `external_content/` structure:

```
~/reachy_mini_conversation_app/
├── .env                                              ← edit this (step 3)
└── external_content/
    ├── external_profiles/
    │   └── nanobot_profile/
    │       ├── instructions.txt
    │       └── tools.txt
    └── external_tools/
        └── call_nanobot.py
```

### 2. Copy the files

```bash
SKILL=~/.nanobot/workspace/skills/reachy-api
DEST=~/reachy_mini_conversation_app

cp $SKILL/external_tools/call_nanobot.py \
   $DEST/external_content/external_tools/call_nanobot.py

cp $SKILL/profile/instructions.txt \
   $DEST/external_content/external_profiles/nanobot_profile/instructions.txt

cp $SKILL/profile/tools.txt \
   $DEST/external_content/external_profiles/nanobot_profile/tools.txt
```

### 3. Append to .env

```bash
cat >> ~/reachy_mini_conversation_app/.env << 'EOF'

# ── NanoBot profile ────────────────────────────────────────────────────────
REACHY_MINI_CUSTOM_PROFILE=nanobot_profile
REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=./external_content/external_profiles
REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=./external_content/external_tools
NANOBOT_CHAT_URL=https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/chat/e8e2007c-9a8c-47b5-a90e-4cbb83449f7f
NANOBOT_TIMEOUT=30
EOF
```

### 4. Check httpx

```bash
python3 -c "import httpx; print('httpx', httpx.__version__)"
```

If missing: `pip install httpx`

### 5. Launch

```bash
cd ~/reachy_mini_conversation_app
source .venv/bin/activate
reachy-mini-conversation-app
```

Startup logs should contain:

```
Loading tools for profile: nanobot_profile
✓ Loaded external tool: call_nanobot
✓ Loaded core tool: play_emotion
✓ Loaded core tool: head_pose
✓ Loaded core tool: dance
tool registered: call_nanobot - Send a request to NanoBot ...
```

---

## Smoke test

From any machine that can reach EC2:

```bash
curl -N -s -X POST \
  "https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/api/conversations/e8e2007c-9a8c-47b5-a90e-4cbb83449f7f/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "What is on my calendar today?"}' \
  | grep '"type":"done"'
```
