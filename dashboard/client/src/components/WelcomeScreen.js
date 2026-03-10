import React, { useState, useRef } from 'react';
import './WelcomeScreen.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

const SUGGESTIONS = [
  "What's the weather like today?",
  "What's on my calendar this week?",
  "Show me my pending todos",
  "Give me a morning briefing",
  "What should I focus on today?",
  "Help me write a quick summary",
];

export default function WelcomeScreen({ onNewChat, stats, onToggleSidebar, sidebarOpen }) {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: form });
      if (!res.ok) throw new Error((await res.json()).error || 'Upload failed');
      const data = await res.json();
      setAttachments(prev => [...prev, data]);
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
    } finally {
      setUploading(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text && attachments.length === 0) return;
    const imageMarkdown = attachments
      .filter(a => a.type === 'image')
      .map(a => `\n![image](${a.url})`)
      .join('');
    onNewChat((text + imageMarkdown).trim());
    setInput('');
    setAttachments([]);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }

  function handleSuggestion(text) {
    onNewChat(text);
  }

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  return (
    <div className="welcome-screen">
      {/* Topbar */}
      <div className="welcome-topbar">
        {!sidebarOpen && (
          <button className="icon-btn topbar-toggle" onClick={onToggleSidebar} title="Open sidebar">
            ▶
          </button>
        )}
        <div className="topbar-spacer" />
      </div>

      {/* Hero */}
      <div className="welcome-hero">
        <div className="hero-icon">🐈</div>
        <h1 className="hero-title">nanobot</h1>
        <p className="hero-subtitle">
          Your intelligent assistant — calendar, weather, todos, and more.
        </p>

        {stats && (
          <div className="hero-stats">
            <div className="stat-pill">
              <span className="stat-num">{stats.total_conversations}</span>
              <span className="stat-lbl">conversations</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-pill">
              <span className="stat-num">{stats.total_messages}</span>
              <span className="stat-lbl">messages</span>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="welcome-input-area">
        <form className="welcome-form" onSubmit={handleSubmit}>
          {attachments.length > 0 && (
            <div className="chat-attachments" style={{ marginBottom: 8 }}>
              {attachments.map(a => (
                <div key={a.filename} className="chat-attachment-thumb">
                  {a.type === 'image' && <img src={`${window.location.origin}${a.url}`} alt="attachment" />}
                  <button className="attachment-remove" onClick={() => setAttachments(prev => prev.filter(x => x.filename !== a.filename))}>✕</button>
                </div>
              ))}
            </div>
          )}
          <div className="welcome-input-wrap">
            <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFileChange} />
            <button
              type="button"
              className={`chat-attach-btn ${uploading ? 'uploading' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              title="Attach image"
            >
              {uploading ? <span className="send-spinner" /> : '📎'}
            </button>
            <textarea
              ref={textareaRef}
              className="welcome-textarea"
              value={input}
              onChange={e => { setInput(e.target.value); autoResize(); }}
              onKeyDown={handleKeyDown}
              placeholder="Ask nanobot anything…"
              rows={1}
              autoFocus
            />
            <button
              type="submit"
              className={`welcome-send-btn ${(input.trim() || attachments.length > 0) ? 'active' : ''}`}
              disabled={!input.trim() && attachments.length === 0}
              title="Send"
            >
              ↑
            </button>
          </div>
        </form>

        {/* Suggestions */}
        <div className="suggestions">
          {SUGGESTIONS.map((s, i) => (
            <button key={i} className="suggestion-chip" onClick={() => handleSuggestion(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
