import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './EdgeDevicesView.css';

const API = process.env.REACT_APP_API_URL || '';

const DIRECTIVES = ['wake', 'sleep', 'restart_app', 'restart_picoclaw', 'set_volume', 'capture_frame'];

const GUIDE = `## Setup

Save this as \`~/.nanobot/workspace/skills-auto/edge-sync/sync.py\` and fill in the 3 variables.

\`\`\`python
#!/usr/bin/env python3
# Run once: sync, wait 30s, sync again, exit. Schedule with cron every minute.
import hashlib, hmac, json, ssl, sys, time, urllib.request

BRIDGE_URL    = "https://ec2-3-106-107-16.ap-southeast-2.compute.amazonaws.com"  # no /bridge suffix
DEVICE_ID     = "my-device"   # unique name for this instance
DEVICE_SECRET = "Nb9kQmX3pL7!"

def sync(message=None):
    telemetry = [{"kind": "message", "content": message}] if message else []
    payload = {"status": {"daemon": "running"}, "telemetry": telemetry}
    body = json.dumps(payload).encode()
    sig = hmac.new(DEVICE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        f"{BRIDGE_URL}/api/devices/{DEVICE_ID}/sync",
        data=body,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
        method="POST"
    )
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def handle(result):
    for d in result.get("directives", []):
        if d["command"].startswith("reply:"):
            print("Agent:", d["command"][len("reply:"):])
        else:
            print("Directive:", d["command"])

message = " ".join(sys.argv[1:]) or None
handle(sync(message))  # first sync — sends message if provided
time.sleep(30)
handle(sync())         # second sync — picks up agent reply
# script exits — cron runs it again next minute
\`\`\`

**Schedule it (one cron job, covers both syncs per minute):**
\`\`\`
cron("*/1 * * * * python3 /root/.nanobot/workspace/skills-auto/edge-sync/sync.py >> /tmp/edge-sync.log 2>&1")
\`\`\`

**To send a message manually:**
\`\`\`
python3 /root/.nanobot/workspace/skills-auto/edge-sync/sync.py "your message here"
\`\`\`

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| \`401 Unauthorized\` | \`BRIDGE_URL\` has \`/bridge\` suffix — remove it. Or wrong \`DEVICE_SECRET\`. |
| directives always empty | Pass a message as argument — empty polls don't trigger agent replies |
| device shows stale | Cron not running — check with \`crontab -l\` |
| script hangs | You used \`while True\` or \`nohup\` — the script must exit on its own |
`;

function StatusDot({ online }) {
  return <span className={`ed-dot ${online ? 'online' : 'offline'}`} title={online ? 'Online' : 'Offline'} />;
}

function timeAgo(ts) {
  if (!ts) return 'never';
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 5) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function DeviceCard({ device, onSendDirective, onDeleteDirective, onClearDirectives }) {
  const [selected, setSelected] = useState(DIRECTIVES[0]);
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState([]);
  const [tick, setTick] = useState(0);
  const bottomRef = useRef(null);
  const lastIdRef = useRef(0);

  // Re-render every 5s to keep "X ago" fresh
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 5000);
    return () => clearInterval(t);
  }, []);

  // Load message history
  useEffect(() => {
    fetch(`${API}/api/devices/${device.device_id}/messages`)
      .then(r => r.json())
      .then(data => {
        setMessages(data);
        if (data.length) lastIdRef.current = data[data.length - 1].id;
      })
      .catch(() => {});
  }, [device.device_id]);

  // SSE stream for new messages
  useEffect(() => {
    const es = new EventSource(`${API}/api/devices/${device.device_id}/messages/stream?lastId=${lastIdRef.current}`);
    es.onmessage = (e) => {
      try {
        const row = JSON.parse(e.data);
        lastIdRef.current = row.id;
        setMessages(prev => prev.some(m => m.id === row.id) ? prev : [...prev, row]);
      } catch {}
    };
    return () => es.close();
  }, [device.device_id]);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const statusFields = Object.entries(device.status || {})
    .filter(([k]) => k !== 'last_seen')
    .slice(0, 4);

  async function handleSend() {
    setSending(true);
    await onSendDirective(device.device_id, selected);
    setSending(false);
  }

  return (
    <div className={`ed-card ${device.online ? 'online' : 'offline'}`}>
      <div className="ed-card-header">
        <StatusDot online={device.online} />
        <span className="ed-device-id">{device.device_id}</span>
        <span className="ed-last-seen">{timeAgo(device.last_seen)}</span>
      </div>

      <div className="ed-card-meta">
        <span className="ed-meta-item">poll {device.poll_interval_seconds}s</span>
        {device.stream_mode && <span className="ed-meta-item">stream:{device.stream_mode}</span>}
        {statusFields.map(([k, v]) => (
          <span key={k} className="ed-meta-item">{k}:{String(v)}</span>
        ))}
      </div>

      <div className="ed-messages">
        {messages.length === 0 ? (
          <div className="ed-messages-empty">No messages yet</div>
        ) : (
          messages.map((m, i) => {
            const isDevice = m.source !== 'assistant';
            const time = (() => {
              try { return new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
              catch { return ''; }
            })();
            return (
              <div key={m.id ?? i} className={`ed-msg ${isDevice ? 'inbound' : 'outbound'}`}>
                <div className="ed-msg-bubble">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
                <div className="ed-msg-time">{time}</div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      <div className="ed-directives-section">
        <div className="ed-directives-header">
          <span className="ed-directives-label">
            📬 Queue ({device.pending_directives})
          </span>
          {device.pending_directives > 0 && (
            <button
              className="ed-btn-clear"
              onClick={() => onClearDirectives(device.device_id)}
              title="Clear all"
            >Clear</button>
          )}
        </div>
        {(device.directives || []).map((d, i) => (
          <div key={i} className="ed-directive-row">
            <code className="ed-directive-cmd">{d.command}</code>
            <button
              className="ed-btn-remove"
              onClick={() => onDeleteDirective(device.device_id, i)}
              title="Remove"
            >✕</button>
          </div>
        ))}
      </div>

      <div className="ed-send-row">
        <select
          className="ed-select"
          value={selected}
          onChange={e => setSelected(e.target.value)}
        >
          {DIRECTIVES.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <button
          className="ed-btn-send"
          onClick={handleSend}
          disabled={sending}
        >{sending ? '…' : 'Send'}</button>
      </div>
    </div>
  );
}

export default function EdgeDevicesView({ onToggleSidebar, sidebarOpen }) {
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/devices`);
      if (!r.ok) throw new Error(`${r.status}`);
      const data = await r.json();
      // Fetch per-device status to get directives list
      const detailed = await Promise.all(
        (data.devices || []).map(async d => {
          try {
            const sr = await fetch(`${API}/api/devices/${d.device_id}/status`);
            if (sr.ok) {
              const s = await sr.json();
              return { ...d, directives: s.directives || [] };
            }
          } catch {}
          return { ...d, directives: [] };
        })
      );
      setDevices(detailed);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const sendDirective = useCallback(async (deviceId, command) => {
    await fetch(`${API}/api/devices/${deviceId}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    });
    await refresh();
  }, [refresh]);

  const deleteDirective = useCallback(async (deviceId, idx) => {
    await fetch(`${API}/api/devices/${deviceId}/command/${idx}`, { method: 'DELETE' });
    await refresh();
  }, [refresh]);

  const clearDirectives = useCallback(async (deviceId) => {
    await fetch(`${API}/api/devices/${deviceId}/command`, { method: 'DELETE' });
    await refresh();
  }, [refresh]);

  return (
    <div className="ed-view">
      <div className="ed-header">
        {!sidebarOpen && (
          <button className="icon-btn" onClick={onToggleSidebar} title="Open sidebar">▶</button>
        )}
        <div className="ed-header-icon">🔌</div>
        <div className="ed-header-info">
          <div className="ed-header-title">Edge Devices</div>
          <div className="ed-header-sub">
            {loading ? 'Loading…' : error ? `Bridge unreachable` : `${devices.length} device${devices.length !== 1 ? 's' : ''}`}
          </div>
        </div>
        <button
          className="ed-btn-refresh"
          onClick={refresh}
          title="Refresh"
        >↻</button>
      </div>

      <div className="ed-body">
        {loading ? (
          <div className="ed-empty">Loading…</div>
        ) : error ? (
          <div className="ed-empty ed-error">
            ⚠ Bridge unreachable — {error}<br />
            <small>Is the bridge container running?</small>
          </div>
        ) : devices.length === 0 ? (
          <div className="ed-empty">
            No devices registered.<br />
            <small>Add <code>channels.edgeDevices.devices</code> to config.json and restart.</small>
          </div>
        ) : (
          <div className="ed-grid">
            {devices.map(d => (
              <DeviceCard
                key={d.device_id}
                device={d}
                onSendDirective={sendDirective}
                onDeleteDirective={deleteDirective}
                onClearDirectives={clearDirectives}
              />
            ))}
          </div>
        )}
        <div className="ed-guide">
            <div className="ed-guide-label">📋 INTEGRATION GUIDE</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{GUIDE}</ReactMarkdown>
          </div>
      </div>
    </div>
  );
}
