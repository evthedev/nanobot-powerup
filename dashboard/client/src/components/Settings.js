import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import './Settings.css';

const API = process.env.REACT_APP_API_URL || '';

// ── Workspace Docs Section ───────────────────────────────────────────────────
const WORKSPACE_DOC_META = {
  'SOUL.md':      { icon: '🧬', label: 'Soul',      badge: 'config',  desc: 'Agent identity & values' },
  'AGENTS.md':    { icon: '🤖', label: 'Agents',    badge: 'config',  desc: 'Agent behaviour rules' },
  'USER.md':      { icon: '👤', label: 'User',       badge: 'runtime', desc: 'Agent-maintained user profile' },
  'TOOLS.md':     { icon: '🔧', label: 'Tools',     badge: 'config',  desc: 'Tool usage guidelines' },
  'HEARTBEAT.md': { icon: '💓', label: 'Heartbeat', badge: 'runtime', desc: 'Active task queue' },
};

function WorkspaceSection({ api }) {
  const [docs, setDocs]           = useState([]);
  const [loading, setLoading]     = useState(true);
  const [expandedDoc, setExpanded] = useState(null);

  useEffect(() => {
    fetch(`${api}/api/workspace/docs`)
      .then(r => r.ok ? r.json() : [])
      .then(d => { setDocs(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [api]);

  function toggle(name) {
    setExpanded(v => v === name ? null : name);
  }

  return (
    <section className="settings-section">
      <h3>📄 Workspace Files</h3>
      {loading ? (
        <p className="field-help">Loading…</p>
      ) : (
        <div className="wsdoc-list">
          {docs.map(doc => {
            const meta       = WORKSPACE_DOC_META[doc.name] || { icon: '📄', label: doc.name, badge: 'config', desc: '' };
            const isExpanded = expandedDoc === doc.name;
            const isRuntime  = meta.badge === 'runtime';
            return (
              <div key={doc.name} className={`wsdoc-card ${isExpanded ? 'expanded' : ''}`}>
                <button className="wsdoc-header" onClick={() => toggle(doc.name)}>
                  <span className="wsdoc-icon">{meta.icon}</span>
                  <span className="wsdoc-title">
                    <span className="wsdoc-name">{doc.name}</span>
                    <span className="wsdoc-desc">{meta.desc}</span>
                  </span>
                  <span className="wsdoc-meta">
                    <span className={`wsdoc-badge ${meta.badge}`}>{meta.badge}</span>
                    {doc.exists
                      ? <span className="wsdoc-status ok">●</span>
                      : <span className="wsdoc-status missing">○ missing</span>
                    }
                    <span className="wsdoc-chevron">{isExpanded ? '▾' : '▸'}</span>
                  </span>
                </button>

                {isExpanded && (
                  <div className="wsdoc-body">
                    <div className="wsdoc-path">
                      <span className="wsdoc-path-label">path</span>
                      <code className="wsdoc-path-value">{doc.path}</code>
                    </div>
                    {doc.exists ? (
                      <pre className={`wsdoc-content ${isRuntime ? 'runtime' : ''}`}>{doc.content}</pre>
                    ) : (
                      <p className="wsdoc-missing-msg">File does not exist at runtime yet.</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function fileExt(filename) {
  return filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';
}

// ── WhatsApp Section (pairing QR from dashboard) ──────────────────────────────
function WhatsAppSection({ api, Field: FieldComponent }) {
  const [status, setStatus] = useState({ enabled: false, pairing: false, connected: false });
  const [qr, setQr] = useState(null);

  const fetchStatus = useCallback(() => {
    fetch(`${api}/api/whatsapp/status`)
      .then(r => r.ok ? r.json() : {})
      .then(d => setStatus(d))
      .catch(() => setStatus({ enabled: false, pairing: false, connected: false }));
  }, [api]);

  const fetchQr = useCallback(() => {
    fetch(`${api}/api/whatsapp/qr`)
      .then(r => r.ok ? r.json() : {})
      .then(d => d.status === 'pending' && d.qr ? setQr(d.qr) : setQr(null))
      .catch(() => setQr(null));
  }, [api]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    if (status.pairing) fetchQr();
    else setQr(null);
  }, [status.pairing, fetchQr]);

  // Poll when pairing (QR refreshes every ~60s) or when enabled (to detect connect)
  useEffect(() => {
    if (!status.enabled) return;
    const id = setInterval(() => {
      fetchStatus();
      if (status.pairing) fetchQr();
    }, 3000);
    return () => clearInterval(id);
  }, [status.enabled, status.pairing, fetchStatus, fetchQr]);

  const qrImageUrl = qr
    ? `https://api.qrserver.com/v1/create-qr-code/?size=256x256&data=${encodeURIComponent(qr)}`
    : null;

  return (
    <section className="settings-section">
      <h3>💬 WhatsApp</h3>
      <FieldComponent
        id="whatsapp_allowed_numbers"
        label="Allowed Phone Numbers"
        placeholder="61412345678, 61498765432"
        helpText="Comma-separated, no + prefix"
        isPassword={false}
      />
      {status.enabled && (
        <div className="whatsapp-pairing" style={{ marginTop: '1rem' }}>
          {status.connected && (
            <p className="field-help" style={{ color: 'var(--success, #22c55e)' }}>
              ✅ WhatsApp connected
            </p>
          )}
          {status.pairing && qrImageUrl && (
            <div className="whatsapp-qr-box" style={{ marginTop: '0.5rem' }}>
              <p className="field-help">Scan with WhatsApp → Linked Devices</p>
              <img
                src={qrImageUrl}
                alt="WhatsApp pairing QR"
                style={{ display: 'block', marginTop: '0.5rem', border: '1px solid #ccc', borderRadius: 8 }}
              />
            </div>
          )}
          {status.enabled && !status.connected && !status.pairing && (
            <p className="field-help" style={{ marginTop: '0.5rem' }}>
              Waiting for bridge… Ensure the WhatsApp bridge container is running.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function SkillsSection({ api }) {
  const [skills, setSkills]               = useState({ workspace: [], auto: [] });
  const [loading, setLoading]             = useState(true);
  const [expandedKey, setExpandedKey]     = useState(null); // 'skills/ping-test'
  const [activeFile, setActiveFile]       = useState(null); // filename string
  const [fileContent, setFileContent]     = useState(null); // { content } | { error } | null
  const [fileLoading, setFileLoading]     = useState(false);
  const contentCache                      = useRef({});     // cacheKey → content string
  // prState[skillName] = { status: 'idle'|'loading'|'success'|'error', prUrl?, prNumber?, error? }
  const [prState, setPrState]             = useState({});
  // toggleState[`source/skillName`] = 'idle' | 'saving'
  const [toggleState, setToggleState]     = useState({});

  useEffect(() => {
    fetch(`${api}/api/skills`)
      .then(r => r.ok ? r.json() : { workspace: [], auto: [] })
      .then(d => { setSkills(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [api]);

  function toggleSkill(source, name) {
    const key = `${source}/${name}`;
    if (expandedKey === key) {
      setExpandedKey(null);
      setActiveFile(null);
      setFileContent(null);
    } else {
      setExpandedKey(key);
      setActiveFile(null);
      setFileContent(null);
    }
  }

  async function openFile(source, skill, file) {
    setActiveFile(file);
    const cacheKey = `${source}/${skill}/${file}`;
    if (contentCache.current[cacheKey] !== undefined) {
      setFileContent({ content: contentCache.current[cacheKey] });
      return;
    }
    setFileLoading(true);
    setFileContent(null);
    try {
      const r = await fetch(`${api}/api/skills/content?source=${encodeURIComponent(source)}&skill=${encodeURIComponent(skill)}&file=${encodeURIComponent(file)}`);
      const data = await r.json();
      contentCache.current[cacheKey] = data.content || data.error || '';
      setFileContent(data);
    } catch (e) {
      setFileContent({ error: e.message });
    } finally {
      setFileLoading(false);
    }
  }

  async function submitPr(skillName, e) {
    e.stopPropagation();
    setPrState(s => ({ ...s, [skillName]: { status: 'loading' } }));
    try {
      const r    = await fetch(`${api}/api/skills/promote`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ skillName }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      setPrState(s => ({ ...s, [skillName]: { status: 'success', prUrl: data.prUrl, prNumber: data.prNumber } }));
    } catch (err) {
      setPrState(s => ({ ...s, [skillName]: { status: 'error', error: err.message } }));
    }
  }

  async function toggleEnabled(source, skillName, currentEnabled, e) {
    e.stopPropagation();
    const key     = `${source}/${skillName}`;
    const newVal  = !currentEnabled;
    setToggleState(s => ({ ...s, [key]: 'saving' }));

    // Optimistic update
    setSkills(prev => {
      const field = source === 'skills-auto' ? 'auto' : 'workspace';
      return {
        ...prev,
        [field]: prev[field].map(s => s.name === skillName ? { ...s, enabled: newVal } : s),
      };
    });

    try {
      const r = await fetch(`${api}/api/skills/toggle`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ source, skillName, enabled: newVal }),
      });
      if (!r.ok) throw new Error((await r.json()).error || `HTTP ${r.status}`);
    } catch {
      // Revert on failure
      setSkills(prev => {
        const field = source === 'skills-auto' ? 'auto' : 'workspace';
        return {
          ...prev,
          [field]: prev[field].map(s => s.name === skillName ? { ...s, enabled: currentEnabled } : s),
        };
      });
    } finally {
      setToggleState(s => ({ ...s, [key]: 'idle' }));
    }
  }

  function SkillGroup({ label, badge, source, list }) {
    if (!list.length) return null;
    const isAuto = source === 'skills-auto';
    return (
      <div className="skills-group">
        <div className="skills-group-header">
          <span>{label}</span>
          <span className={`skill-source-badge ${badge}`}>{list.length}</span>
        </div>
        {list.map(skill => {
          const key        = `${source}/${skill.name}`;
          const isExpanded = expandedKey === key;
          const pr         = prState[skill.name] || { status: 'idle' };
          const isSaving   = toggleState[key] === 'saving';
          return (
            <div key={key} className={`skill-card ${isExpanded ? 'expanded' : ''} ${skill.enabled === false ? 'skill-disabled' : ''}`}>
              <div className="skill-card-header-row">
                <button
                  className="skill-card-header"
                  onClick={() => toggleSkill(source, skill.name)}
                >
                  <span className="skill-name">{skill.name}</span>
                  <span className="skill-meta">
                    <span className="skill-file-count">{skill.files.length} file{skill.files.length !== 1 ? 's' : ''}</span>
                    <span className="skill-chevron">{isExpanded ? '▾' : '▸'}</span>
                  </span>
                </button>

                <button
                  className={`skill-toggle ${skill.enabled !== false ? 'on' : 'off'} ${isSaving ? 'saving' : ''}`}
                  onClick={e => toggleEnabled(source, skill.name, skill.enabled !== false, e)}
                  title={skill.enabled !== false ? 'Disable skill' : 'Enable skill'}
                  disabled={isSaving}
                >
                  <span className="skill-toggle-thumb" />
                </button>

                {isAuto && (
                  <div className="skill-pr-action" onClick={e => e.stopPropagation()}>
                    {pr.status === 'idle' && (
                      <button className="skill-pr-btn" onClick={e => submitPr(skill.name, e)} title="Submit PR to promote this skill to the base layer">
                        ↑ Submit PR
                      </button>
                    )}
                    {pr.status === 'loading' && (
                      <span className="skill-pr-loading">Submitting…</span>
                    )}
                    {pr.status === 'success' && (
                      <a className="skill-pr-success" href={pr.prUrl} target="_blank" rel="noopener noreferrer" title={`PR #${pr.prNumber}`}>
                        ✓ PR #{pr.prNumber} ↗
                      </a>
                    )}
                    {pr.status === 'error' && (
                      <span className="skill-pr-error" title={pr.error}>
                        ✗ Failed
                        <button className="skill-pr-retry" onClick={e => submitPr(skill.name, e)}>retry</button>
                      </span>
                    )}
                  </div>
                )}
              </div>

              {isExpanded && (
                <div className="skill-card-body">
                  <div className="skill-file-tabs">
                    {skill.files.map(f => {
                      const ext = fileExt(f);
                      return (
                        <button
                          key={f}
                          className={`skill-file-tab ext-${ext} ${activeFile === f ? 'active' : ''}`}
                          onClick={() => openFile(source, skill.name, f)}
                        >
                          <span className="skill-file-ext-badge">{ext || 'txt'}</span>
                          {f}
                        </button>
                      );
                    })}
                  </div>

                  {activeFile && (
                    <div className="skill-file-viewer">
                      {fileLoading && <div className="skill-file-loading">Loading…</div>}
                      {!fileLoading && fileContent && (
                        fileContent.error
                          ? <div className="skill-file-error">{fileContent.error}</div>
                          : <pre className={`skill-file-content ext-${fileExt(activeFile)}`}>{fileContent.content}</pre>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  const totalSkills = skills.workspace.length + skills.auto.length;

  return (
    <section className="settings-section">
      <h3>🧠 Skills {!loading && <span className="skills-total-badge">{totalSkills}</span>}</h3>
      {loading ? (
        <p className="field-help">Loading skills…</p>
      ) : totalSkills === 0 ? (
        <p className="field-help">No skills found in workspace.</p>
      ) : (
        <div className="skills-list">
          <SkillGroup label="Workspace"     badge="workspace" source="skills"      list={skills.workspace} />
          <SkillGroup label="Auto-Generated" badge="auto"     source="skills-auto" list={skills.auto} />
        </div>
      )}
    </section>
  );
}

// ── ModelSelector ─────────────────────────────────────────────────────────────
function ModelSelector({ id, label, value, onChange, options, loading, helpText }) {
  const [query, setQuery]   = useState(value || '');
  const [open, setOpen]     = useState(false);
  const wrapRef             = useRef(null);

  // Keep query in sync when value changes from outside (e.g. config reload)
  useEffect(() => { setQuery(value || ''); }, [value]);

  // Close on click-outside
  useEffect(() => {
    function handler(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const filtered = useMemo(() => {
    if (!options || !options.length) return [];
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(o =>
      o.id.toLowerCase().includes(q) || (o.name && o.name.toLowerCase().includes(q))
    );
  }, [options, query]);

  function select(modelId) {
    setQuery(modelId);
    onChange(modelId);
    setOpen(false);
  }

  function handleKey(e) {
    if (e.key === 'Escape') { setOpen(false); e.target.blur(); }
    if (e.key === 'Enter')  { onChange(query); setOpen(false); e.target.blur(); }
  }

  return (
    <div className="settings-field" ref={wrapRef}>
      <label htmlFor={id}>{label}</label>
      <div className="model-selector-wrap">
        <div className="field-input-wrap">
          <input
            id={id}
            type="text"
            value={query}
            onChange={e => { setQuery(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            onKeyDown={handleKey}
            onBlur={e => {
              // Commit typed value on blur unless user clicked a dropdown item
              setTimeout(() => { onChange(query); }, 120);
            }}
            placeholder={loading ? 'Loading models…' : 'Search or type model ID…'}
            autoComplete="off"
            spellCheck="false"
          />
        </div>

        {open && (loading || filtered.length > 0) && (
          <div className="model-dropdown" role="listbox">
            {loading && <div className="model-dropdown-empty">Loading…</div>}
            {!loading && filtered.length === 0 && (
              <div className="model-dropdown-empty">No matches</div>
            )}
            {!loading && filtered.slice(0, 150).map(opt => (
              <div
                key={opt.id}
                className={`model-dropdown-item ${opt.id === value ? 'selected' : ''}`}
                role="option"
                aria-selected={opt.id === value}
                onMouseDown={e => { e.preventDefault(); select(opt.id); }}
              >
                <span className="model-dropdown-id">{opt.id}</span>
                {opt.name && opt.name !== opt.id && (
                  <span className="model-dropdown-name">{opt.name}</span>
                )}
              </div>
            ))}
            {!loading && filtered.length > 150 && (
              <div className="model-dropdown-more">
                +{filtered.length - 150} more — type to narrow
              </div>
            )}
          </div>
        )}
      </div>
      {helpText && <p className="field-help">{helpText}</p>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

export default function Settings({ onToggleSidebar, sidebarOpen }) {
  const [saving, setSaving]       = useState(false);
  const [status, setStatus]       = useState(null);    // { type: 'success'|'error', msg }
  const [visible, setVisible]     = useState({});
  const [googleStatus, setGoogleStatus] = useState(undefined); // undefined = loading, null = failed/disconnected

  // Model selector state
  const [modelOptions, setModelOptions]   = useState([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsProvider, setModelsProvider] = useState(null);

  const [fields, setFields] = useState({
    openrouter_api_key:       '',
    nvidia_api_key:           '',
    grok_api_key:             '',
    brave_api_key:            '',
    tavily_api_key:           '',
    maps_api_key:             '',
    main_llm:                 '',
    smart_model:              '',
    whatsapp_allowed_numbers: '',
    telegram_token:           '',
    capsolver_api_key:        '',
    gmail_email:              '',
    gmail_app_password:       '',
    github_token:             '',
    github_repo:              '',
  });

  const loadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      const r = await fetch(`${API}/api/models`);
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setModelOptions(data.models || []);
      setModelsProvider(data.provider || null);
    } catch (e) {
      setModelOptions([]);
    } finally {
      setModelsLoading(false);
    }
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/config`);
      if (!r.ok) throw new Error(await r.text());
      const cfg = await r.json();

      setFields({
        openrouter_api_key:       cfg.providers?.openrouter?.apiKey       || '',
        nvidia_api_key:           cfg.providers?.nvidia?.apiKey           || '',
        grok_api_key:             cfg.providers?.grok?.apiKey             || '',
        brave_api_key:            cfg.tools?.web?.search?.apiKey          || '',
        tavily_api_key:           cfg.tools?.web?.search?.tavilyApiKey    || '',
        maps_api_key:             cfg.tools?.google?.mapsApiKey           || '',
        main_llm:                 cfg.agents?.defaults?.model             || '',
        smart_model:              cfg.agents?.defaults?.smartModel || cfg.agents?.defaults?.smart_model || '',
        whatsapp_allowed_numbers: (cfg.channels?.whatsapp?.allowFrom || []).join(', '),
        telegram_token:           cfg.channels?.telegram?.token           || '',
        capsolver_api_key:        cfg.tools?.capsolver?.api_key           || '',
        gmail_email:              cfg.tools?.gmail?.email                 || '',
        gmail_app_password:       cfg.tools?.gmail?.app_password          || '',
        github_token:             cfg.tools?.github?.token                || '',
        github_repo:              cfg.tools?.github?.repo                 || '',
      });
    } catch (e) {
      setStatus({ type: 'error', msg: 'Failed to load config: ' + e.message });
    }
  }, []);

  const loadGoogleStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/google/status`);
      setGoogleStatus(r.ok ? await r.json() : { connected: false });
    } catch {
      setGoogleStatus({ connected: false });
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadGoogleStatus();
    loadModels();
  }, [loadConfig, loadGoogleStatus, loadModels]);

  // Listen for the popup's postMessage after OAuth completes
  useEffect(() => {
    function onMessage(e) {
      if (e.data?.type === 'google_auth_success') {
        setStatus({ type: 'success', msg: `✅ ${e.data.message}` });
        loadGoogleStatus();
        setTimeout(() => setStatus(null), 5000);
      } else if (e.data?.type === 'google_auth_error') {
        setStatus({ type: 'error', msg: `❌ Google auth failed: ${e.data.message}` });
      }
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [loadGoogleStatus]);

  async function saveConfig() {
    setSaving(true);
    setStatus(null);
    try {
      const updates = {
        agents: {
          defaults: {
            model:      fields.main_llm.trim(),
            smartModel: fields.smart_model.trim(),
          },
        },
      tools: {
        gmail: {
          email:        fields.gmail_email.trim(),
          app_password: fields.gmail_app_password.trim(),
        },
        capsolver: {
          api_key: fields.capsolver_api_key.trim(),
        },
        github: {
          token: fields.github_token.trim(),
          repo:  fields.github_repo.trim(),
        },
      },
        channels: {
          whatsapp: {
            allowFrom: fields.whatsapp_allowed_numbers
              .split(',')
              .map(n => n.trim())
              .filter(Boolean),
          },
        },
      };

      const r = await fetch(`${API}/api/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!r.ok) throw new Error(await r.text());

      // Restart gateway so the new models take effect
      setStatus({ type: 'success', msg: '✅ Saved — restarting gateway…' });
      try {
        const rr = await fetch(`${API}/api/gateway/restart`, { method: 'POST' });
        const rd = await rr.json();
        if (rr.ok) {
          setStatus({ type: 'success', msg: '✅ Saved & gateway restarted.' });
        } else {
          setStatus({ type: 'success', msg: `✅ Saved. Restart warning: ${rd.error || 'unknown'}` });
        }
      } catch {
        setStatus({ type: 'success', msg: '✅ Saved. (Could not reach restart endpoint.)' });
      }

      await loadGoogleStatus();
      setTimeout(() => setStatus(null), 5000);
    } catch (e) {
      setStatus({ type: 'error', msg: '❌ Failed to save: ' + e.message });
    } finally {
      setSaving(false);
    }
  }

  function connectGoogle() {
    if (!googleHasCreds) {
      setStatus({
        type: 'error',
        msg: '❌ Google OAuth credentials are not configured on this server. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your deployment secrets (or re-run make setup locally).',
      });
      return;
    }
    const popup = window.open(
      `${API}/api/google/auth`,
      'google_oauth',
      'width=520,height=650,left=200,top=100,resizable=yes,scrollbars=yes'
    );
    if (!popup) {
      setStatus({
        type: 'error',
        msg: '❌ Pop-up blocked — please allow pop-ups for this page and try again.',
      });
    }
  }

  async function disconnectGoogle() {
    try {
      const r = await fetch(`${API}/api/google/disconnect`, { method: 'POST' });
      if (!r.ok) throw new Error(await r.text());
      await loadGoogleStatus();
      setStatus({ type: 'success', msg: '✅ Google account disconnected.' });
      setTimeout(() => setStatus(null), 3000);
    } catch (e) {
      setStatus({ type: 'error', msg: '❌ ' + e.message });
    }
  }

  function toggle(key) { setVisible(v => ({ ...v, [key]: !v[key] })); }
  function set(key, val) { setFields(f => ({ ...f, [key]: val })); }

  function Field({ id, label, placeholder, helpText, isPassword = true, readOnly = false }) {
    return (
      <div className="settings-field">
        <label htmlFor={id}>
          {label}
          {readOnly && <span className="field-readonly-badge">runtime</span>}
        </label>
        <div className="field-input-wrap">
          <input
            id={id}
            type={isPassword && !visible[id] ? 'password' : 'text'}
            value={fields[id]}
            onChange={readOnly ? undefined : e => set(id, e.target.value)}
            placeholder={readOnly ? '— not set —' : placeholder}
            autoComplete="off"
            data-testid={id}
            readOnly={readOnly}
            className={readOnly ? 'readonly-input' : ''}
          />
          {isPassword && (
            <button
              type="button"
              className="visibility-btn"
              onClick={() => toggle(id)}
              title={visible[id] ? 'Hide' : 'Show'}
            >
              {visible[id] ? '🙈' : '👁️'}
            </button>
          )}
        </div>
        {helpText && <p className="field-help">{helpText}</p>}
      </div>
    );
  }

  // ── Google status badge ──
  function GoogleBadge() {
    if (googleStatus === undefined) return <span className="google-status-badge disconnected">Loading…</span>;
    if (!googleStatus?.connected)  return <span className="google-status-badge disconnected">Not connected</span>;
    if (googleStatus.expired)      return <span className="google-status-badge expired">Token expired</span>;
    return <span className="google-status-badge connected">Connected</span>;
  }

  const googleConnected = googleStatus?.connected && !googleStatus?.expired;
  // false only when the API explicitly tells us credentials are absent
  const googleHasCreds = googleStatus?.hasCredentials !== false;

  return (
    <div className="settings-page">

      {/* Toolbar */}
      <div className="settings-toolbar">
        <div className="settings-title-row">
          {!sidebarOpen && onToggleSidebar && (
            <button className="log-ctrl-btn settings-menu-btn" onClick={onToggleSidebar} title="Open menu">☰</button>
          )}
          <span className="settings-title">⚙️ Settings</span>
        </div>
        <div className="settings-toolbar-actions">
          <button className="btn-secondary" onClick={loadConfig} disabled={saving}>
            🔄 Reload
          </button>
          <button
            className="btn-primary"
            onClick={saveConfig}
            disabled={saving}
            data-testid="save-config-btn"
          >
            {saving ? 'Saving…' : '💾 Save'}
          </button>
        </div>
      </div>

      <div className="settings-body">
        <div className="settings-content">

          {/* AI Providers */}
          <section className="settings-section">
            <h3>🤖 AI Providers</h3>

            {/* Model selectors */}
            <div className="model-selectors-group">
              <div className="model-selectors-header">
                <span className="model-selectors-label">
                  Models
                  {modelsProvider && (
                    <span className="model-provider-badge">{modelsProvider}</span>
                  )}
                </span>
                <button
                  className="btn-link model-refresh-btn"
                  onClick={async () => {
                    await fetch(`${API}/api/models/refresh`, { method: 'POST' });
                    loadModels();
                  }}
                  disabled={modelsLoading}
                  title="Refresh model list from provider"
                >
                  {modelsLoading ? '⟳ Loading…' : '⟳ Refresh'}
                </button>
              </div>

              <ModelSelector
                id="main_llm"
                label="Main Agent Model"
                value={fields.main_llm}
                onChange={v => set('main_llm', v)}
                options={modelOptions}
                loading={modelsLoading}
                helpText="Used for all regular agent tasks."
              />

              <ModelSelector
                id="smart_model"
                label="Smart (Subagent) Model"
                value={fields.smart_model}
                onChange={v => set('smart_model', v)}
                options={modelOptions}
                loading={modelsLoading}
                helpText="Used for complex reasoning and spawned subagents."
              />
            </div>

            <Field
              id="grok_api_key"
              label="Grok (xAI) API Key"
              readOnly
              helpText="Primary fallback provider — xai-… keys from https://console.x.ai"
            />
            <Field
              id="nvidia_api_key"
              label="NVIDIA NIM API Key"
              readOnly
              helpText="Secondary fallback provider — nvapi-… keys"
            />
            <Field
              id="openrouter_api_key"
              label="OpenRouter API Key"
              readOnly
              helpText="Tertiary fallback provider — sk-or-… keys"
            />
          </section>

          {/* Search */}
          <section className="settings-section">
            <h3>🔍 Search</h3>
            <Field
              id="tavily_api_key"
              label="Tavily API Key"
              readOnly
            />
            <Field
              id="brave_api_key"
              label="Brave Search API Key"
              readOnly
            />
          </section>

          {/* Maps */}
          <section className="settings-section">
            <h3>🗺️ Maps</h3>
            <Field
              id="maps_api_key"
              label="Google Maps API Key"
              readOnly
            />
          </section>

          {/* Telegram */}
          <section className="settings-section">
            <h3>✈️ Telegram</h3>
            <Field
              id="telegram_token"
              label="Bot Token"
              readOnly
              helpText={
                fields.telegram_token
                  ? `Bot is ${fields.telegram_token ? 'enabled' : 'disabled'}. Token set via config/deploy.`
                  : 'No token configured. Run make setup or set TELEGRAM_BOT_TOKEN in deploy secrets.'
              }
            />
          </section>

          {/* Google */}
          <section className="settings-section">
            <h3>
              <svg width="18" height="18" viewBox="0 0 24 24" style={{ verticalAlign: 'middle', marginRight: 6 }}>
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              Google Services
            </h3>

            {/* Status + action row */}
            <div className="google-auth-row">
              <GoogleBadge />
              {googleStatus?.email && (
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                  {googleStatus.email}
                </span>
              )}
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                {googleConnected ? (
                  <button className="btn-danger-sm" onClick={disconnectGoogle}>
                    Disconnect
                  </button>
                ) : (
                  <button
                    className="btn-google"
                    onClick={connectGoogle}
                    title="Sign in with Google"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" style={{ marginRight: 6 }}>
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84z"/>
                    </svg>
                    Sign in with Google
                  </button>
                )}
              </div>
            </div>

            {/* Scopes info */}
            {googleConnected && (
              <p className="field-help" style={{ marginTop: 8 }}>
                Authorised for Gmail (read/send) and Google Calendar access.
              </p>
            )}

          </section>

          {/* Gmail (App Password) */}
          <section className="settings-section">
            <h3>📧 Gmail (App Password)</h3>
            <Field
              id="gmail_email"
              label="Gmail Address"
              isPassword={false}
              helpText="The Gmail account used to send emails via App Password (SMTP)."
            />
            <Field
              id="gmail_app_password"
              label="Gmail App Password"
              helpText="16-character app password from Google Account → Security → App passwords."
            />
          </section>

          {/* Capsolver */}
          <section className="settings-section">
            <h3>🧩 Capsolver</h3>
            <Field
              id="capsolver_api_key"
              label="Capsolver API Key"
              helpText="Used by the stealth-browser skill to solve CAPTCHAs automatically."
            />
          </section>

          {/* GitHub */}
          <section className="settings-section">
            <h3>🐙 GitHub</h3>
            <Field
              id="github_token"
              label="Personal Access Token"
              helpText='Required for "Submit PR" — create a token at github.com/settings/tokens with repo scope.'
            />
            <Field
              id="github_repo"
              label="Repository"
              isPassword={false}
              helpText='Your fork, e.g. your-username/nanobot-powerup — PRs are raised against main.'
            />
          </section>

          {/* WhatsApp */}
          <WhatsAppSection api={API} Field={Field} />

          {/* Workspace Files */}
          <WorkspaceSection api={API} />

          {/* Skills */}
          <SkillsSection api={API} />

          {/* Status message */}
          {status && (
            <div className={`settings-status ${status.type}`} data-testid="settings-status">
              {status.msg}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
