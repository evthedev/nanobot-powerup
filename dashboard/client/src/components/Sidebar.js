import React, { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { useLocation, useNavigate } from 'react-router-dom';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  activeConvId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  stats,
  serverOk,
  environmentName,
  isOpen,
  onToggle,
  onLogs,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const showLogs      = location.pathname === '/logs';
  const showTelegram  = location.pathname === '/telegram';
  const showWhatsApp  = location.pathname === '/whatsapp';
  const showPicoClaw  = location.pathname === '/picoclaw' || location.pathname === '/devices';
  const showSettings  = location.pathname === '/settings';
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [hoveredId, setHoveredId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  function startEdit(conv, e) {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title);
  }

  function commitEdit(id) {
    if (editTitle.trim()) onRename(id, editTitle.trim());
    setEditingId(null);
  }

  function handleKeyDown(e, id) {
    if (e.key === 'Enter') commitEdit(id);
    if (e.key === 'Escape') setEditingId(null);
  }

  function handleDelete(id, e) {
    e.stopPropagation();
    if (confirmDelete === id) {
      onDelete(id);
      setConfirmDelete(null);
    } else {
      setConfirmDelete(id);
      setTimeout(() => setConfirmDelete(null), 2500);
    }
  }

  function timeAgo(dateStr) {
    try {
      return formatDistanceToNow(new Date(dateStr), { addSuffix: true });
    } catch {
      return '';
    }
  }

  return (
    <aside className={`sidebar ${isOpen ? 'open' : 'closed'}`}>
      {/* Header */}
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <span className="brand-icon">🐈</span>
          {isOpen && <span className="brand-name">{environmentName || 'nanobot'}</span>}
        </div>
        <button className="icon-btn toggle-btn" onClick={onToggle} title={isOpen ? 'Collapse' : 'Expand'}>
          {isOpen ? '◀' : '▶'}
        </button>
      </div>

      {/* New Chat Button */}
      <div className="sidebar-actions">
        <button className="new-chat-btn" onClick={onNew}>
          <span className="btn-icon">✏️</span>
          {isOpen && <span>New Chat</span>}
        </button>
        <button
          className={`logs-nav-btn ${showTelegram ? 'active' : ''}`}
          onClick={() => navigate('/telegram')}
          title="Telegram Chat"
        >
          <span className="btn-icon">✈️</span>
          {isOpen && <span>Telegram</span>}
        </button>
        <button
          className={`logs-nav-btn ${showWhatsApp ? 'active' : ''}`}
          onClick={() => navigate('/whatsapp')}
          title="WhatsApp Chat"
        >
          <span className="btn-icon">💬</span>
          {isOpen && <span>WhatsApp</span>}
        </button>
        <button
          className={`logs-nav-btn ${showPicoClaw ? 'active' : ''}`}
          onClick={() => navigate('/devices')}
          title="Edge Devices"
        >
          <span className="btn-icon">🔌</span>
          {isOpen && <span>Edge Devices</span>}
        </button>
        <button
          className={`logs-nav-btn ${showLogs ? 'active' : ''}`}
          onClick={onLogs}
          title="Agent Logs"
        >
          <span className="btn-icon">📋</span>
          {isOpen && <span>Logs</span>}
        </button>
      </div>

      {/* Conversations List */}
      {isOpen && (
        <div className="conversations-section">
          <div className="section-label">Conversations</div>
          <div className="conversations-list">
            {conversations.length === 0 ? (
              <div className="empty-state">No conversations yet</div>
            ) : (
              conversations.map(conv => (
                <div
                  key={conv.id}
                  className={`conv-item ${conv.id === activeConvId ? 'active' : ''}`}
                  onClick={() => onSelect(conv.id)}
                  onMouseEnter={() => setHoveredId(conv.id)}
                  onMouseLeave={() => { setHoveredId(null); setConfirmDelete(null); }}
                >
                  <div className="conv-icon">💬</div>
                  <div className="conv-body">
                    {editingId === conv.id ? (
                      <input
                        className="conv-edit-input"
                        value={editTitle}
                        onChange={e => setEditTitle(e.target.value)}
                        onBlur={() => commitEdit(conv.id)}
                        onKeyDown={e => handleKeyDown(e, conv.id)}
                        autoFocus
                        onClick={e => e.stopPropagation()}
                      />
                    ) : (
                      <>
                        <div className="conv-title">{conv.title}</div>
                        <div className="conv-meta">
                          <span className="conv-time">{timeAgo(conv.updated_at)}</span>
                          {conv.message_count > 0 && (
                            <span className="conv-count">{conv.message_count} msg</span>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                  {hoveredId === conv.id && editingId !== conv.id && (
                    <div className="conv-actions" onClick={e => e.stopPropagation()}>
                      <button className="conv-action-btn" onClick={e => startEdit(conv, e)} title="Rename">
                        ✏️
                      </button>
                      <button
                        className={`conv-action-btn delete-btn ${confirmDelete === conv.id ? 'confirm' : ''}`}
                        onClick={e => handleDelete(conv.id, e)}
                        title={confirmDelete === conv.id ? 'Click again to confirm' : 'Delete'}
                      >
                        {confirmDelete === conv.id ? '⚠️' : '🗑️'}
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Footer Stats */}
      {isOpen && (
        <div className="sidebar-footer">
          <div className={`status-dot ${serverOk === true ? 'ok' : serverOk === false ? 'err' : 'loading'}`} />
          <div className="footer-stats">
            {serverOk === false ? (
              <span className="stat-err">Server offline</span>
            ) : stats ? (
              <>
                <span>{stats.total_conversations} chats</span>
                <span className="stat-sep">·</span>
                <span>{stats.total_messages} messages</span>
              </>
            ) : (
              <span>Connecting…</span>
            )}
          </div>
          <button
            className={`icon-btn settings-btn ${showSettings ? 'active' : ''}`}
            onClick={() => navigate('/settings')}
            title="Settings"
            data-testid="settings-btn"
          >
            ⚙️
          </button>
        </div>
      )}
    </aside>
  );
}
