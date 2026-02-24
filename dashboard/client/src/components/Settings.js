import React, { useState, useEffect } from 'react';
import './Settings.css';

const API = process.env.REACT_APP_API_URL || '';

export default function Settings({ onClose }) {
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null); // { type: 'success'|'error', msg }
  const [visible, setVisible] = useState({});

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

  useEffect(() => {
    loadConfig();
  }, []);

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
