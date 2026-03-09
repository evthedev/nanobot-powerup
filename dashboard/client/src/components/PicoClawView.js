import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './WhatsAppView.css';

const API = process.env.REACT_APP_API_URL || '';

export default function PicoClawView({ onToggleSidebar, sidebarOpen }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const messagesEndRef = useRef(null);
  const lastIdRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    fetch(`${API}/api/picoclaw/status`)
      .then(r => r.json())
      .then(s => { setStatus(s); setStatusLoaded(true); })
      .catch(() => { setStatus({ enabled: false }); setStatusLoaded(true); });

    fetch(`${API}/api/picoclaw/messages`)
      .then(r => r.json())
      .then(msgs => {
        setMessages(msgs);
        if (msgs.length > 0) lastIdRef.current = msgs[msgs.length - 1].id;
      })
      .catch(() => {});
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  useEffect(() => {
    const es = new EventSource(`${API}/api/picoclaw/stream?lastId=${lastIdRef.current}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        lastIdRef.current = msg.id;
        setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
      } catch {}
    };
    return () => { es.close(); setConnected(false); };
  }, []);

  function formatTime(dateStr) {
    try { return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch { return ''; }
  }

  return (
    <div className="whatsapp-view">
      <div className="whatsapp-header">
        {!sidebarOpen && (
          <button className="icon-btn" onClick={onToggleSidebar} title="Open sidebar">▶</button>
        )}
        <div className="whatsapp-header-icon">🦐</div>
        <div className="whatsapp-header-info">
          <div className="whatsapp-header-title">Picoclaw</div>
          <div className={`whatsapp-header-status ${connected ? 'live' : 'offline'}`}>
            {connected ? 'live' : 'connecting…'}
          </div>
        </div>
        {statusLoaded && status && !status.enabled && (
          <div className="whatsapp-warning">⚠ Channel not enabled in config</div>
        )}
      </div>

      <div className="whatsapp-messages">
        {messages.length === 0 ? (
          <div className="whatsapp-empty">
            {!statusLoaded
              ? 'Loading…'
              : status?.enabled
                ? 'No messages yet — send one from your picoclaw device to start.'
                : 'Picoclaw channel is not enabled. Set channels.picoclaw.enabled = true in config.json and restart.'}
          </div>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className={`wa-message-row ${msg.direction === 'inbound' ? 'inbound' : 'outbound'}`}>
              <div className="wa-avatar">{msg.direction === 'inbound' ? '🦐' : '🐈'}</div>
              <div className="wa-message-body">
                <div className="wa-sender-name">{msg.device_id || 'default'}</div>
                <div className="wa-bubble">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                </div>
                <div className="wa-time">{formatTime(msg.created_at)}</div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="whatsapp-footer">
        <span>🦐 Live mirror of picoclaw edge device messages.</span>
      </div>
    </div>
  );
}
