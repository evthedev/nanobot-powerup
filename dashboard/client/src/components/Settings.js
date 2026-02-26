import React, { useState, useEffect, useCallback } from 'react';
import './Settings.css';

const API = process.env.REACT_APP_API_URL || '';

export default function Settings({ onClose }) {
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null); // { type: 'success'|'error', msg }
  const [visible, setVisible] = useState({});
  const [googleStatus, setGoogleStatus] = useState(null); // { connected, expired, scope }

  // Form state
  const [fields, setFields] = useState({
    openrouter_api_key: '',
    anthropic_api_key: '',
    openai_api_key: '',
    brave_api_key: '',
    google_client_id: '',
    google_client_secret: '',
    whatsapp_allowed_numbers: '',
  });

  const loadGoogleStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/google/auth/status`);
      if (r.ok) setGoogleStatus(await r.json());
    } catch {}
  }, []);

  useEffect(() => {
    loadConfig();
    loadGoogleStatus();
  }, [loadGoogleStatus]);

  async function loadConfig() {
    try {
      const r = await fetch(`${API}/api/config`);
      if (!r.ok) throw new Error(await r.text());
      const cfg = await r.json();
      setConfig(cfg);

      setFields({
        openrouter_api_key: cfg.providers?.openrouter?.apiKey || '',
        anthropic_api_key: cfg.providers?.anthropic?.apiKey || '',
        openai_api_key: cfg.providers?.openai?.apiKey || '',
        brave_api_key: cfg.tools?.web?.search?.apiKey || '',
        google_client_id: cfg.tools?.google_calendar?.clientId || '',
        google_client_secret: cfg.tools?.google_calendar?.clientSecret || '',
        whatsapp_allowed_numbers: (cfg.channels?.whatsapp?.allowFrom || []).join(', '),
      });
    } catch (e) {
      setStatus({ type: 'error', msg: 'Failed to load config: ' + e.message });
    }
  }

  async function saveConfig() {
    setSaving(true);
    setStatus(null);
    try {
      const updates = {
        providers: {
          openrouter: { apiKey: fields.openrouter_api_key },
          anthropic:  { apiKey: fields.anthropic_api_key },
          openai:     { apiKey: fields.openai_api_key },
        },
        tools: {
          web: { search: { apiKey: fields.brave_api_key } },
          google_calendar: {
            clientId:     fields.google_client_id,
            clientSecret: fields.google_client_secret,
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
      setStatus({ type: 'success', msg: '✅ Configuration saved successfully!' });
      setTimeout(() => setStatus(null), 4000);
    } catch (e) {
      setStatus({ type: 'error', msg: '❌ Failed to save: ' + e.message });
    } finally {
      setSaving(false);
    }
  }

  function toggle(key) {
    setVisible(v => ({ ...v, [key]: !v[key] }));
  }

  function set(key, value) {
    setFields(f => ({ ...f, [key]: value }));
  }

  function connectGoogle() {
    // Save Client ID/Secret first so the server can use them for the handshake
    saveConfig().then(() => {
      const popup = window.open(`${API}/api/google/auth/start`, 'google_auth',
        'width=500,height=650,left=200,top=100');
      if (!popup) {
        setStatus({ type: 'error', msg: 'Popup blocked — allow popups for this site and try again.' });
        return;
      }
      const onMsg = (e) => {
        if (e.data?.type !== 'google_auth') return;
        window.removeEventListener('message', onMsg);
        if (e.data.success) {
          setStatus({ type: 'success', msg: '✅ Google connected!' });
          loadGoogleStatus();
          setTimeout(() => setStatus(null), 4000);
        } else {
          setStatus({ type: 'error', msg: `❌ Google auth failed: ${e.data.error}` });
        }
      };
      window.addEventListener('message', onMsg);
    });
  }

  async function disconnectGoogle() {
    try {
      await fetch(`${API}/api/google/auth/revoke`, { method: 'DELETE' });
      setGoogleStatus({ connected: false });
      setStatus({ type: 'success', msg: 'Google disconnected.' });
      setTimeout(() => setStatus(null), 3000);
    } catch (e) {
      setStatus({ type: 'error', msg: '❌ Failed to disconnect: ' + e.message });
    }
  }

  function Field({ id, label, placeholder, helpText, isPassword = true }) {
    return (
      <div className="settings-field">
        <label htmlFor={id}>{label}</label>
        <div className="field-input-wrap">
          <input
            id={id}
            type={isPassword && !visible[id] ? 'password' : 'text'}
            value={fields[id]}
            onChange={e => set(id, e.target.value)}
            placeholder={placeholder}
            autoComplete="off"
            data-testid={id}
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
              id="openrouter_api_key"
              label="OpenRouter API Key (active)"
              placeholder="sk-or-v1-…"
              helpText="Primary key used for chat. Get one at openrouter.ai"
            />
            <Field
              id="anthropic_api_key"
              label="Anthropic API Key"
              placeholder="sk-ant-…"
            />
            <Field
              id="openai_api_key"
              label="OpenAI API Key"
              placeholder="sk-…"
            />
          </section>

          {/* Search */}
          <section className="settings-section">
            <h3>🦁 Brave Search</h3>
            <Field
              id="brave_api_key"
              label="Brave Search API Key"
              placeholder="BSA…"
              helpText="Get from brave.com/search/api"
            />
          </section>

          {/* Google */}
          <section className="settings-section">
            <h3>🔐 Google OAuth</h3>
            <p className="field-help" style={{ marginBottom: '12px' }}>
              Grants nanobot access to Google Calendar and Gmail on your behalf.
              Create credentials at <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">Google Cloud Console</a> and
              add <code>{window.location.origin}/api/google/auth/callback</code> as an authorised redirect URI.
            </p>
            <Field
              id="google_client_id"
              label="Client ID"
              placeholder="…apps.googleusercontent.com"
            />
            <Field
              id="google_client_secret"
              label="Client Secret"
              placeholder="GOCSPX-…"
            />
            <div className="google-auth-row">
              <span className={`google-status-badge ${googleStatus?.connected ? (googleStatus.expired ? 'expired' : 'connected') : 'disconnected'}`}>
                {googleStatus?.connected
                  ? (googleStatus.expired ? '⚠️ Token expired' : '✅ Connected')
                  : '○ Not connected'}
              </span>
              {googleStatus?.connected ? (
                <button className="btn-danger-sm" onClick={disconnectGoogle}>
                  Disconnect
                </button>
              ) : (
                <button
                  className="btn-google"
                  onClick={connectGoogle}
                  disabled={!fields.google_client_id || !fields.google_client_secret}
                  title={!fields.google_client_id || !fields.google_client_secret ? 'Enter Client ID and Secret first' : ''}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" style={{ marginRight: 6, verticalAlign: 'middle' }}>
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                  Connect Google
                </button>
              )}
            </div>
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

          {/* Status */}
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
