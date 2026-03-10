import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './WhatsAppView.css';

const API = process.env.REACT_APP_API_URL || '';

const GUIDE_MD = `# PicoClaw → Bridge Integration

Connect your PicoClaw-powered edge device (e.g. Reachy Mini) to the nanobot Reachy bridge. The bridge queues commands from Nanobot; your device polls to pick them up.

---

## Prerequisites

Get these from whoever runs the bridge (your deploy operator):

| Variable | Description |
|----------|-------------|
| \`BRIDGE_URL\` | Full base URL including scheme and path (e.g. \`https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com/picoclaw\`) |
| \`BRIDGE_SECRET\` | Shared secret for HMAC signing. Must match the bridge's \`BRIDGE_SECRET\`. |

---

## Architecture

\`\`\`
Boss (WhatsApp) → Nanobot → Bridge (queues commands)
                                    ▲
PicoClaw (polls every ~30s) ────────┘  POST <BRIDGE_URL>/api/sync
\`\`\`

Communication is **polling, not push**. Your device POSTs to \`/api/sync\` every ~30 seconds to report status and receive pending commands.

---

## Sync cycle

Every ~30 seconds, POST to the bridge:

\`\`\`
POST <BRIDGE_URL>/api/sync
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

All fields are optional. Only \`reachy_status\` is used by the bridge currently.

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

\`pending_commands\` is drained on each sync — commands are delivered exactly once. Execute each in order, then wait for the next cycle.

---

## HMAC signing

Every request must include \`X-Bridge-Signature\`:

\`\`\`python
import hashlib, hmac, json

body = json.dumps(payload).encode()
sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
headers = {
    "Content-Type": "application/json",
    "X-Bridge-Signature": sig,
}
\`\`\`

Missing or invalid signature → \`401 Unauthorized\`.

---

## Commands

| \`command\` | Meaning |
|-----------|---------|
| \`wake\` | Power on / wake from sleep |
| \`sleep\` | Power off / enter sleep mode |
| \`restart_app\` | Restart the conversation app only |

Log and ignore unknown commands.

---

## Minimal sync loop (Python)

\`\`\`python
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
\`\`\`

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| \`401 Unauthorized\` | \`BRIDGE_SECRET\` mismatch — confirm with operator |
| Connection refused / timeout | \`BRIDGE_URL\` wrong or unreachable — ask operator |
| Status shows "unknown" | Include \`reachy_status\` in your sync payload |
| Commands never arrive | Bridge may not be enabled — ask operator to verify |
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
          <pre style={{
            margin: '1rem',
            padding: '1rem 1.25rem',
            background: '#1e1e2e',
            border: '1px solid #313244',
            borderRadius: '8px',
            textAlign: 'left',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: 'inherit',
            fontSize: '0.85rem',
            lineHeight: 1.6,
            color: '#cdd6f4',
          }}>
            <div style={{ marginBottom: '0.5rem', opacity: 0.5, fontSize: '0.75rem', letterSpacing: '0.05em' }}>📋 INTEGRATION GUIDE</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{guide}</ReactMarkdown>
          </pre>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="whatsapp-footer">
        <span>🦐 Bidirectional sync log — Reachy polls every ~30s.</span>
      </div>
    </div>
  );
}
