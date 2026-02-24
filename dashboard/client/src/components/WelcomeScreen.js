import React, { useState, useRef } from 'react';
import './WelcomeScreen.css';

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
  const textareaRef = useRef(null);

  function handleSubmit(e) {
    e.preventDefault();
    if (input.trim()) {
      onNewChat(input.trim());
      setInput('');
    }
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
          <div className="welcome-input-wrap">
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
              className={`welcome-send-btn ${input.trim() ? 'active' : ''}`}
              disabled={!input.trim()}
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
