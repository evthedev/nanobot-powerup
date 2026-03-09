import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './WhatsAppView.css';

const API = process.env.REACT_APP_API_URL || '';

export default function WhatsAppView({ onToggleSidebar, sidebarOpen }) {
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
    fetch(`${API}/api/whatsapp/status`)
      .then(r => r.json())
      .then(s => { setStatus(s); setStatusLoaded(true); })
      .catch(() => { setStatus({ enabled: false, connected: false }); setStatusLoaded(true); });

    fetch(`${API}/api/whatsapp/messages`)
      .then(r => r.json())
      .then(msgs => {
        setMessages(msgs);
        if (msgs.length > 0) lastIdRef.current = msgs[msgs.length - 1].id;
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    const url = `${API}/api/whatsapp/stream?lastId=${lastIdRef.current}`;
    const es = new EventSource(url);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        lastIdRef.current = msg.id;
        setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
      } catch {}
    };
    return () => {
      es.close();
      setConnected(false);
    };
  }, []);

  function formatTime(dateStr) {
    try {
      return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  }

  return (
    <div className="whatsapp-view">
      <div className="whatsapp-header">
        {!sidebarOpen && (
          <button className="icon-btn" onClick={onToggleSidebar} title="Open sidebar">▶</button>
        )}
        <div className="whatsapp-header-icon">💬</div>
        <div className="whatsapp-header-info">
          <div className="whatsapp-header-title">WhatsApp</div>
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
                ? 'No WhatsApp messages yet — send one to your linked account to start tracking.'
                : 'WhatsApp is not enabled. Configure it in Settings.'}
          </div>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className={`wa-message-row ${msg.direction === 'inbound' ? 'inbound' : 'outbound'}`}>
              <div className="wa-avatar">{msg.direction === 'inbound' ? '👤' : '🐈'}</div>
              <div className="wa-message-body">
                <div className="wa-sender-name">
                  {msg.phone_number || msg.chat_id || 'unknown'}
                </div>
                <div className="wa-chat-id">{msg.chat_id}</div>
                <div className="wa-bubble">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                </div>
                <div className="wa-time">{formatTime(msg.created_at)}</div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="whatsapp-footer">
        <span>📱 Live mirror of `whatsapp_messages` from the bridge channel.</span>
      </div>
    </div>
  );
}
