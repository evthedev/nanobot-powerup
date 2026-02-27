# nanobot-powerup

A fully self-hosted, production-deployed personal AI assistant built on top of [nanobot-ai](https://github.com/HKUDS/nanobot). Adds a web dashboard, cloud deployment (AWS EC2), a Planner-Executor-Evaluator research pipeline, screenshot-backed verification, trip mapping, and a suite of custom skills.

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [Architecture](#architecture)
3. [Directory Structure](#directory-structure)
4. [Core Configuration](#core-configuration)
5. [Agent Loop & Tool Orchestration](#agent-loop--tool-orchestration)
6. [Built-in Tools](#built-in-tools)
7. [Custom Tools](#custom-tools)
8. [Skills](#skills)
9. [Planner-Executor-Evaluator Pattern](#planner-executor-evaluator-pattern)
10. [Chat Dashboard](#chat-dashboard)
11. [Local Development](#local-development)
12. [Production Deployment (AWS EC2)](#production-deployment-aws-ec2)
13. [Secrets & Environment Variables](#secrets--environment-variables)
14. [Key Design Decisions & Quirks](#key-design-decisions--quirks)
15. [Known Bugs Fixed](#known-bugs-fixed)

---

## What This Is

`nanobot-powerup` wraps the upstream `nanobot-ai` Python package with:

- **Web chat dashboard** — React + Express, SSE streaming, live log panel, settings UI, Google OAuth flow
- **Production stack** — Docker Compose (gateway + dashboard + nginx), AWS EC2, Terraform, GitHub Actions CI/CD
- **Research pipeline** — `plan_task` tool implements a Planner → Executor → Evaluator loop using `google/gemini-3-flash-preview` on OpenRouter
- **Screenshot verification** — `screenshot_pages` uses headless Playwright to capture real pages as visual proof embedded in responses
- **Trip mapping** — `trip-mapper` skill geocodes stops and generates Google Static Maps images with numbered pins
- **Skills system** — Markdown-defined workflows (`SKILL.md`) the agent reads and executes, stored in `~/.nanobot/workspace/skills/`
- **Long-term memory** — `MEMORY.md` (facts) + `HISTORY.md` (event log), auto-consolidated after 50 messages
- **Heartbeat** — Periodic tasks checked every 30 min (morning brief, calendar, etc.)

The agent model is `google/gemini-3-flash-preview` via OpenRouter.

---

## Architecture

```
 User (browser / Telegram)
        │
        ▼
  ┌─────────────┐   HTTPS/WSS   ┌─────────────────────────────┐
  │    nginx    │◄──────────────│   EC2 t3.small (Ubuntu 24)  │
  │ (port 80/443│               │                             │
  │  basic auth)│               │  ┌────────────────────────┐ │
  └──────┬──────┘               │  │  nanobot-gateway        │ │
         │ proxy_pass           │  │  (Python, port 18791 WS)│ │
         ▼                      │  │  • AgentLoop            │ │
  ┌─────────────┐               │  │  • ToolRegistry         │ │
  │  dashboard  │──WebSocket───►│  │  • MemoryStore          │ │
  │  (Node 20,  │               │  │  • CronScheduler        │ │
  │   port 3001)│               │  │  • HeartbeatService     │ │
  │  Express API│               │  └────────────────────────┘ │
  │  React SPA  │               │                             │
  └─────────────┘               │  /opt/nanobot (EBS volume)  │
                                │  ├── config.json            │
                                │  ├── workspace/             │
                                │  │   ├── AGENTS.md          │
                                │  │   ├── HEARTBEAT.md       │
                                │  │   ├── memory/            │
                                │  │   ├── screenshots/       │
                                │  │   └── skills/            │
                                │  └── chat.db (SQLite)       │
                                └─────────────────────────────┘
```

**Data flow for a chat message:**

1. Browser POSTs to `dashboard /api/conversations/:id/messages`
2. Dashboard forwards via WebSocket to `nanobot-gateway:18791`
3. Agent loop calls LLM → gets tool calls → executes tools (possibly parallel)
4. Tool results feed back into next LLM call
5. Final response streams back via SSE (`delta` events) to browser
6. Dashboard commits message to SQLite; browser renders streaming cursor

---

## Directory Structure

```
nanobot-powerup/
├── nanobot/                    # Upstream nanobot-ai source (pip-installed in dev)
│   └── agent/
│       ├── loop.py             # Core agent loop
│       └── tools/              # All tool implementations
│           ├── plan_task.py    # ★ Custom: Planner + Evaluator
│           ├── screenshot_pages.py  # ★ Custom: Playwright screenshots
│           ├── web.py          # web_search (Tavily/Brave) + web_fetch
│           ├── shell.py        # exec (shell commands)
│           ├── filesystem.py   # read/write/edit/list files
│           ├── message.py      # send messages to users
│           ├── spawn.py        # spawn subagents
│           ├── cron.py         # schedule tasks
│           ├── reddit.py       # reddit_search
│           ├── trustpilot.py   # trustpilot_search
│           ├── yelp.py         # yelp_search
│           └── mcp.py          # MCP client (Playwright, etc.)
│
├── workspace/                  # Synced to /opt/nanobot/workspace/ on EC2
│   ├── AGENTS.md               # Agent personality + tool selection guide
│   ├── HEARTBEAT.md            # Periodic task list (checked every 30 min)
│   ├── memory/                 # MEMORY.md + HISTORY.md
│   └── skills/
│       ├── travel-research/    # ★ Multi-day trip planner
│       ├── trip-mapper/        # ★ Google Static Maps generator
│       ├── review/             # Product/restaurant review skill
│       ├── google-calendar/    # Calendar read/write
│       ├── australian-news/    # News digest
│       ├── recommendation-enhancement/
│       ├── reddit-api-access/
│       ├── memory/
│       └── ping-test/
│
├── dashboard/
│   ├── server/index.js         # Express API + SSE streaming + WebSocket proxy
│   ├── client/src/             # React SPA (ChatWindow, LogsPanel, Settings)
│   └── Dockerfile              # Multi-stage: React build → Express serve
│
├── deploy/
│   ├── nginx/nginx.conf        # Reverse proxy, HTTPS, basic auth, SSE config
│   ├── nginx/.htpasswd         # Hashed credentials (username: nanobot)
│   ├── terraform/              # IaC: EC2 + VPC + EBS + Elastic IP
│   ├── inject_keys.py          # Injects GitHub Secrets → config.json post-deploy
│   ├── migrate_db.py           # One-time: fix hardcoded localhost URLs in chat.db
│   └── bootstrap.sh            # First-time AWS setup (S3, key pair, IAM, secrets)
│
├── .github/workflows/
│   └── deploy.yml              # Terraform + SSH deploy on push to main
│
├── docker-compose.yml          # Local + prod: gateway + dashboard + nginx
├── Dockerfile                  # Gateway: Python 3.12 + Node 20 + Chromium
└── .env                        # Google OAuth creds (not committed to prod)
```

---

## Core Configuration

All runtime config lives at `~/.nanobot/config.json` (EC2: `/opt/nanobot/config.json`).

```json
{
  "agents": {
    "defaults": {
      "model": "google/gemini-3-flash-preview",
      "workspace": "/root/.nanobot/workspace",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20
    }
  },
  "channels": {
    "web": { "enabled": true, "port": 18791 },
    "telegram": { "enabled": false, "token": "", "allowFrom": [] }
  },
  "providers": {
    "openrouter": { "apiKey": "sk-or-..." }
  },
  "gateway": { "host": "0.0.0.0", "port": 18790 },
  "tools": {
    "exec": { "timeout": 600 },
    "restrictToWorkspace": false,
    "web": {
      "search": {
        "provider": "tavily",
        "tavilyApiKey": "tvly-..."
      }
    },
    "google": {
      "mapsApiKey": "AIza...",
      "calendar": {
        "clientId": "...",
        "clientSecret": "...",
        "tokens": { "access_token": "...", "refresh_token": "..." }
      }
    },
    "mcpServers": {
      "playwright": {
        "command": "npx",
        "args": ["@playwright/mcp@latest", "--output-dir", "/root/.nanobot/workspace/screenshots"]
      }
    }
  }
}
```

**Key points:**
- `mapsApiKey` is read by `trip-mapper.py` via `config.json` fallback (not from container env vars)
- `tools.web.search.provider` switches between `"tavily"` (default, paid) and `"brave"` (fallback)
- `restrictToWorkspace: false` — exec is unrestricted; agent can write anywhere under `~`
- MCP Playwright server is wired up; its tools go to **subagents only**, not the main agent

---

## Agent Loop & Tool Orchestration

`nanobot/agent/loop.py` is the core processing engine:

### Sequential vs Parallel execution

| Condition | Behaviour |
|-----------|-----------|
| All requested tools are read-only (`web_search`, `read_file`, `screenshot_pages`, etc.) | Run all **in parallel** (batch mode) |
| Mix of read-only + side-effect (`spawn`, `message`, `write_file`, etc.) | Run first tool only, defer rest |
| `spawn` present | Run `spawn` first, always |

### Evaluation gate

When `plan_task(mode="plan")` is called, the loop **blocks the final response** until `plan_task(mode="evaluate")` is also called (max 2 evaluation attempts). If the limit is hit with unresolved criteria, the agent must explicitly disclose the gaps.

### Memory consolidation

Triggers automatically when session exceeds 50 messages. Compresses old messages into `memory/MEMORY.md` and `memory/HISTORY.md` via an async background task. Doesn't block message processing.

### Special commands

- `/new` — clears session and triggers memory consolidation

---

## Built-in Tools

| Tool | Description |
|------|-------------|
| `web_search` | Tavily (primary) or Brave (fallback). Semaphore limits to 2 concurrent calls. Retries once on 429. |
| `web_fetch` | Fetches URL, extracts readable content via `readability`. Max 50k chars. |
| `exec` | Shell commands. Deny list blocks `rm -rf`, `format`, `dd`, etc. 600s timeout. 10k output limit. |
| `read_file` / `write_file` / `edit_file` / `list_dir` | File operations. `edit_file` uses difflib for fuzzy matching. |
| `message` | Sends messages to the current user channel. Suppresses duplicate main-agent reply. |
| `spawn` | Creates background subagents. Takes priority in scheduling. Results delivered via `message`. |
| `reddit_search` | Reddit JSON API (no key). Subreddit filter, sort, time window. |
| `trustpilot_search` | Extracts `__NEXT_DATA__` from Trustpilot pages. Returns trust scores + reviews. |
| `yelp_search` | Yelp Fusion API. Requires `YELP_API_KEY`. Location, category, price, open_now. |
| `cron` | Add/list/remove scheduled jobs. Supports cron expressions, intervals, one-shot `at` times. |

---

## Custom Tools

### `screenshot_pages`

Takes screenshots of up to **5 URLs per call** using headless Playwright. Saves PNG files to `~/.nanobot/workspace/screenshots/` where they're served at `/api/screenshots/`.

**Hard rules:**
- **Max 5 pages per call** — rejects oversized calls with explicit split instructions:
  ```
  ❌ screenshot_pages REJECTED: 20 pages submitted but max is 5 per call.
  You MUST split this into 4 separate calls: Call 1: pages 1–5 ...
  ```
- **Google URLs blocked** — auto-redirected to DuckDuckGo (Google detects headless browsers)
- **Headless mode** — detects `$DISPLAY` env var; uses `headless=True` on EC2 (no X server), `headless=False` locally
- **Usability markers** — output marks each result as `✅ USABLE` or `❌ FAILED — DO NOT EMBED`
- **Search results warning** — flags DuckDuckGo/Bing URLs used for non-price labels

### `plan_task`

Two-mode orchestration tool using `google/gemini-3-flash-preview`:

- **`mode="plan"`** — generates a structured execution plan with success criteria, batched steps, and quality gate. Called by skills before research begins.
- **`mode="evaluate"`** — checks a draft response against the plan's criteria. Returns `pass` or `retry` with per-criterion feedback and specific retry instructions.

**Travel-specific enforcement:**
- Injects constraint into planner prompt: "MINIMUM 4 screenshot_pages calls for a 12-day trip"
- `_enforce_travel_screenshot_batching()` post-processes plan JSON to split any >5-page call
- Evaluator counts named locations in draft, checks screenshot coverage, fails if M < N

---

## Skills

Skills are Markdown files (`SKILL.md`) in `~/.nanobot/workspace/skills/<name>/`. The agent reads them when a matching intent is detected and follows the instructions.

**Always use `~/.nanobot/workspace/` paths** in skill commands — never hardcode `/Users/ev/` or `/root/`.

### `travel-research`

Full trip-planning workflow. Triggers on travel requests. Calls `plan_task(mode="plan")` with `available_tools="web_search, screenshot_pages, exec, read_file, plan_task"`, then the agent executes the plan.

Expected output per trip: flights (Type A screenshots), hotels (Type A), per-location screenshots (Type B, one per named place), trip map (trip-mapper), Google Maps link, no deferral phrases.

### `trip-mapper`

Geocodes a list of stop names and generates a Google Static Maps image with numbered red pins and a blue route line.

```bash
python3 ~/.nanobot/workspace/skills/trip-mapper/trip-mapper.py \
  "Haeundae Beach, Busan" "Gamcheon Culture Village, Busan" "Gyeongbokgung Palace, Seoul"
```

**Output (ready-to-embed markdown):**
```
✅ Trip map generated. Copy this EXACT markdown into your response:
![Trip Map](/api/screenshots/trip-map.png)
[Open in Google Maps](https://www.google.com/maps/dir/35.1586,129.1605/35.0963,129.0088/...)

IMAGE_PATH:/root/.nanobot/workspace/screenshots/trip-map.png
STOPS:
  1. Haeundae Beach, Busan (35.1586, 129.1605)
  ...
```

API key source: `$GOOGLE_STATIC_MAPS_API_KEY` env var → fallback to `~/.nanobot/config.json tools.google.mapsApiKey` (required on EC2 where container env doesn't have the key).

Geocoding: Nominatim (OpenStreetMap, free) first, then Google Geocoding API if `GOOGLE_GEOCODING_API_KEY` is set. Max 25 stops.

### `review`

Product/restaurant/service review research. Uses `plan_task` for structured evaluation with screenshots.

### `google-calendar`

Read and write Google Calendar events. Requires OAuth tokens stored in `config.json`. Auth flow initiated via dashboard Settings → Google Auth.

### `australian-news`

Fetches and summarises Australian news headlines.

### `recommendation-enhancement`

Enriches a draft recommendation with additional screenshots and source verification.

---

## Planner-Executor-Evaluator Pattern

```
User request
    │
    ▼
plan_task(mode="plan")         ← Gemini plans steps + criteria
    │ Returns: criteria list
    │          numbered steps with batch flags
    │          quality gate
    ▼
Agent executes steps
  Step 1 (batch): web_search × N + screenshot_pages × 1-2
  Step 2 (batch): screenshot_pages × 3-4  (Type B source pages)
  Step 3 (batch): exec trip-mapper  (travel only)
    │
    ▼
plan_task(mode="evaluate")     ← Gemini checks draft vs criteria
    │
    ├── verdict=pass → write_response (final)
    │
    └── verdict=retry → agent takes more screenshots, retries
              (max 2 evaluation attempts)
              If limit hit: agent must disclose gaps explicitly
```

### Screenshot taxonomy

| Type | Purpose | URL pattern | Example |
|------|---------|-------------|---------|
| **Type A** | Price/availability evidence | Search results OK | `flights-syd-sel.png` → DuckDuckGo search |
| **Type B** | Factual claim verification | Source pages required | `hybe-insight.png` → Wikipedia/TripAdvisor |

Google URLs are **always banned** — auto-redirected to DuckDuckGo.

---

## Chat Dashboard

### Backend (`dashboard/server/index.js`)

- **Database**: SQLite3 (`better-sqlite3`, WAL mode) at `DB_PATH` (`/root/.nanobot/chat.db`)
- **Tables**: `conversations`, `messages`, `system_stats`
- **WebSocket proxy**: Connects to `ws://nanobot-gateway:18791`, 10-minute idle timeout
- **SSE streaming**: `/api/conversations/:id/messages` (POST) streams `delta` / `done` / `stream_end` events
- **Log streaming**: `/api/logs/stream` — `tail -F` the gateway log, parses loguru format, tags each line with `level`, `source` (`main`/`sub`/`sys`), model name, token counts
- **Config API**: `/api/config` GET/POST — deep merge into `config.json`
- **Screenshots**: `/api/screenshots/:file` — serves from `~/.nanobot/workspace/screenshots/` (no auth on nginx)
- **Google OAuth**: `/api/google/auth/start` + `/api/google/auth/callback` — PKCE-style state with 10-min TTL

### Frontend (`dashboard/client/src/`)

- React SPA, relative API URLs in prod (`REACT_APP_API_URL=""`)
- `ChatWindow.js` — ReactMarkdown with GFM, streaming cursor, auto-scroll
- `LogsPanel.js` — live log viewer with tab filtering (main / subagent / system)
- `Settings.js` — deep-merge config editor with model/key management
- SSE events: `delta` (streaming chunk), `new_message` (subagent bubble), `done` (message complete), `stream_end` (close SSE)

### nginx config highlights

```nginx
# Screenshots: no basic auth so <img> tags load in any browser
location /api/screenshots/ {
  auth_basic off;
  proxy_pass http://dashboard:3001;
}

# Chat POST: rate-limited (5 req/min, burst 20)
location ~ ^/api/conversations/.*/chat$ {
  limit_req zone=login burst=20 nodelay;
}

# SSE: never buffered
location /api/logs/stream {
  proxy_buffering off;
  proxy_read_timeout 24h;
}

# Chat messages: long timeout for slow research
location /api/conversations/ {
  proxy_read_timeout 10m;
}
```

---

## Local Development

### 1-Command Setup (Recommended)

The easiest way to set up everything locally is to use the interactive setup script. This script **creates a virtual environment (`.venv`)** to isolate the project's Python dependencies.

```bash
# 1. Run the interactive setup (prompts for API keys)
python3 setup-local.py

# 2. Activate the virtual environment (for local CLI use)
source .venv/bin/activate

# 3. Start the services
docker compose up -d
```

Access your dashboard at:
- **Direct (recommended for local):** [http://localhost:3001](http://localhost:3001) (No auth)
- **Proxy (matches prod):** [https://localhost](https://localhost) (Basic auth / self-signed cert)

---

### Manual Setup (Step-by-Step)

If you prefer to run services manually or without Docker, follow these prerequisites:

- Python ≥ 3.11, Node.js ≥ 18, `uv` package manager
- `nanobot-ai` installed: `pip install -e .` (from repo root)
- `~/.nanobot/config.json` with `openrouter.apiKey`, `tavilyApiKey` and `channels.web.enabled: true`

### docker-compose.override.yml (local only)

A `docker-compose.override.yml` is **gitignored** and must never be committed. It can mount local source code into the containers for development. The EC2 deploy explicitly deletes it:

```bash
rm -f docker-compose.override.yml
```

### Syncing skills to local gateway

Skills are version-controlled in `workspace/skills/` (the repo). The running gateway reads from `~/.nanobot/workspace/skills/` (local instance). After editing files in the repo, push them to the running gateway:

```bash
rsync -a workspace/ ~/.nanobot/workspace/
```

You can edit `~/.nanobot/workspace/skills/` directly for quick experiments, but those changes won't persist — the next EC2 deploy overwrites them from the repo. Always commit skill changes back to `workspace/skills/`.

### Gateway log

```bash
tail -f ~/.nanobot/logs/gateway.log
```

---

## Production Deployment (AWS EC2)

### Infrastructure

| Component | Spec |
|-----------|------|
| Instance | `t3.small`, Ubuntu 24.04 LTS |
| Root EBS | 20 GB — OS disk, replaced with the instance |
| Data EBS | 10 GB, mounted at `/opt/nanobot` — separate persistent disk that survives instance replacement. EBS (Elastic Block Store) is AWS's virtual hard drive that can be detached from one EC2 instance and re-attached to another. |
| Elastic IP | `13.54.226.177` → [`ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com`](https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com) |
| Region | ap-southeast-2 (Sydney) |
| Terraform state | S3 bucket |

### First-time setup

Run `deploy/bootstrap.sh` **once** from a local machine with AWS CLI + GitHub CLI configured. It:
1. Creates S3 bucket for Terraform state
2. Generates EC2 key pair, uploads to AWS, saves private key to GitHub secret `EC2_SSH_KEY`
3. Creates IAM user with EC2 + S3 permissions, saves keys to GitHub secrets
4. Sets all required GitHub secrets/variables

### Deployment flow (GitHub Actions → `deploy.yml`)

On every push to `main`:

```
1. Terraform init + apply
   │
   ├── init: GitHub Actions runners are ephemeral (fresh VM per run). init re-downloads
   │         the AWS provider and configures the S3 state backend. Fast (~5s), idempotent.
   │
   └── apply: checks the S3 state file; makes zero changes if infra hasn't drifted.
              Only acts when EC2/VPC/IP config has actually changed.

2. SSH Phase 1 (ubuntu user)
   │  Terraform only provisions infrastructure — it doesn't deploy code.
   │  SSH is needed to run git pull and docker compose inside the instance.
   │
   a. git pull latest main
   b. rsync workspace/*.md + skills/ → /opt/nanobot/workspace/
   c. python3 deploy/inject_keys.py   → injects API keys into config.json
   d. python3 deploy/migrate_db.py    → fixes any old localhost:3001 URLs in chat.db
   e. write /opt/nanobot-app/.env     → GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, MAPS_KEY

3. SSH Phase 2 (docker group — separate session so group membership is active)
   a. docker compose build --pull
   b. docker compose up -d --force-recreate
   c. docker image prune -f
```

### Volume layout on EC2

```
/opt/nanobot/           ← EBS data volume (persistent across deploys)
├── config.json         ← Runtime config + injected API keys
├── chat.db             ← SQLite conversation history
├── logs/gateway.log    ← Agent log (rotated by loguru)
└── workspace/
    ├── AGENTS.md
    ├── HEARTBEAT.md
    ├── memory/
    │   ├── MEMORY.md
    │   └── HISTORY.md
    ├── screenshots/    ← Saved PNG files, served at /api/screenshots/
    └── skills/
        ├── travel-research/
        ├── trip-mapper/
        └── ...

/opt/nanobot-app/       ← Git repo (replaced on each deploy)
├── .env                ← Google OAuth credentials (written by deploy.yml)
├── docker-compose.yml
├── workspace/          ← Synced to /opt/nanobot/workspace/ during deploy
└── ...
```

### Docker containers

| Container | Image | Purpose |
|-----------|-------|---------|
| `nanobot-gateway` | `./Dockerfile` | Python agent, Playwright, WebSocket server (port 18791 internal) |
| `nanobot-dashboard` | `./dashboard/Dockerfile` | Express API + React static (port 3001 internal) |
| `nanobot-nginx` | `nginx:alpine` | HTTPS + basic auth + reverse proxy (ports 80, 443) |

Volume mount: all containers share `/opt/nanobot:/root/.nanobot`

### Dashboard access

```
URL:      https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/
Username: nanobot
Password: (see deploy/nginx/.htpasswd — set during bootstrap)
```

Screenshots are served **without auth** at `https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/api/screenshots/<file>.png`.

---

## Secrets & Environment Variables

### GitHub Secrets (set by bootstrap.sh)

| Secret | Used by |
|--------|---------|
| `AWS_ACCESS_KEY_ID` | Terraform |
| `AWS_SECRET_ACCESS_KEY` | Terraform |
| `EC2_SSH_KEY` | SSH deploy |
| `EC2_KEY_PAIR_NAME` | Terraform |
| `TF_STATE_BUCKET` | Terraform S3 backend |
| `OPENROUTER_API_KEY` | LLM via OpenRouter |
| `TAVILY_API_KEY` | Web search (primary) |
| `BRAVE_API_KEY` | Web search (fallback) |
| `GOOGLE_STATIC_MAPS_API_KEY` | trip-mapper + static map images |
| `GOOGLE_CLIENT_ID` | Google OAuth (Calendar) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth (Calendar) |

### GitHub Variables

| Variable | Value |
|----------|-------|
| `AWS_REGION` | `ap-southeast-2` |

### Container environment variables

The `nanobot-gateway` container only receives:
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`
- `PLAYWRIGHT_BROWSERS_PATH=/usr/bin`

**All other keys** (OpenRouter, Tavily, Maps, etc.) are injected into `config.json` by `inject_keys.py`, not passed as env vars. Tools that need them read from `config.json`.

---

## Key Design Decisions & Quirks

### 1. Playwright runs headless on EC2

`screenshot_pages` detects `$DISPLAY` env var:
```python
_headless = not bool(os.environ.get("DISPLAY"))
browser = await pw.chromium.launch(headless=_headless)
```
EC2 has no X server → headless. Local Mac has `DISPLAY` → headed (needed for some sites that detect headless).

### 2. Google Maps API key in config.json, not env var

`trip-mapper.py` reads the key in this order:
1. `$GOOGLE_STATIC_MAPS_API_KEY` env var (works locally)
2. `~/.nanobot/config.json → tools.google.mapsApiKey` (required on EC2 where container env is minimal)

### 3. `screenshot_pages` hard-limits 5 pages per call

Any call with >5 pages is **immediately rejected** with explicit split instructions. The agent must make multiple calls. This prevents silent truncation where pages 6+ were dropped with no feedback.

### 4. trip-mapper outputs ready-to-embed markdown

Previous format (`IMAGE_URL:/api/screenshots/trip-map.png`) caused the agent to copy the label `IMAGE_URL` literally into responses. Now outputs:
```
✅ Trip map generated. Copy this EXACT markdown into your response:
![Trip Map](/api/screenshots/trip-map.png)
[Open in Google Maps](https://www.google.com/maps/dir/...)
```

### 5. Screenshot URLs use relative paths

All screenshot URLs in chat responses use `/api/screenshots/` (relative), not `http://localhost:3001/api/screenshots/`. `migrate_db.py` patches historical messages on every deploy.

### 6. AGENTS.md uses `~` paths, not hardcoded home directories

`workspace/AGENTS.md` previously said `The workspace is /Users/ev/.nanobot/workspace/`. This caused the EC2 agent to use the wrong path (home is `/root` inside the container). All paths now use `~/.nanobot/workspace/`.

### 7. Planner-Evaluator for travel uses programmatic enforcement

The LLM planner reliably generates only 1 `screenshot_pages` call even when asked for 4. Two safeguards:
- Prompt injection: `"MINIMUM 4 screenshot_pages calls for a 12-day trip"`
- Post-processor: `_enforce_travel_screenshot_batching()` splits >5-page calls in the generated plan JSON

### 8. Nginx rate limiting is endpoint-specific

Server-level rate limiting (`limit_req` on the whole server block) was blocking image asset loads in the browser. Rate limiting is now only on the chat POST endpoint.

### 9. docker-compose.override.yml must never reach EC2

Local development uses a `docker-compose.override.yml` to mount source code. `deploy.yml` explicitly deletes it:
```bash
rm -f docker-compose.override.yml
```

### 10. Workspace sync is additive only

The deploy script syncs skills with `rsync -a` (no `--delete`). This means skills created directly on EC2 are preserved across deploys. Only files that exist in the repo are updated.

---

## Known Bugs Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `screenshot_pages` crashed on EC2 with "Missing X server" | `headless=False` requires display | Auto-detect `$DISPLAY`, use `headless=True` when absent |
| `trip-mapper.py` exited silently with "GOOGLE_STATIC_MAPS_API_KEY not set" | EC2 container has no env var for the key | Read from `config.json` as fallback |
| Agent embedded `![Map](IMAGE_URL)` literally | `trip-mapper` output was `IMAGE_URL:/api/screenshots/...` — agent copied the label | Output changed to ready-to-embed markdown lines |
| Only 5 of 20 named locations had screenshots | `screenshot_pages` silently dropped pages 6+ when >5 submitted | Hard-reject >5 pages with split instructions |
| Map still not generating even with all fixes | Planner LLM generated only 1 screenshot_pages call | Prompt injection + `_enforce_travel_screenshot_batching()` post-processor |
| Old chat images broken in prod after URL format change | Messages stored `http://localhost:3001/api/screenshots/...` | `migrate_db.py` patches on every deploy |
| Images intermittently failing to load in browser | nginx server-level `limit_req` throttled all requests including image assets | Move rate limiting to chat endpoint only |
| Agent used `/Users/ev/.nanobot/` on EC2 | `AGENTS.md` said "This agent runs on macOS. Never use /root/ paths." | All workspace paths now use `~` |
| Sushi request returned no response (silent failure) | `screenshot_pages` X server crash caused unhandled exception that prevented any DB write | Fixed by headless mode detection |
| Agent hallucinated screenshot URLs for missing locations | Agent inferred filenames based on labels without actually capturing them | `✅ USABLE` / `❌ FAILED` markers + hard rejection |
