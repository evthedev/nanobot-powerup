import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Lightbox from 'yet-another-react-lightbox';
import Zoom from 'yet-another-react-lightbox/plugins/zoom';
import 'yet-another-react-lightbox/styles.css';
import './ChatWindow.css';

function ChatImg({ src, alt, onLightbox }) {
  const [broken, setBroken] = useState(false);
  const imgSrc = src?.startsWith('/') ? `${window.location.origin}${src}` : src;
  if (broken) {
    return (
      <div className="chat-img-broken" title={src}>
        <span>Image unavailable</span>
      </div>
    );
  }
  return (
    <img
      src={imgSrc}
      alt={alt || ''}
      className="chat-img-thumb"
      onClick={() => onLightbox(imgSrc)}
      onError={() => setBroken(true)}
    />
  );
}

export default function ChatWindow({
  conversation,
  messages,
  onSend,
  streaming,
  loading,
  onToggleSidebar,
  sidebarOpen,
}) {
  const [input, setInput]       = useState('');
  const [lightboxSrc, setLightboxSrc] = useState(null);
  const bottomRef               = useRef(null);
  const textareaRef             = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSend() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    onSend(text);
  }

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function formatTime(dateStr) {
    try {
      return new Date(dateStr).toLocaleTimeString('en-AU', {
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return ''; }
  }

  const mdComponents = {
    img: ({ src, alt }) => <ChatImg src={src} alt={alt} onLightbox={setLightboxSrc} />,
  };

  return (
    <div className="chat-window">
      <Lightbox
        open={!!lightboxSrc}
        close={() => setLightboxSrc(null)}
        slides={lightboxSrc ? [{ src: lightboxSrc }] : []}
        plugins={[Zoom]}
        zoom={{ maxZoomPixelRatio: 8, doubleTapDelay: 300 }}
        carousel={{ finite: true }}
        render={{ buttonPrev: () => null, buttonNext: () => null }}
      />
      {/* Header */}
      <div className="chat-header">
        {!sidebarOpen && (
          <button className="icon-btn" onClick={onToggleSidebar} title="Open sidebar">▶</button>
        )}
        <div className="chat-header-title">
          <span className="chat-title-text">{conversation?.title || 'Chat'}</span>
        </div>
      </div>

      {/* Messages */}
      <div className="messages-area">
        {loading ? (
          <div className="messages-loading">Loading…</div>
        ) : messages.length === 0 ? (
          <div className="messages-empty">Send a message to get started.</div>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className={`message-row ${msg.role}`}>
              <div className="message-avatar">
                {msg.role === 'user' ? '👤' : '🐈'}
              </div>
              <div className="message-body">
                <div className={`message-bubble ${msg.error ? 'error' : ''} ${msg.streaming ? 'streaming' : ''}`}>
                  {msg.role === 'assistant' ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {msg.content || (msg.streaming ? '…' : '')}
                    </ReactMarkdown>
                  ) : (
                    <span className="message-text">{msg.content}</span>
                  )}
                  {msg.streaming && <span className="cursor-blink" />}
                </div>
                <div className="message-meta">
                  <span className="message-time">{formatTime(msg.created_at)}</span>
                  {msg.tokens_used > 0 && (
                    <span className="message-tokens">{msg.tokens_used} tokens</span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="chat-input-area">
        <div className="chat-input-wrap">
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            value={input}
            onChange={e => { setInput(e.target.value); autoResize(); }}
            onKeyDown={handleKeyDown}
            placeholder="Message nanobot…"
            rows={1}
            disabled={streaming}
          />
          <button
            className={`chat-send-btn ${input.trim() && !streaming ? 'active' : ''}`}
            onClick={handleSend}
            disabled={!input.trim() || streaming}
            title="Send (Enter)"
          >
            {streaming ? <span className="send-spinner" /> : '↑'}
          </button>
        </div>
        <div className="chat-input-hint">Enter to send · Shift+Enter for new line</div>
      </div>
    </div>
  );
}
