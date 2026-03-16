import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './EdgeDevicesView.css';

const API = process.env.REACT_APP_API_URL || '';

function StatusDot({ online }) {
  return <span className={`ed-dot ${online ? 'online' : 'offline'}`} title={online ? 'Online' : 'Offline'} />;
}

function InstallGuideModal({ onClose }) {
  const skillMd = `# edge-listener

## Purpose
Connects edge device to the NanoBot bridge via WebSocket. Listens for incoming messages from users, attempts to fulfill them using local skills, and proxies anything it cannot fulfill to NanoBot. Speaks NanoBot's reply verbatim to the user.

## Location
~/.nanobot/workspace/skills/edge-listener/

## Files
- SKILL.md (this file)
- listener.py (main process)

## Behaviour

### Proxy pattern
1. User speaks to edge device
2. edge device STT → text
3. try_local_skills(text)
   - Match found AND executes successfully → speak result locally
   - No match OR execution fails OR returns empty → proxy to NanoBot
4. If proxying: speak "let me check" → send verbatim to bridge → speak reply verbatim

### Knowledge boundary
edge device owns: motors, servos, LEDs, GPIO, local hardware commands
NanoBot owns: everything else (calendar, weather, reminders, general knowledge, etc.)

The boundary is enforced by skill availability — not a hardcoded list.
If a skill exists and succeeds → handle locally.
If no skill matches OR skill throws/returns empty → forward to NanoBot.

### Proxy invariants
- User message is forwarded to bridge VERBATIM — no rephrasing
- Bridge reply is spoken to user VERBATIM — no rephrasing
- edge device does not interpret, summarise or modify NanoBot's response
- NanoBot replies in 2nd person, spoken sentence structure (enforced bridge-side)

## Usage

### Run as daemon
python3 listener.py --device-id my-device --bridge wss://<host>/edge/ws

### One-shot query (testing)
python3 listener.py --send "what events do I have today"

### Environment variables
EDGE_DEVICE_ID   device id registered with bridge
EDGE_TOKEN       bearer token for bridge auth
BRIDGE_URL       wss://host/edge/ws

## Dependencies
- websockets
- local skill router (imported from device agent)
- TTS (native)
- STT (native)

## Reconnect behaviour
Exponential backoff: 5s → 10s → 20s → 40s → 60s (cap)
On reconnect: re-sends hello frame, resumes normal operation

## Integration points
- Bridge endpoint: /edge/ws?device_id=<id>
- Auth: Authorization: Bearer <EDGE_TOKEN>
- Frames used: hello, ping/pong, message.send, message.create
`;

  const listenerPy = `def handle_message(content: str):
    # Attempt local skill dispatch
    result = try_local_skills(content)
    
    if result is not None:
        speak(result)
    else:
        # No skill matched or skill failed — proxy to NanoBot
        speak("let me check")
        reply = send_to_bridge(content)
        if reply:
            speak(reply)

def try_local_skills(content: str) -> str | None:
    """
    Attempt to match and execute a local skill.
    Returns result string if handled, None if not matched or failed.
    """
    try:
        match = skill_router.match(content)
        if not match:
            return None
        result = match.execute(content)
        return result if result else None  # empty result also falls through
    except Exception:
        return None  # skill failure falls through to NanoBot
`;

  return (
    <div className="ed-modal-overlay" onClick={onClose}>
      <div className="ed-modal" onClick={e => e.stopPropagation()}>
        <div className="ed-modal-header">
          <span className="ed-modal-title">Edge Installation Guide</span>
          <button className="ed-modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="ed-modal-body">
          <div className="ed-guide-section">
            <div className="ed-guide-header">
              <div className="ed-guide-name">edge-listener</div>
              <span className="ed-pill md">MD</span>
              <span className="ed-guide-name">SKILL.md</span>
            </div>
            <div className="ed-code-wrap">
              <div className="ed-code">{skillMd}</div>
            </div>
          </div>

          <div className="ed-guide-section">
            <div className="ed-guide-header">
              <div className="ed-guide-name">edge-listener</div>
              <span className="ed-pill py">PY</span>
              <span className="ed-guide-name">listener.py</span>
            </div>
            <div className="ed-code-wrap">
              <div className="ed-code">{listenerPy}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function timeAgo(ts) {
  if (!ts) return 'never';
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 5) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function DeviceCard({ device, onSendDirective, onDisconnect, onRemove }) {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState('');
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState([]);
  const [, setTick] = useState(0);
  const [convId, setConvId] = useState(null);
  const bottomRef = useRef(null);
  const lastIdRef = useRef(0);

  // Re-render every 5s to keep "X ago" fresh
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 5000);
    return () => clearInterval(t);
  }, []);

  // Load message history
  const fetchMessages = useCallback(() => {
    fetch(`${API}/api/devices/${device.device_id}/messages`)
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) {
          setMessages(data);
          if (data.length) lastIdRef.current = data[data.length - 1].id;
        }
      })
      .catch(() => {});
  }, [device.device_id]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  // Poll for new messages every 4s (SSE proxy hangs in Docker — polling is reliable)
  useEffect(() => {
    const interval = setInterval(fetchMessages, 4000);
    return () => clearInterval(interval);
  }, [fetchMessages]);

  // Fetch the device's linked chat conversation ID
  useEffect(() => {
    fetch(`${API}/api/devices/${device.device_id}/conversation`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.id) setConvId(data.id); })
      .catch(() => {});
  }, [device.device_id]);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const statusFields = Object.entries(device.status || {})
    .filter(([k]) => k !== 'last_seen')
    .slice(0, 4);

  async function handleSend() {
    const text = inputValue.trim();
    if (!text) return;
    setSending(true);
    setInputValue('');
    await onSendDirective(device.device_id, text);
    setSending(false);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className={`ed-card ${device.online ? 'online' : 'offline'}`}>
      <div className="ed-card-header">
        <StatusDot online={device.online} />
        <span className="ed-device-id">{device.device_id}</span>
        <span className="ed-last-seen">{timeAgo(device.last_seen)}</span>
        {convId && (
          <button
            className="ed-btn-chat"
            onClick={() => navigate(`/chat/${convId}`)}
            title="Open in chat"
          >💬 Chat</button>
        )}
        {device.ws_connected && (
          <button
            className="ed-btn-disconnect"
            onClick={() => onDisconnect(device.device_id)}
            title="Disconnect WebSocket"
          >⏏</button>
        )}
        <button
          className="ed-btn-remove-device"
          onClick={() => onRemove(device.device_id)}
          title="Remove from registry"
        >✕</button>
      </div>

      <div className="ed-card-meta">
        {device.ws_connected ? (
          <span className="ed-meta-item ws-badge">ws</span>
        ) : (
          <span className="ed-meta-item">poll {device.poll_interval_seconds}s</span>
        )}
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
            const isDevice = m.source !== 'assistant' && m.source !== 'bridge';
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

      <div className="ed-send-row">
        <input
          type="text"
          className="ed-input"
          placeholder="Type a command (e.g. walk forward, wake up)..."
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
          aria-label="Command input"
        />
        <button
          className="ed-btn-send"
          onClick={handleSend}
          disabled={sending || !inputValue.trim()}
        >{sending ? '…' : 'Send'}</button>
      </div>
    </div>
  );
}

export default function EdgeDevicesView({ onToggleSidebar, sidebarOpen }) {
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showInstallGuide, setShowInstallGuide] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/devices`);
      if (!r.ok) throw new Error(`${r.status}`);
      const data = await r.json();
      setDevices(data.devices || []);
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

  const disconnectDevice = useCallback(async (deviceId) => {
    if (!window.confirm(`Disconnect WebSocket for ${deviceId}?`)) return;
    await fetch(`${API}/api/devices/${deviceId}/disconnect`, { method: 'POST' });
    await refresh();
  }, [refresh]);

  const removeDevice = useCallback(async (deviceId) => {
    if (!window.confirm(`Remove ${deviceId} from registry entirely?`)) return;
    await fetch(`${API}/api/devices/${deviceId}`, { method: 'DELETE' });
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
          <div className="ed-header-title">
            Edge Devices
            <button className="ed-btn-install" onClick={() => setShowInstallGuide(true)}>
              Install Guide
            </button>
          </div>
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

      {showInstallGuide && <InstallGuideModal onClose={() => setShowInstallGuide(false)} />}

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
          </div>
        ) : (
          <div className="ed-grid">
            {devices.map(d => (
              <DeviceCard
                key={d.device_id}
                device={d}
                onSendDirective={sendDirective}
                onDisconnect={disconnectDevice}
                onRemove={removeDevice}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
