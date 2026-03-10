import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './WhatsAppView.css';

const API = process.env.REACT_APP_API_URL || '';

const GUIDE_MD = `# Edge Device Integration Guide

How to connect a picoclaw-powered edge device (e.g. Reachy Mini) to nanobot via the Reachy bridge.

## Architecture

\`\`\`
Boss (WhatsApp)
    │ "wake up reachy"
    ▼
Shantelle (nanobot on EC2)
    │ POST localhost:18790/api/dashboard/command
    ▼
nanobot-bridge (HTTP :18790 on EC2)
    │ queues {command: "wake"} in memory
    ▼
PicoClaw on Reachy (polls every ~30s)
    │ POST https://<ec2-host>:18790/api/sync  ← HMAC-signed
    ▼
Reachy hardware
\`\`\`

Communication is **polling, not push**. Shantelle never talks directly to Reachy. She queues commands into the bridge's in-memory list. PicoClaw polls \`/api/sync\` to pick them up.

---

## Server-side Setup (EC2 / nanobot host)

### 1. Enable the Reachy bridge in nanobot config

\`\`\`json
{
  "channels": {
    "reachyBridge": {
      "enabled": true,
      "url": "http://localhost:18790",
      "secret": "<BRIDGE_SECRET>"
    }
  }
}
\`\`\`

### 2. Start the bridge with Reachy enabled

\`\`\`bash
REACHY_BRIDGE_ENABLED=true \\
BRIDGE_SECRET=<BRIDGE_SECRET> \\
REACHY_BRIDGE_PORT=18790 \\
npm start
\`\`\`

Port 18790 must be externally accessible (open in EC2 security group) for PicoClaw to reach it. The WhatsApp WS bridge runs on a separate port (default 3001) and is unaffected.

### 3. Restart nanobot

\`\`\`bash
sudo systemctl restart nanobot
\`\`\`

Shantelle will now intercept WhatsApp messages matching Reachy commands (\`wake up reachy\`, \`sleep reachy\`, \`restart reachy\`, \`reachy status\`) and route them to the bridge instead of the LLM.

---

## PicoClaw Integration (edge device)

### Sync cycle

Every ~30 seconds, POST to the bridge:

\`\`\`
POST https://<ec2-host>:18790/api/sync
Content-Type: application/json
X-Bridge-Signature: <hmac-sha256-hex>
\`\`\`

**Request body:**
\`\`\`json
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
\`\`\`

All fields are optional. Only \`reachy_status\` is used by the bridge currently — the rest are reserved for future KG/memory sync.

**Response:**
\`\`\`json
{
  "pending_commands": [
    {"command": "wake", "queued_at": 1718000000.0}
  ],
  "knowledge_update": [],
  "trust_config": {}
}
\`\`\`

\`pending_commands\` is drained on each sync — commands are delivered exactly once. Execute each command in order, then wait for the next sync cycle.

### HMAC signing

Every request to \`/api/sync\` and \`/api/enrich\` must include \`X-Bridge-Signature\`:

\`\`\`python
import hashlib, hmac, json

body = json.dumps(payload).encode()
sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
headers = {
    "Content-Type": "application/json",
    "X-Bridge-Signature": sig,
}
\`\`\`

Requests with a missing or invalid signature receive \`401 Unauthorized\`.

### Commands

| \`command\` | Meaning |
|-----------|---------|
| \`wake\` | Power on / wake from sleep |
| \`sleep\` | Power off / enter sleep mode |
| \`restart_app\` | Restart the conversation app only |

Unknown commands should be logged and ignored — new commands may be added without a version bump.

### Minimal PicoClaw sync loop (Python)

\`\`\`python
import hashlib, hmac, json, time
import requests

BRIDGE_URL = "https://<ec2-host>:18790"
BRIDGE_SECRET = "<BRIDGE_SECRET>"
SYNC_INTERVAL = 30  # seconds


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
    # Replace with real hardware queries
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
        result = signed_post("/api/sync", {
            "reachy_status": get_reachy_status(),
        })
        for cmd in result.get("pending_commands", []):
            execute_command(cmd["command"])
    except Exception as e:
        print(f"Sync failed: {e}")
    time.sleep(SYNC_INTERVAL)
\`\`\`

---

## Checking Reachy status from WhatsApp

Send any of these to Shantelle:

- \`reachy status\`
- \`check reachy\`
- \`is reachy running\`

She queries \`GET localhost:18790/api/dashboard/status\` and returns the cached state from the last sync. If the last sync was more than 10 minutes ago, she reports Reachy as likely offline.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| \`401 Unauthorized\` on \`/api/sync\` | \`BRIDGE_SECRET\` mismatch between bridge and PicoClaw |
| Commands never arrive | Bridge not started with \`REACHY_BRIDGE_ENABLED=true\` |
| Shantelle doesn't intercept "wake up reachy" | \`channels.reachyBridge.enabled\` not set in nanobot config, or nanobot not restarted |
| Status shows "unknown" | PicoClaw hasn't completed a sync yet, or \`reachy_status\` not included in sync payload |
| Port 18790 unreachable | EC2 security group missing inbound rule for TCP 18790 |
`;

function SyncRow({ row }) {
  const isInbound = row.direction === 'inbound';
  let payload;
  try { payload = JSON.parse(row.payload); } catch { payload = {}; }

  const time = (() => {
    try { return new Date(row.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
    catch { return ''; }
  })();

  let summary;
  if (row.event_type === 'sync') {
    const s = payload.reachy_status || {};
    const facts = payload.pending_facts?.length || 0;
    summary = `daemon:${s.daemon || '?'} app:${s.conversation_app || '?'} picoclaw:${s.picoclaw || '?'}${facts ? ` · ${facts} fact(s)` : ''}`;
  } else if (row.event_type === 'commands') {
    summary = (payload.commands || []).map(c => c.command).join(', ');
  } else {
    summary = JSON.stringify(payload);
  }

  return (
    <div className={`wa-message-row ${isInbound ? 'inbound' : 'outbound'}`}>
      <div className="wa-avatar">{isInbound ? '🦐' : '🤖'}</div>
      <div className="wa-message-body">
        <div className="wa-sender-name">{isInbound ? 'Reachy → Bridge' : 'Bridge → Reachy'}</div>
        <div className="wa-bubble">
          <code style={{ fontSize: '0.8rem' }}>[{row.event_type}] {summary}</code>
        </div>
        <div className="wa-time">{time}</div>
      </div>
    </div>
  );
}

export default function PicoClawView({ onToggleSidebar, sidebarOpen }) {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [live, setLive] = useState(false);
  const [guide, setGuide] = useState('');
  const bottomRef = useRef(null);
  const lastIdRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    fetch(`${API}/api/picoclaw/integration-guide`)
      .then(r => r.ok ? r.text() : Promise.reject())
      .then(setGuide).catch(() => setGuide(GUIDE_MD));

    fetch(`${API}/api/picoclaw/status`)
      .then(r => r.json())
      .then(s => { setStatus(s); setStatusLoaded(true); })
      .catch(() => { setStatus({ enabled: false }); setStatusLoaded(true); });

    fetch(`${API}/api/picoclaw/messages`)
      .then(r => r.json())
      .then(data => {
        setRows(data);
        if (data.length > 0) lastIdRef.current = data[data.length - 1].id;
      })
      .catch(() => {});
  }, []);

  useEffect(() => { scrollToBottom(); }, [rows, scrollToBottom]);

  useEffect(() => {
    const es = new EventSource(`${API}/api/picoclaw/stream?lastId=${lastIdRef.current}`);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.onmessage = (e) => {
      try {
        const row = JSON.parse(e.data);
        lastIdRef.current = row.id;
        setRows(prev => prev.some(r => r.id === row.id) ? prev : [...prev, row]);
      } catch {}
    };
    return () => { es.close(); setLive(false); };
  }, []);

  return (
    <div className="whatsapp-view">
      <div className="whatsapp-header">
        {!sidebarOpen && (
          <button className="icon-btn" onClick={onToggleSidebar} title="Open sidebar">▶</button>
        )}
        <div className="whatsapp-header-icon">🦐</div>
        <div className="whatsapp-header-info">
          <div className="whatsapp-header-title">Picoclaw</div>
          <div className={`whatsapp-header-status ${live ? 'live' : 'offline'}`}>
            {live ? 'live' : 'connecting…'}
          </div>
        </div>
        {statusLoaded && status && !status.enabled && (
          <div className="whatsapp-warning">⚠ Reachy bridge not enabled in config</div>
        )}
      </div>

      <div className="whatsapp-messages">
        {rows.length === 0 ? (
          <div className="whatsapp-empty">
            {!statusLoaded
              ? 'Loading…'
              : status?.enabled
                ? 'No syncs yet — waiting for Reachy to check in.'
                : 'Reachy bridge not enabled. Set channels.reachyBridge.enabled and restart.'}
          </div>
        ) : (
          rows.map(row => <SyncRow key={row.id} row={row} />)
        )}
        {guide && (
          <details style={{ margin: '1rem', textAlign: 'left' }}>
            <summary style={{ cursor: 'pointer', opacity: 0.7 }}>📋 Integration guide</summary>
            <div style={{ padding: '1rem 0' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{guide}</ReactMarkdown>
            </div>
          </details>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="whatsapp-footer">
        <span>🦐 Bidirectional sync log — Reachy polls every ~30s.</span>
      </div>
    </div>
  );
}
