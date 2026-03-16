import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './EdgeDevicesView.css';

const API = process.env.REACT_APP_API_URL || '';

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

function DeviceCard({ device, onSendDirective, onDeleteDirective, onClearDirectives, onDisconnect, onRemove }) {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState('');
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState([]);
  const [tick, setTick] = useState(0);
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
