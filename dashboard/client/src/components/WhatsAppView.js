import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import EmojiPicker from 'emoji-picker-react';
import twemoji from 'twemoji';
import './WhatsAppView.css';

function Twemoji({ text }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) twemoji.parse(ref.current, { folder: 'svg', ext: '.svg' });
  });
  return <span ref={ref}>{text}</span>;
}

const API = process.env.REACT_APP_API_URL || '';

function chatLabel(chatId) {
  if (!chatId) return 'Unknown';
  if (chatId.endsWith('@g.us')) return `Group · ${chatId.split('@')[0]}`;
  if (chatId.endsWith('@lid')) return `LID · ${chatId.split('@')[0]}`;
  return chatId.split('@')[0];
}

export default function WhatsAppView({ onToggleSidebar, sidebarOpen }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const [selectedChat, setSelectedChat] = useState(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const pickerRef = useRef(null);
  const textareaRef = useRef(null);
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
  }, [messages, selectedChat, scrollToBottom]);

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

  async function sendMessage() {
    if (!draft.trim() || !selectedChat || sending) return;
    setSending(true);
    try {
      const res = await fetch(`${API}/api/whatsapp/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: selectedChat, text: draft.trim() }),
      });
      if (res.ok) {
        setDraft('');
        // Optimistically append — SSE will also deliver it but dedup handles that
        const now = new Date().toISOString();
        setMessages(prev => [...prev, {
          id: Date.now(), direction: 'outbound', chat_id: selectedChat,
          phone_number: '', content: draft.trim(), created_at: now,
        }]);
      }
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  async function handlePaste(e) {
    const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
    if (!item) return;
    e.preventDefault();
    const file = item.getAsFile();
    setSending(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
      if (!res.ok) throw new Error('Upload failed');
      const { url } = await res.json();
      const text = `![image](${url})`;
      const now = new Date().toISOString();
      await fetch(`${API}/api/whatsapp/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: selectedChat, text }),
      });
      setMessages(prev => [...prev, {
        id: Date.now(), direction: 'outbound', chat_id: selectedChat,
        phone_number: '', content: text, created_at: now,
      }]);
    } catch (err) {
      alert(`Paste upload failed: ${err.message}`);
    } finally {
      setSending(false);
    }
  }

  function onEmojiClick({ emoji }) {
    const ta = textareaRef.current;
    const start = ta.selectionStart;
    setDraft(d => d.slice(0, start) + emoji + d.slice(ta.selectionEnd));
    setShowPicker(false);
    setTimeout(() => { ta.focus(); ta.setSelectionRange(start + emoji.length, start + emoji.length); }, 0);
  }

  // Close picker on outside click
  useEffect(() => {
    if (!showPicker) return;
    function handler(e) { if (pickerRef.current && !pickerRef.current.contains(e.target)) setShowPicker(false); }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showPicker]);

  function formatTime(dateStr) {
    try {
      return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  }

  // Build ordered chat list: most recent message first
  const chats = Object.values(
    messages.reduce((acc, msg) => {
      const key = msg.chat_id;
      if (!acc[key]) acc[key] = { chat_id: key, lastMsg: msg, unread: 0 };
      else acc[key].lastMsg = msg;
      return acc;
    }, {})
  ).sort((a, b) => new Date(b.lastMsg.created_at) - new Date(a.lastMsg.created_at));

  const threadMessages = selectedChat
    ? messages.filter(m => m.chat_id === selectedChat)
    : [];

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

      <div className="wa-body">
        {/* Chat list */}
        <div className="wa-chat-list">
          {messages.length === 0 ? (
            <div className="whatsapp-empty" style={{ padding: '20px 12px' }}>
              {!statusLoaded ? 'Loading…'
                : status?.enabled ? 'No messages yet.'
                : 'WhatsApp not enabled.'}
            </div>
          ) : chats.map(({ chat_id, lastMsg }) => (
            <div
              key={chat_id}
              className={`wa-chat-item ${selectedChat === chat_id ? 'active' : ''}`}
              onClick={() => setSelectedChat(chat_id)}
            >
              <div className="wa-chat-item-avatar">
                {chat_id.endsWith('@g.us') ? '👥' : '👤'}
              </div>
              <div className="wa-chat-item-info">
                <div className="wa-chat-item-name">{chatLabel(chat_id)}</div>
                <div className="wa-chat-item-preview">
                  {lastMsg.direction === 'outbound' ? '🐈 ' : ''}
                  {lastMsg.content.slice(0, 60)}{lastMsg.content.length > 60 ? '…' : ''}
                </div>
              </div>
              <div className="wa-chat-item-time">{formatTime(lastMsg.created_at)}</div>
            </div>
          ))}
        </div>

        {/* Message thread */}
        <div className="wa-thread">
          {!selectedChat ? (
            <div className="whatsapp-empty" style={{ marginTop: '120px' }}>
              Select a conversation
            </div>
          ) : (
            <>
              <div className="wa-thread-header">
                <span className="wa-thread-title">{chatLabel(selectedChat)}</span>
                <span className="wa-thread-id">{selectedChat}</span>
              </div>
              <div className="whatsapp-messages">
                {threadMessages.map(msg => (
                  <div key={msg.id} className={`wa-message-row ${msg.direction === 'inbound' ? 'inbound' : 'outbound'}`}>
                    <div className="wa-avatar">{msg.direction === 'inbound' ? '👤' : '🐈'}</div>
                    <div className="wa-message-body">
                      <div className="wa-sender-name">{msg.phone_number || msg.chat_id}</div>
                      <div className="wa-bubble">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ p: ({children}) => <p><Twemoji text={children} /></p> }}>{msg.content}</ReactMarkdown>
                      </div>
                      <div className="wa-time">{formatTime(msg.created_at)}</div>
                    </div>
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
              <div className="wa-compose">
                {showPicker && (
                  <div className="wa-emoji-picker" ref={pickerRef}>
                    <EmojiPicker onEmojiClick={onEmojiClick} skinTonesDisabled height={380} />
                  </div>
                )}
                <button className="wa-emoji-btn" onClick={() => setShowPicker(p => !p)}>😊</button>
                <textarea
                  ref={textareaRef}
                  className="wa-compose-input"
                  placeholder="Reply as agent…"
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={onKeyDown}
                  onPaste={handlePaste}
                  rows={1}
                />
                <button className="wa-compose-send" onClick={sendMessage} disabled={sending || !draft.trim()}>
                  {sending ? '⏳' : '↑'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
