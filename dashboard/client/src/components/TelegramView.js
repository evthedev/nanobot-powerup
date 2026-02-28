import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './TelegramView.css';

const API = process.env.REACT_APP_API_URL || '';

export default function TelegramView({ onToggleSidebar, sidebarOpen }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState(null);       // null = loading, object = loaded
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const messagesEndRef = useRef(null);
  const lastIdRef = useRef(0);
  const eventSourceRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  // Fetch status and history on mount
  useEffect(() => {
    fetch(`${API}/api/telegram/status`)
      .then(r => r.json())
      .then(s => { setStatus(s); setStatusLoaded(true); })
      .catch(() => { setStatus({ enabled: false, hasToken: false }); setStatusLoaded(true); });

    fetch(`${API}/api/telegram/messages`)
      .then(r => r.json())
      .then(msgs => {
        setMessages(msgs);
        if (msgs.length > 0) {
          lastIdRef.current = msgs[msgs.length - 1].id;
        }
      })
      .catch(() => {});
  }, []);

  // Scroll after messages load
  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // SSE stream for live messages.
  // The server emits `id:` fields — the browser automatically sends Last-Event-ID
  // on reconnect, so the server can resume from the right position without gaps.
  useEffect(() => {
    // Pass current lastId as a fallback for the very first connection (before
    // any Last-Event-ID is established). On subsequent auto-reconnects the
    // browser uses the Last-Event-ID header instead.
    const url = `${API}/api/telegram/stream?lastId=${lastIdRef.current}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        lastIdRef.current = msg.id;
        setMessages(prev => {
          if (prev.some(m => m.id === msg.id)) return prev;
          return [...prev, msg];
        });
      } catch {}
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
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
    <div className="telegram-view">
      {/* Header */}
      <div className="telegram-header">
        {!sidebarOpen && (
          <button className="icon-btn" onClick={onToggleSidebar} title="Open sidebar">▶</button>
        )}
        <div className="telegram-header-icon">✈️</div>
        <div className="telegram-header-info">
          <div className="telegram-header-title">Telegram</div>
          <div className={`telegram-header-status ${connected ? 'live' : 'offline'}`}>
            {connected ? 'live' : 'connecting…'}
          </div>
        </div>
        {statusLoaded && status && !status.enabled && (
          <div className="telegram-warning">⚠ Bot not enabled in config</div>
        )}
      </div>

      {/* Messages */}
      <div className="telegram-messages">
        {messages.length === 0 ? (
          <div className="telegram-empty">
            {!statusLoaded
              ? 'Loading…'
              : status?.enabled
                ? 'No messages yet — send a message to your Telegram bot to get started.'
                : 'Telegram is not enabled. Add your bot token in Settings.'}
          </div>
        ) : (
          messages.map(msg => (
            <div
              key={msg.id}
              className={`tg-message-row ${msg.direction === 'inbound' ? 'inbound' : 'outbound'}`}
            >
              <div className="tg-avatar">
                {msg.direction === 'inbound' ? '👤' : '🐈'}
              </div>
              <div className="tg-message-body">
                {msg.direction === 'inbound' && msg.sender_name && (
                  <div className="tg-sender-name">{msg.sender_name}</div>
                )}
                <div className="tg-bubble">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                </div>
                <div className="tg-time">{formatTime(msg.created_at)}</div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Footer note */}
      <div className="telegram-footer">
        <span>📱 Read-only mirror of Telegram — reply from your Telegram app</span>
      </div>
    </div>
  );
}
