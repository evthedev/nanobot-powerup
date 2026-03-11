import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './WhatsAppView.css';

const API = process.env.REACT_APP_API_URL || '';

const GUIDE_MD = `# PicoClaw → Bridge Integration Guide

Connect your PicoClaw-powered edge device to the nanobot AI agent via the Reachy bridge.

---

## How it works

\`\`\`
Your device  ──POST /api/sync──►  Bridge  ──WebSocket──►  Agent (Shantelle)
             ◄──pending_commands──          ◄──reply──
\`\`\`

1. Your device POSTs to \`/api/sync\` every ~30 seconds
2. Messages in \`pending_feedback\` are forwarded to the AI agent
3. The agent's reply is returned as a \`reply:\` command on the **next** sync
4. Your device reads the reply from \`pending_commands\` and speaks/displays it

**\`pending_feedback\` is the primary way your device talks to the agent.**

---

## Prerequisites

| Variable | Example |
|----------|---------|
| \`BRIDGE_URL\` | \`https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com/picoclaw\` |
| \`BRIDGE_SECRET\` | shared HMAC secret (get from operator) |

---

## Sync request

\`\`\`
POST <BRIDGE_URL>/api/sync
Content-Type: application/json
X-Bridge-Signature: <hmac-sha256-hex>
\`\`\`

\`\`\`json
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
\`\`\`

| Field | Purpose |
|-------|---------|
| \`reachy_status\` | Device health shown in dashboard |
| \`pending_feedback\` | **Messages to send to the agent.** Each string = one message. Use \`[]\` if nothing to say. |

---

## Sync response

\`\`\`json
{
  "pending_commands": [
    {"command": "reply:Good morning! You have physio at 10am.", "queued_at": 1718000000.0}
  ]
}
\`\`\`

\`pending_commands\` is drained every sync — each command delivered exactly once.

| Command | What to do |
|---------|------------|
| \`reply:<text>\` | **Strip prefix, speak/display the text** |
| \`wake\` | Wake hardware |
| \`sleep\` | Sleep hardware |
| \`restart_app\` | Restart conversation process |

\`\`\`python
if command.startswith("reply:"):
    speak(command[len("reply:"):])
\`\`\`

---

## HMAC signing

\`\`\`python
import hashlib, hmac, json

body = json.dumps(payload).encode()
sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
headers = {"Content-Type": "application/json", "X-Bridge-Signature": sig}
\`\`\`

---

## Full example (Python)

\`\`\`python
import hashlib, hmac, json, time, os
import requests

BRIDGE_URL = os.environ["BRIDGE_URL"]
BRIDGE_SECRET = os.environ["BRIDGE_SECRET"]
_pending_feedback = []

def signed_post(path, payload):
    body = json.dumps(payload).encode()
    sig = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return requests.post(f"{BRIDGE_URL}{path}", data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        timeout=15).json()

while True:
    try:
        feedback, _pending_feedback[:] = _pending_feedback[:], []
        result = signed_post("/api/sync", {
            "reachy_status": {"daemon": "running", "conversation_app": "running", "picoclaw": "1.0.0"},
            "pending_feedback": feedback,
        })
        for cmd in result.get("pending_commands", []):
            if cmd["command"].startswith("reply:"):
                speak(cmd["command"][len("reply:"):])
            elif cmd["command"] == "wake":
                wake_hardware()
    except Exception as e:
        print(f"Sync error: {e}")
    time.sleep(30)
\`\`\`

To send a message to the agent: \`_pending_feedback.append("user said: hello")\`

---

## Timing

- Sync every ~30s → end-to-end latency is **30–60s** (one cycle to send, next to receive)
- Reduce \`SYNC_INTERVAL\` for faster responses (min ~10s)

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| \`401 Unauthorized\` | \`BRIDGE_SECRET\` mismatch |
| Connection refused | Wrong \`BRIDGE_URL\` |
| Agent never replies | \`pending_feedback\` always empty — populate it |
| Reply never arrives | Missing \`reply:\` handler — add it |
| Duplicate syncs in dashboard | Two sync processes running — kill one |
`;

function SyncRow({ row, onDelete }) {
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
    <div className={`wa-message-row ${isInbound ? 'inbound' : 'outbound'}`} style={{ position: 'relative' }}>
      <div className="wa-avatar">{isInbound ? '🦐' : '🤖'}</div>
      <div className="wa-message-body">
        <div className="wa-sender-name">{isInbound ? 'Reachy → Bridge' : 'Bridge → Reachy'}</div>
        <div className="wa-bubble">
          <code style={{ fontSize: '0.8rem' }}>[{row.event_type}] {summary}</code>
        </div>
        <div className="wa-time">{time}</div>
      </div>
      <button
        onClick={() => onDelete(row.id)}
        title="Delete"
        style={{ position: 'absolute', top: 0, right: 0, background: 'none', border: 'none', cursor: 'pointer', opacity: 0.3, fontSize: '0.75rem', padding: '2px 6px', color: 'var(--text-muted)' }}
        onMouseEnter={e => e.currentTarget.style.opacity = 1}
        onMouseLeave={e => e.currentTarget.style.opacity = 0.3}
      >✕</button>
    </div>
  );
}

export default function PicoClawView({ onToggleSidebar, sidebarOpen }) {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [queue, setQueue] = useState([]);
  const [live, setLive] = useState(false);
  const [guide, setGuide] = useState('');
  const bottomRef = useRef(null);
  const lastIdRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const refreshStatus = useCallback(() => {
    fetch(`${API}/api/picoclaw/status`)
      .then(r => r.json())
      .then(s => { setStatus(s); setStatusLoaded(true); setQueue(s.pending_commands || []); })
      .catch(() => { setStatus({ enabled: false }); setStatusLoaded(true); });
  }, []);

  const clearLog = useCallback(async () => {
    await fetch(`${API}/api/picoclaw/messages`, { method: 'DELETE' });
    setRows([]);
  }, []);

  const deleteRow = useCallback(async (id) => {
    await fetch(`${API}/api/picoclaw/messages/${id}`, { method: 'DELETE' });
    setRows(prev => prev.filter(r => r.id !== id));
  }, []);

  const deleteQueueItem = useCallback(async (index) => {
    await fetch(`${API}/api/picoclaw/queue/${index}`, { method: 'DELETE' });
    refreshStatus();
  }, [refreshStatus]);

  const clearQueue = useCallback(async () => {
    await fetch(`${API}/api/picoclaw/queue`, { method: 'DELETE' });
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    fetch(`${API}/api/picoclaw/integration-guide`)
      .then(r => r.ok ? r.text() : Promise.reject())
      .then(setGuide).catch(() => setGuide(GUIDE_MD));

    refreshStatus();
    const statusPoll = setInterval(refreshStatus, 5000);

    fetch(`${API}/api/picoclaw/messages`)
      .then(r => r.json())
      .then(data => {
        setRows(data);
        if (data.length > 0) lastIdRef.current = data[data.length - 1].id;
      })
      .catch(() => {});

    return () => clearInterval(statusPoll);
  }, [refreshStatus]);

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
        {rows.length > 0 && (
          <button
            onClick={clearLog}
            title="Clear sync log"
            style={{ marginLeft: 'auto', fontSize: '0.7rem', padding: '3px 10px', cursor: 'pointer', background: '#45475a', border: 'none', borderRadius: '4px', color: '#cdd6f4' }}
          >Clear log</button>
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
          rows.map(row => <SyncRow key={row.id} row={row} onDelete={deleteRow} />)
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
        {queue.length > 0 ? (
          <div style={{ width: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
              <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>📬 Pending commands ({queue.length})</span>
              <button onClick={clearQueue} style={{ fontSize: '0.7rem', padding: '2px 8px', cursor: 'pointer', background: '#f38ba8', border: 'none', borderRadius: '4px', color: '#1e1e2e' }}>Clear all</button>
            </div>
            {queue.map((cmd, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', marginBottom: '0.3rem', fontSize: '0.75rem' }}>
                <span style={{ flex: 1, wordBreak: 'break-word', opacity: 0.85 }}>{cmd.command}</span>
                <button onClick={() => deleteQueueItem(i)} style={{ flexShrink: 0, padding: '1px 6px', cursor: 'pointer', background: '#45475a', border: 'none', borderRadius: '3px', color: '#cdd6f4' }}>✕</button>
              </div>
            ))}
          </div>
        ) : (
          <span>🦐 Bidirectional sync log — Reachy polls every ~30s.</span>
        )}
      </div>
    </div>
  );
}
