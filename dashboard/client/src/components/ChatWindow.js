import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import EmojiPicker from 'emoji-picker-react';
import twemoji from 'twemoji';
import Lightbox from 'yet-another-react-lightbox';
import Zoom from 'yet-another-react-lightbox/plugins/zoom';
import 'yet-another-react-lightbox/styles.css';
import './ChatWindow.css';

function Twemoji({ children }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) twemoji.parse(ref.current, { folder: 'svg', ext: '.svg' });
  });
  return <span ref={ref}>{children}</span>;
}

const VIDEO_EXTS = /\.(mp4|webm|mov|ogg)$/i;

function ChatImg({ src, alt, onLightbox }) {
  const [broken, setBroken] = useState(false);
  const resolved = src?.startsWith('/') ? `${window.location.origin}${src}` : src;
  if (broken) {
    return (
      <div className="chat-img-broken" title={src}>
        <span>Media unavailable</span>
      </div>
    );
  }
  if (VIDEO_EXTS.test(src)) {
    return (
      <video
        src={resolved}
        className="chat-video-thumb"
        controls
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <img
      src={resolved}
      alt={alt || ''}
      className="chat-img-thumb"
      onClick={() => onLightbox(resolved)}
      onError={() => setBroken(true)}
    />
  );
}

const API_BASE = process.env.REACT_APP_API_URL || '';

export default function ChatWindow({
  conversation,
  messages,
  onSend,
  streaming,
  loading,
  onToggleSidebar,
  sidebarOpen,
}) {
  const [input, setInput]             = useState('');
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading]     = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState(null);
  const [showPicker, setShowPicker]   = useState(false);
  const bottomRef                     = useRef(null);
  const textareaRef                   = useRef(null);
  const fileInputRef                  = useRef(null);
  const pickerRef                     = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function onEmojiClick({ emoji }) {
    const ta = textareaRef.current;
    const start = ta.selectionStart;
    setInput(d => d.slice(0, start) + emoji + d.slice(ta.selectionEnd));
    setShowPicker(false);
    setTimeout(() => { ta.focus(); ta.setSelectionRange(start + emoji.length, start + emoji.length); }, 0);
  }

  useEffect(() => {
    if (!showPicker) return;
    function handler(e) { if (pickerRef.current && !pickerRef.current.contains(e.target)) setShowPicker(false); }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showPicker]);

  async function uploadFile(file) {
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

  async function handlePaste(e) {
    const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
    if (!item) return;
    e.preventDefault();
    await uploadFile(item.getAsFile());
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    await uploadFile(file);
  }

  function removeAttachment(filename) {
    setAttachments(prev => prev.filter(a => a.filename !== filename));
  }

  function handleSend() {
    const text = input.trim();
    if ((!text && attachments.length === 0) || streaming) return;
    // Append image markdown for each attachment
    const imageMarkdown = attachments
      .map(a => a.type === 'video'
        ? `\n![video](${a.url})`
        : `\n![image](${a.url})`)
      .join('');
    const fullContent = text + imageMarkdown;
    setInput('');
    setAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    onSend(fullContent);
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
    p: ({ children }) => <p><Twemoji>{children}</Twemoji></p>,
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
                    <>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                        {msg.content || (msg.streaming ? '' : '')}
                      </ReactMarkdown>
                      {msg.streaming && msg._progressText && !msg.content && (
                        <span className="progress-hint">{msg._progressText}</span>
                      )}
                    </>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {msg.content || ''}
                    </ReactMarkdown>
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
        {attachments.length > 0 && (
          <div className="chat-attachments">
            {attachments.map(a => (
              <div key={a.filename} className="chat-attachment-thumb">
                {a.type === 'image' && (
                  <img src={`${window.location.origin}${a.url}`} alt="attachment" />
                )}
                {a.type === 'video' && (
                <video src={`${window.location.origin}${a.url}`} className="chat-video-thumb attachment-video-preview" />
              )}
                <button className="attachment-remove" onClick={() => removeAttachment(a.filename)}>✕</button>
              </div>
            ))}
          </div>
        )}
        <div className="chat-input-wrap">
          {showPicker && (
            <div className="chat-emoji-picker" ref={pickerRef}>
              <EmojiPicker onEmojiClick={onEmojiClick} skinTonesDisabled height={380} />
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,video/*"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
          <button
            className={`chat-attach-btn ${uploading ? 'uploading' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || uploading}
            title="Attach image"
          >
            {uploading ? <span className="send-spinner" /> : '📎'}
          </button>
          <button className="chat-emoji-btn" onClick={() => setShowPicker(p => !p)} title="Emoji">😊</button>
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            value={input}
            onChange={e => { setInput(e.target.value); autoResize(); }}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="Message nanobot…"
            rows={1}
            disabled={streaming}
          />
          <button
            className={`chat-send-btn ${(input.trim() || attachments.length > 0) && !streaming ? 'active' : ''}`}
            onClick={handleSend}
            disabled={(!input.trim() && attachments.length === 0) || streaming}
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
