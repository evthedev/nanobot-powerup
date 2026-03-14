import React from 'react';
import './TerminalView.css';

export default function TerminalView({ onToggleSidebar, sidebarOpen }) {
  return (
    <div className="terminal-view">
      <div className="terminal-header">
        <button className="icon-btn" onClick={onToggleSidebar} title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}>
          {sidebarOpen ? '◀' : '▶'}
        </button>
        <span className="terminal-title">Terminal</span>
      </div>
      <div className="terminal-frame-wrap">
        <iframe
          src="/ttyd"
          title="Terminal"
          className="terminal-frame"
          allow="clipboard-read; clipboard-write; popup"
        />
      </div>
    </div>
  );
}
