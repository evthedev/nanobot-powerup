import React, { useState, useEffect, useRef, useCallback } from 'react';
import './LogsPanel.css';

const API = process.env.REACT_APP_API_URL || '';

const FILTERS = [
  { id: 'all',      label: 'All' },
  { id: 'main',     label: 'Main Agent' },
  { id: 'subagent', label: 'Subagents' },
  { id: 'channel',  label: 'Channels' },
  { id: 'error',    label: 'Errors' },
];

function shortModel(model) {
  if (!model) return null;
  if (model.includes('gemini-3-flash'))   return 'gemini-3-flash';
  if (model.includes('gemini-2.5-flash')) return 'gemini-2.5f';
  if (model.includes('gemini-2.0-flash')) return 'gemini-2f';
  if (model.includes('gpt-4o-mini'))      return 'gpt-4o-mini';
  if (model.includes('gpt-4o'))           return 'gpt-4o';
  if (model.includes('claude-sonnet'))    return 'claude-sonnet';
  if (model.includes('claude-opus'))      return 'claude-opus';
  if (model.includes('claude-haiku'))     return 'claude-haiku';
  const parts = model.split('/');
  return parts[parts.length - 1] || model;
}

export default function LogsPanel({ mainModel }) {
  const [entries, setEntries]     = useState([]);
  const [filter, setFilter]       = useState('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [connected, setConnected]   = useState(false);
  const [paused, setPaused]         = useState(false);
  const [search, setSearch]         = useState('');

  const subagentModels = useRef({});
  const bottomRef  = useRef(null);
  const pauseRef   = useRef(false);
  const esRef      = useRef(null);

  pauseRef.current = paused;

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close();
    const es = new EventSource(`${API}/api/logs/stream`);
    esRef.current = es;

    es.onopen  = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      if (pauseRef.current) return;
      try {
        const entry = JSON.parse(e.data);
        if (entry.category === 'spawn' && entry.model && entry.subagentId) {
          subagentModels.current[entry.subagentId] = entry.model;
        }
        if (entry.type === 'subagent' && entry.subagentId && !entry.model) {
          entry.model = subagentModels.current[entry.subagentId] || null;
        }
        setEntries(prev => {
          const next = [...prev, { ...entry, id: Date.now() + Math.random() }];
          return next.length > 10000 ? next.slice(-10000) : next;
        });
      } catch {}
    };

    return () => es.close();
  }, []);

  useEffect(() => {
    const cleanup = connect();
    return cleanup;
  }, [connect]);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [entries, autoScroll]);

  const visibleEntries = entries.filter(e => {
    if (filter === 'error'    && e.category !== 'error' && e.level !== 'ERROR') return false;
    if (filter === 'main'     && e.type !== 'main')     return false;
    if (filter === 'subagent' && e.type !== 'subagent') return false;
    if (filter === 'channel'  && e.type !== 'channel')  return false;
    if (search && !e.msg.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  // Running token totals across the visible entries
  const tokenTotals = visibleEntries.reduce((acc, e) => {
    if (e.tokens) {
      acc.in    += e.tokens.in;
      acc.out   += e.tokens.out;
      acc.total += e.tokens.total;
      acc.calls += 1;
    }
    return acc;
  }, { in: 0, out: 0, total: 0, calls: 0 });

  function handleScroll(e) {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  }

  return (
    <div className="logs-panel">
      <div className="logs-toolbar">
        <div className="logs-title-row">
          <span className="logs-title">Agent Logs</span>
          <span className={`logs-conn-dot ${connected ? 'live' : 'dead'}`} />
          <span className="logs-conn-label">{connected ? 'live' : 'disconnected'}</span>
          <span className="logs-count">{visibleEntries.length}{entries.length !== visibleEntries.length ? `/${entries.length}` : ''} lines</span>
          {mainModel && (
            <span className="logs-main-model">
              main: <span className="model-badge model-badge-main">{shortModel(mainModel)}</span>
            </span>
          )}
          {tokenTotals.calls > 0 && (
            <span className="logs-token-summary" title={`${tokenTotals.calls} LLM calls · ${tokenTotals.in.toLocaleString()} in · ${tokenTotals.out.toLocaleString()} out`}>
              <span className="token-sum-icon">⚡</span>
              {tokenTotals.total.toLocaleString()} tok
              <span className="token-sum-detail"> ↑{tokenTotals.in.toLocaleString()} ↓{tokenTotals.out.toLocaleString()}</span>
            </span>
          )}
        </div>
        <div className="logs-controls">
          <div className="logs-filters">
            {FILTERS.map(f => (
              <button
                key={f.id}
                className={`log-filter-btn ${filter === f.id ? 'active' : ''}`}
                onClick={() => setFilter(f.id)}
              >{f.label}</button>
            ))}
          </div>
          <input
            className="logs-search"
            placeholder="Search…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            className={`log-ctrl-btn ${paused ? 'active' : ''}`}
            onClick={() => setPaused(p => !p)}
          >{paused ? '▶ Resume' : '⏸ Pause'}</button>
          <button className="log-ctrl-btn" onClick={() => setEntries([])}>🗑 Clear</button>
        </div>
      </div>

      <div className="logs-body" onScroll={handleScroll}>
        {visibleEntries.length === 0 ? (
          <div className="logs-empty">
            {connected ? 'Waiting for log entries…' : 'Not connected — is the gateway running?'}
          </div>
        ) : (
          visibleEntries.map(entry => <LogEntry key={entry.id} entry={entry} />)
        )}
        <div ref={bottomRef} />
      </div>

      {!autoScroll && (
        <button className="scroll-to-bottom" onClick={() => {
          setAutoScroll(true);
          bottomRef.current && bottomRef.current.scrollIntoView({ behavior: 'smooth' });
        }}>
          ↓ Jump to latest
        </button>
      )}
    </div>
  );
}

function LogEntry({ entry }) {
  const { ts, level, type, msg, category, model, subagentId, tokens } = entry;
  const time = ts ? ts.slice(11, 23) : '';

  const rowClass = [
    'log-row',
    'log-type-' + type,
    'log-cat-' + category,
    (level === 'ERROR' || level === 'CRITICAL') ? 'log-level-error' : '',
    level === 'WARNING' ? 'log-level-warn' : '',
  ].filter(Boolean).join(' ');

  const srcLabel =
    type === 'main'     ? 'main' :
    type === 'subagent' ? ('sub·' + (subagentId ? subagentId.slice(0, 6) : '?')) :
    type === 'channel'  ? 'chan' : 'sys';

  return (
    <div className={rowClass}>
      <span className="log-ts">{time}</span>
      <span className={'log-src log-src-' + type}>{srcLabel}</span>
      {model && (
        <span className={'model-badge model-badge-' + type}>{shortModel(model)}</span>
      )}
      {tokens ? (
        <span className="log-tokens">
          <span className="tok-total">{tokens.total.toLocaleString()}</span>
          <span className="tok-detail"> ↑{tokens.in.toLocaleString()} ↓{tokens.out.toLocaleString()}</span>
        </span>
      ) : (
        <span className="log-msg">{renderMsg(msg, category)}</span>
      )}
    </div>
  );
}

function renderMsg(msg, category) {
  if (category === 'inbound')  return React.createElement(React.Fragment, null, React.createElement('span', { className: 'msg-arrow' }, '▶ '), msg.replace('>>> INBOUND ', ''));
  if (category === 'outbound') return React.createElement(React.Fragment, null, React.createElement('span', { className: 'msg-arrow-out' }, '◀ '), msg.replace('<<< OUTBOUND ', ''));
  if (category === 'spawn')    return React.createElement(React.Fragment, null, React.createElement('span', { className: 'msg-spawn' }, '⚡ '), msg);
  if (category === 'tool')     return React.createElement(React.Fragment, null, React.createElement('span', { className: 'msg-tool' }, '🔧 '), msg);
  if (category === 'done')     return React.createElement(React.Fragment, null, React.createElement('span', { className: 'msg-done' }, '✓ '), msg);
  if (category === 'error')    return React.createElement(React.Fragment, null, React.createElement('span', { className: 'msg-err' }, '✗ '), msg);
  return msg;
}
