import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './TelegramView.css';

const API = process.env.REACT_APP_API_URL || '';

export default function TelegramView({ onToggleSidebar, sidebarOpen }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState(null);
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
      .then(s => setStatus(s))
      .catch(() => setStatus({ enabled: false, hasToken: false }));

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

  // SSE stream for live messages
  useEffect(() => {
    const url = `${API}/api/telegram/stream?lastId=${lastIdRef.current}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        setMessages(prev => {
          // Avoid duplicates
          if (prev.some(m => m.id === msg.id)) return prev;
          return [...prev, msg];
        });
        lastIdRef.current = msg.id;
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
        {status && !status.enabled && (
          <div className="telegram-warning">⚠ Bot not enabled in config</div>
        )}
      </div>

      {/* Messages */}
      <div className="telegram-messages">
        {messages.length === 0 ? (
          <div className="telegram-empty">
            {status?.enabled
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
