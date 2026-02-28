import React, { useState, useEffect, useCallback } from 'react';
import './Settings.css';

const API = process.env.REACT_APP_API_URL || '';

export default function Settings({ onClose }) {
  const [saving, setSaving]       = useState(false);
  const [status, setStatus]       = useState(null);    // { type: 'success'|'error', msg }
  const [visible, setVisible]     = useState({});
  const [googleStatus, setGoogleStatus] = useState(undefined); // undefined = loading, null = failed/disconnected

  const [fields, setFields] = useState({
    openrouter_api_key:       '',
    nvidia_api_key:           '',
    brave_api_key:            '',
    tavily_api_key:           '',
    maps_api_key:             '',
    main_llm:                 '',
    whatsapp_allowed_numbers: '',
    telegram_token:           '',
  });

  const loadConfig = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/config`);
      if (!r.ok) throw new Error(await r.text());
      const cfg = await r.json();

      setFields({
        openrouter_api_key:       cfg.providers?.openrouter?.apiKey       || '',
        nvidia_api_key:           cfg.providers?.nvidia?.apiKey           || '',
        brave_api_key:            cfg.tools?.web?.search?.apiKey          || '',
        tavily_api_key:           cfg.tools?.web?.search?.tavilyApiKey    || '',
        maps_api_key:             cfg.tools?.google?.mapsApiKey           || '',
        main_llm:                 cfg.agents?.defaults?.model             || '',
        whatsapp_allowed_numbers: (cfg.channels?.whatsapp?.allowFrom || []).join(', '),
        telegram_token:           cfg.channels?.telegram?.token           || '',
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
  }, [loadConfig, loadGoogleStatus]);

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
      // Only whatsapp_allowed_numbers is editable — all API keys are injected at runtime
      const updates = {
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
      setStatus({ type: 'success', msg: '✅ Configuration saved!' });
      await loadGoogleStatus();
      setTimeout(() => setStatus(null), 4000);
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
    <div className="settings-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="settings-panel" role="dialog" aria-label="Settings">

        {/* Header */}
        <div className="settings-header">
          <h2>⚙️ Settings</h2>
          <button className="settings-close" onClick={onClose} title="Close">✕</button>
        </div>

        <div className="settings-body">

          {/* AI Providers */}
          <section className="settings-section">
            <h3>🤖 AI Providers</h3>
            <Field
              id="main_llm"
              label="Main Agent LLM"
              isPassword={false}
              readOnly
            />
            <Field
              id="openrouter_api_key"
              label="OpenRouter API Key"
              readOnly
            />
            <Field
              id="nvidia_api_key"
              label="NVIDIA NIM API Key"
              readOnly
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

          {/* WhatsApp */}
          <section className="settings-section">
            <h3>💬 WhatsApp</h3>
            <Field
              id="whatsapp_allowed_numbers"
              label="Allowed Phone Numbers"
              placeholder="61412345678, 61498765432"
              helpText="Comma-separated, no + prefix"
              isPassword={false}
            />
          </section>

          {/* Status message */}
          {status && (
            <div className={`settings-status ${status.type}`} data-testid="settings-status">
              {status.msg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="settings-footer">
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
    </div>
  );
}
