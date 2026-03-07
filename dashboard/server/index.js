const express = require('express');
const cors = require('cors');
const Database = require('better-sqlite3');
const { v4: uuidv4 } = require('uuid');
const fetch = require('node-fetch');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const WebSocket = require('ws');

const app = express();
const PORT = process.env.PORT || 3001;

// ─── Config ────────────────────────────────────────────────────────────────
const NANOBOT_HOME = process.env.NANOBOT_HOME || path.join(process.env.HOME, '.nanobot');
const CONFIG_PATH = path.join(NANOBOT_HOME, 'config.json');
let nanobotConfig = {};
try {
  nanobotConfig = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
} catch (e) {
  console.warn('Could not load nanobot config:', e.message);
}

// ─── Server logger — writes to gateway.log in Loguru format so errors surface
//     in the /logs dashboard page alongside gateway events.
const LOG_PATH = path.join(NANOBOT_HOME, 'logs', 'gateway.log');
function serverLog(level, module, msg) {
  const now = new Date();
  const ts = now.toISOString().replace('T', ' ').replace('Z', '').slice(0, 23);
  const padded = level.padEnd(8);
  const line = `${ts} | ${padded} | dashboard.${module}:- - ${msg}\n`;
  try { fs.appendFileSync(LOG_PATH, line); } catch (_) { /* log dir may not exist yet */ }
  if (level === 'ERROR' || level === 'CRITICAL') console.error(`[${module}]`, msg);
  else console.log(`[${module}]`, msg);
}

// Nanobot web channel WebSocket endpoint
const NANOBOT_WS = process.env.NANOBOT_WS || 'ws://127.0.0.1:18791';
const NANOBOT_TIMEOUT_MS = 600_000; // 10 minutes — planner + evaluator + research can be slow

// ─── SQLite Database ────────────────────────────────────────────────────────
const DB_PATH = process.env.DB_PATH || path.join(__dirname, '..', 'chat.db');
const db = new Database(DB_PATH);

// Enable WAL mode for better concurrency
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// Create tables
db.exec(`
  CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New Conversation',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    message_count INTEGER DEFAULT 0,
    model TEXT DEFAULT 'anthropic/claude-sonnet-4-5'
  );

  CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    tokens_used INTEGER DEFAULT 0,
    model TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS system_stats (
    id INTEGER PRIMARY KEY,
    total_messages INTEGER DEFAULT 0,
    total_conversations INTEGER DEFAULT 0,
    last_active TEXT
  );

  INSERT OR IGNORE INTO system_stats (id, total_messages, total_conversations, last_active)
  VALUES (1, 0, 0, datetime('now'));

  CREATE TABLE IF NOT EXISTS telegram_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    chat_id TEXT NOT NULL,
    sender_id TEXT DEFAULT '',
    sender_name TEXT DEFAULT '',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
`);

// ─── Middleware ─────────────────────────────────────────────────────────────
app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '10mb' }));

// Serve React build — in Docker the build is copied to ./public
const CLIENT_BUILD = process.env.CLIENT_BUILD
  || path.join(__dirname, 'public')                    // Docker
  || path.join(__dirname, '..', 'client', 'build');   // local dev fallback
if (fs.existsSync(CLIENT_BUILD)) {
  app.use(express.static(CLIENT_BUILD));
}

// Serve agent-captured screenshots
const SCREENSHOTS_DIR = path.join(NANOBOT_HOME, 'workspace', 'screenshots');
fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
app.use('/api/screenshots', express.static(SCREENSHOTS_DIR));

// ─── Helpers ────────────────────────────────────────────────────────────────
function generateTitle(content) {
  const words = content.trim().split(/\s+/).slice(0, 6).join(' ');
  return words.length > 50 ? words.slice(0, 50) + '…' : words;
}

function updateStats() {
  const totalMessages = db.prepare("SELECT COUNT(*) as c FROM messages WHERE role != 'system'").get().c;
  const totalConversations = db.prepare('SELECT COUNT(*) as c FROM conversations').get().c;
  db.prepare(`
    UPDATE system_stats SET total_messages = ?, total_conversations = ?, last_active = datetime('now')
    WHERE id = 1
  `).run(totalMessages, totalConversations);
}

// ─── API Routes ─────────────────────────────────────────────────────────────

// Health check
app.get('/api/health', (req, res) => {
  const stats = db.prepare('SELECT * FROM system_stats WHERE id = 1').get();
  res.json({
    status: 'ok',
    model: 'nanobot',
    nanobotWs: NANOBOT_WS,
    db: DB_PATH,
    stats
  });
});

// ── Conversations ──

// List all conversations
app.get('/api/conversations', (req, res) => {
  const conversations = db.prepare(`
    SELECT c.*,
      (SELECT content FROM messages WHERE conversation_id = c.id AND role != 'system'
       ORDER BY created_at DESC LIMIT 1) as last_message
    FROM conversations c
    ORDER BY c.updated_at DESC
  `).all();
  res.json(conversations);
});

// Create conversation
app.post('/api/conversations', (req, res) => {
  const { title } = req.body;
  const id = uuidv4();
  const now = new Date().toISOString();
  db.prepare(`
    INSERT INTO conversations (id, title, created_at, updated_at, model)
    VALUES (?, ?, ?, ?, ?)
  `).run(id, title || 'New Conversation', now, now, 'nanobot');
  updateStats();
  res.json(db.prepare('SELECT * FROM conversations WHERE id = ?').get(id));
});

// Get single conversation
app.get('/api/conversations/:id', (req, res) => {
  const conv = db.prepare('SELECT * FROM conversations WHERE id = ?').get(req.params.id);
  if (!conv) return res.status(404).json({ error: 'Not found' });
  res.json(conv);
});

// Update conversation title
app.patch('/api/conversations/:id', (req, res) => {
  const { title } = req.body;
  db.prepare(`UPDATE conversations SET title = ?, updated_at = datetime('now') WHERE id = ?`)
    .run(title, req.params.id);
  res.json(db.prepare('SELECT * FROM conversations WHERE id = ?').get(req.params.id));
});

// Delete conversation
app.delete('/api/conversations/:id', (req, res) => {
  db.prepare('DELETE FROM conversations WHERE id = ?').run(req.params.id);
  updateStats();
  res.json({ success: true });
});

// ── Messages ──

// Get messages for a conversation
app.get('/api/conversations/:id/messages', (req, res) => {
  const messages = db.prepare(`
    SELECT * FROM messages
    WHERE conversation_id = ? AND role != 'system'
    ORDER BY created_at ASC
  `).all(req.params.id);
  res.json(messages);
});

// Send a message — routes through the nanobot agent loop via WebSocket
app.post('/api/conversations/:id/messages', async (req, res) => {
  const { content, tempId: clientTempId } = req.body;
  const conversationId = req.params.id;

  // Verify conversation exists
  const conv = db.prepare('SELECT * FROM conversations WHERE id = ?').get(conversationId);
  if (!conv) return res.status(404).json({ error: 'Conversation not found' });

  // Save user message
  const userMsgId = uuidv4();
  const now = new Date().toISOString();
  db.prepare(`
    INSERT INTO messages (id, conversation_id, role, content, created_at)
    VALUES (?, ?, 'user', ?, ?)
  `).run(userMsgId, conversationId, content, now);

  // Auto-title conversation if it's the first user message
  const msgCount = db.prepare(
    `SELECT COUNT(*) as c FROM messages WHERE conversation_id = ? AND role = 'user'`
  ).get(conversationId).c;
  if (msgCount === 1) {
    const autoTitle = generateTitle(content);
    db.prepare(`UPDATE conversations SET title = ? WHERE id = ?`).run(autoTitle, conversationId);
  }

  // Set up SSE so the client sees updates as they arrive
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'close');
  res.setHeader('X-Accel-Buffering', 'no');
  // Disable Nagle algorithm so every res.write() is flushed to the OS immediately
  if (res.socket) res.socket.setNoDelay(true);

  // Each nanobot "message" is streamed word-by-word and committed to the DB immediately,
  // so the bubble finalises as soon as the message arrives — not 90s later when WS closes.
  // The WebSocket stays open (held by the outer timeout) so subagent messages can still arrive.
  let currentTempId = clientTempId || `assistant-temp-${Date.now()}`;
  let isFirstMessage = true;

  function saveAndFinish(msgContent, tempId) {
    const msgId = uuidv4();
    const msgNow = new Date().toISOString();
    db.prepare(`
      INSERT INTO messages (id, conversation_id, role, content, created_at, model)
      VALUES (?, ?, 'assistant', ?, ?, ?)
    `).run(msgId, conversationId, msgContent, msgNow, 'nanobot');

    res.write(`data: ${JSON.stringify({
      type: 'done',
      tempId,
      messageId: msgId,
      content: msgContent,
    })}\n\n`);
  }

  try {
    // ── Connect to nanobot WebSocket channel ──────────────────────────────────
    const ws = new WebSocket(NANOBOT_WS);

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        ws.terminate();
        reject(new Error('Nanobot gateway connection timeout — is the gateway running?'));
      }, 5000);

      ws.on('open', () => { clearTimeout(timer); resolve(); });
      ws.on('error', (err) => { clearTimeout(timer); reject(err); });
    });

    // Send the message to nanobot — session_id ties this to the conversation's context
    ws.send(JSON.stringify({ session_id: conversationId, content }));

    // Stream responses back to the client via SSE.
    // Multiple messages may arrive (main agent + subagent). Each gets its own bubble.
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        ws.terminate();
        reject(new Error('Nanobot response timeout — the agent took too long to respond.'));
      }, NANOBOT_TIMEOUT_MS);

      ws.on('message', (raw) => {
        try {
          const msg = JSON.parse(raw.toString());

          if (msg.type === 'message') {
            if (!isFirstMessage) {
              // Subagent message — open a new bubble in React
              currentTempId = `assistant-temp-${Date.now()}`;
              res.write(`data: ${JSON.stringify({ type: 'new_message', tempId: currentTempId })}\n\n`);
            }
            isFirstMessage = false;

            // Stream words as deltas for the typewriter effect
            const thisTempId = currentTempId;
            msg.content.split(' ').forEach((word, i) => {
              res.write(`data: ${JSON.stringify({ type: 'delta', content: i === 0 ? word : ' ' + word })}\n\n`);
            });

            // Commit to DB and send done immediately — no waiting for WS close
            saveAndFinish(msg.content, thisTempId);
          }

          if (msg.type === 'done') {
            clearTimeout(timer);
            ws.close();
            // stream_end sent here (same event-loop tick as the last message write)
            // so the browser's reader.read() receives it immediately, before any DB I/O.
            res.write(`data: ${JSON.stringify({ type: 'stream_end' })}\n\n`);
            resolve();
          }

          if (msg.type === 'error') {
            clearTimeout(timer);
            ws.close();
            reject(new Error(msg.content));
          }
        } catch (e) {
          // ignore malformed frames
        }
      });

      ws.on('error', (err) => { clearTimeout(timer); reject(err); });
      ws.on('close', () => { clearTimeout(timer); resolve(); });
    });

    // Update conversation timestamp and message count
    const count = db.prepare('SELECT COUNT(*) as c FROM messages WHERE conversation_id = ?').get(conversationId).c;
    db.prepare(`UPDATE conversations SET updated_at = datetime('now'), message_count = ? WHERE id = ?`)
      .run(count, conversationId);

    updateStats();

  } catch (err) {
    serverLog('ERROR', 'gateway', `Nanobot Error: ${err.message}`);
    const errorMsg = err.message;

    const errMsgId = uuidv4();
    db.prepare(`
      INSERT INTO messages (id, conversation_id, role, content, created_at)
      VALUES (?, ?, 'assistant', ?, datetime('now'))
    `).run(errMsgId, conversationId, `⚠️ ${errorMsg}`);

    res.write(`data: ${JSON.stringify({ type: 'error', error: errorMsg })}\n\n`);
  }

  res.end();
});

// Delete a message
app.delete('/api/messages/:id', (req, res) => {
  db.prepare('DELETE FROM messages WHERE id = ?').run(req.params.id);
  updateStats();
  res.json({ success: true });
});

// ── Stats ──
app.get('/api/stats', (req, res) => {
  const stats = db.prepare('SELECT * FROM system_stats WHERE id = 1').get();
  const recentConvs = db.prepare(`
    SELECT id, title, updated_at, message_count FROM conversations
    ORDER BY updated_at DESC LIMIT 5
  `).all();
  res.json({ ...stats, recentConversations: recentConvs });
});

// ── Models ──────────────────────────────────────────────────────────────────

const modelsCache = {};               // providerName → { models, ts }
const MODELS_CACHE_TTL_MS = 10 * 60 * 1000;  // 10-minute TTL

// Provider endpoints — all OpenAI-compatible, all return { data: [{ id, ... }] }
const PROVIDER_MODELS_ENDPOINT = {
  openrouter: 'https://openrouter.ai/api/v1/models',
  grok:       'https://api.x.ai/v1/models',
  nvidia:     'https://integrate.api.nvidia.com/v1/models',
};

async function fetchModelsForProvider(providerName, apiKey) {
  const cached = modelsCache[providerName];
  if (cached && (Date.now() - cached.ts) < MODELS_CACHE_TTL_MS) {
    return cached.models;
  }

  const endpoint = PROVIDER_MODELS_ENDPOINT[providerName];
  if (!endpoint) return [];

  let models = [];
  try {
    const resp = await fetch(endpoint, {
      headers: { 'Authorization': `Bearer ${apiKey}` },
    });
    if (!resp.ok) {
      console.warn(`[models] ${providerName} returned HTTP ${resp.status}`);
      return [];
    }
    const data = await resp.json();

    models = (data.data || []).map(m => {
      // NVIDIA NIM model IDs must be prefixed with "nvidia_nim/" for LiteLLM routing
      const id = providerName === 'nvidia' ? `nvidia_nim/${m.id}` : m.id;
      const model = { id, name: m.name || m.id };
      if (m.pricing) {
        const inp = parseFloat(m.pricing.prompt);
        const out = parseFloat(m.pricing.completion);
        if (!isNaN(inp)) model.inputCost  = inp * 1_000_000;   // $/1M tokens
        if (!isNaN(out)) model.outputCost = out * 1_000_000;   // $/1M tokens
      }
      return model;
    }).sort((a, b) => a.id.localeCompare(b.id));
  } catch (e) {
    serverLog('ERROR', 'models', `fetch error for ${providerName}: ${e.message}`);
  }

  if (models.length) modelsCache[providerName] = { models, ts: Date.now() };
  return models;
}

// GET /api/models — returns model list for the highest-priority configured provider
app.get('/api/models', async (req, res) => {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    const providers = cfg.providers || {};

    const priority = [
      { name: 'grok',       key: (providers.grok?.apiKey       || '').trim() },
      { name: 'nvidia',     key: (providers.nvidia?.apiKey     || '').trim() },
      { name: 'openrouter', key: (providers.openrouter?.apiKey || '').trim() },
    ];

    const active = priority.find(p => p.key.length > 0);
    if (!active) {
      return res.json({ provider: null, models: [], message: 'No provider configured' });
    }

    const models = await fetchModelsForProvider(active.name, active.key);
    const defaults = cfg.agents?.defaults || {};

    res.json({
      provider: active.name,
      models,
      currentModel:      defaults.model      || '',
      currentSmartModel: defaults.smartModel || defaults.smart_model || '',
    });
  } catch (e) {
    serverLog('ERROR', 'models', `GET error: ${e.message}`);
    res.status(500).json({ error: e.message });
  }
});

// POST /api/models/refresh — bust cache and re-fetch
app.post('/api/models/refresh', async (req, res) => {
  Object.keys(modelsCache).forEach(k => delete modelsCache[k]);
  res.json({ ok: true });
});

// ── Gateway Restart ──────────────────────────────────────────────────────────

// POST /api/gateway/restart — restart the nanobot-gateway container.
// Primary: `docker restart nanobot-gateway` (works when docker socket is mounted).
// Fallback: SIGTERM to the PID in gateway.pid (local non-Docker dev).
app.post('/api/gateway/restart', (req, res) => {
  const { exec } = require('child_process');

  exec('docker restart nanobot-gateway', { timeout: 20000 }, (dockerErr) => {
    if (!dockerErr) {
      serverLog('INFO', 'restart', 'docker restart nanobot-gateway succeeded');
      return res.json({ success: true, method: 'docker' });
    }

    console.warn('[restart] docker restart failed:', dockerErr.message, '— trying PID file');

    const pidFile = path.join(NANOBOT_HOME, 'gateway.pid');
    try {
      const raw = fs.readFileSync(pidFile, 'utf8').trim();
      const pid = parseInt(raw, 10);
      if (pid && !isNaN(pid)) {
        process.kill(pid, 'SIGTERM');
        serverLog('INFO', 'restart', `sent SIGTERM to PID ${pid}`);
        return res.json({ success: true, method: 'sigterm', pid });
      }
    } catch (pidErr) {
      console.warn('[restart] PID file fallback failed:', pidErr.message);
    }

    res.status(500).json({ error: `Could not restart gateway: ${dockerErr.message}` });
  });
});

// ── Config ──

// GET full config (for the settings UI)
app.get('/api/config', (req, res) => {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
    const cfg = JSON.parse(raw);
    res.json(cfg);
  } catch (e) {
    res.status(500).json({ error: 'Could not read config: ' + e.message });
  }
});

// POST (save) full config — deep-merges the incoming updates
app.post('/api/config', (req, res) => {
  try {
    let current = {};
    try { current = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}

    const updates = req.body;

    // Deep merge helper
    function deepMerge(target, source) {
      const result = { ...target };
      for (const key of Object.keys(source)) {
        if (
          source[key] !== null &&
          typeof source[key] === 'object' &&
          !Array.isArray(source[key]) &&
          target[key] !== null &&
          typeof target[key] === 'object' &&
          !Array.isArray(target[key])
        ) {
          result[key] = deepMerge(target[key] || {}, source[key]);
        } else {
          result[key] = source[key];
        }
      }
      return result;
    }

    const merged = deepMerge(current, updates);
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(merged, null, 2), 'utf8');

    // Reload nanobotConfig in memory so getApiKey() picks up the new value immediately
    nanobotConfig = merged;

    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: 'Could not save config: ' + e.message });
  }
});

// GET runtime status (used by health indicator)
app.get('/api/status', (req, res) => {
  res.json({
    model: 'nanobot',
    nanobotWs: NANOBOT_WS,
    dbPath: DB_PATH
  });
});

// ── Log streaming ────────────────────────────────────────────────────────────
const LOG_FILE = path.join(NANOBOT_HOME, 'logs', 'gateway.log');

// Loguru format: "2026-02-24 19:36:07.123 | INFO     | nanobot.agent.loop:fn:42 - message"
function parseLogLine(raw) {
  const line = raw.trim();
  if (!line) return null;

  const m = line.match(
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| (\w+)\s+\| ([\w.]+):[^|]+ - (.+)$/
  );
  if (!m) return { ts: new Date().toISOString(), level: 'RAW', type: 'system', module: '', msg: line, raw: line };

  const [, ts, level, module, msg] = m;

  // Determine source type
  let type = 'system';
  if (module.includes('agent.loop'))          type = 'main';
  else if (module.includes('agent.subagent')) type = 'subagent';
  else if (module.includes('tools.plan_task')) type = 'subagent';
  else if (module.includes('channels'))       type = 'channel';

  // Extract model from spawn lines: "Spawned subagent [xxx] using some/model: task..."
  const modelMatch = msg.match(/using ([\w/.\-:]+):/);

  // Extract subagent ID: "Subagent [abc123] ..."
  const subagentIdMatch = msg.match(/Subagent \[(\w+)\]/);

  // Extract token usage: "LLM usage | model=X tokens_in=N tokens_out=N total=N"
  const tokenMatch = msg.match(/LLM usage \| model=(\S+) tokens_in=(\d+) tokens_out=(\d+) total=(\d+)/);

  // Classify message category for richer UI display
  let category = 'log';
  if (tokenMatch)                           category = 'tokens';
  else if (msg.startsWith('>>> INBOUND'))   category = 'inbound';
  else if (msg.startsWith('<<< OUTBOUND')) category = 'outbound';
  else if (msg.includes('Tool call:'))      category = 'tool';
  else if (msg.includes('Spawned subagent')) category = 'spawn';
  else if (msg.includes('executing:'))      category = 'tool';
  else if (msg.includes('completed successfully')) category = 'done';
  else if (msg.includes('messaged user directly')) category = 'done';
  else if (level === 'ERROR' || level === 'CRITICAL') category = 'error';
  else if (level === 'WARNING')             category = 'warning';

  return {
    ts,
    level,
    type,
    module,
    msg,
    category,
    model:      tokenMatch?.[1] || modelMatch?.[1] || null,
    subagentId: subagentIdMatch?.[1] || null,
    tokens: tokenMatch ? {
      in:    parseInt(tokenMatch[2], 10),
      out:   parseInt(tokenMatch[3], 10),
      total: parseInt(tokenMatch[4], 10),
    } : null,
    raw: line,
  };
}

// Convert a telegram_messages row into the shared log-entry schema
function telegramToLogEntry(row) {
  const snippet = row.content.length > 300 ? row.content.slice(0, 300) + '…' : row.content;
  return {
    ts:         (row.created_at || '').replace(' ', 'T') + '.000',
    level:      'INFO',
    type:       'telegram',
    module:     'channels.telegram',
    msg:        snippet,
    category:   row.direction === 'inbound' ? 'tg-inbound' : 'tg-outbound',
    direction:  row.direction,
    sender:     row.sender_name || '',
    chat_id:    row.chat_id || '',
    tokens:     null,
    model:      null,
    subagentId: null,
    raw:        row.content,
  };
}

// SSE endpoint — streams live log lines + Telegram messages to the dashboard
app.get('/api/logs/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  // Send a heartbeat comment every 15s to keep connection alive
  const heartbeat = setInterval(() => res.write(': ping\n\n'), 15000);

  // ── Gateway log tail ────────────────────────────────────────────────────
  const args = fs.existsSync(LOG_FILE)
    ? ['-n', '200', '-F', LOG_FILE]   // -F retries if file is rotated
    : ['-n', '0', '-F', LOG_FILE];    // file doesn't exist yet, just follow

  const tail = spawn('tail', args);

  tail.stdout.on('data', (chunk) => {
    const lines = chunk.toString().split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      // Skip pure MCP debug noise
      if (line.includes('mcp_playwright') && line.includes('registered tool')) continue;
      const parsed = parseLogLine(line);
      if (parsed) {
        res.write(`data: ${JSON.stringify(parsed)}\n\n`);
      }
    }
  });

  tail.stderr.on('data', () => {}); // ignore tail warnings

  // ── Telegram messages — seed last 50 then poll for new ones ────────────
  let lastTelegramId = 0;
  try {
    const recent = db.prepare(
      'SELECT * FROM telegram_messages ORDER BY id DESC LIMIT 50'
    ).all().reverse();
    for (const row of recent) {
      res.write(`data: ${JSON.stringify(telegramToLogEntry(row))}\n\n`);
      lastTelegramId = row.id;
    }
  } catch {}

  const tgPoll = setInterval(() => {
    try {
      const rows = db.prepare(
        'SELECT * FROM telegram_messages WHERE id > ? ORDER BY id ASC LIMIT 50'
      ).all(lastTelegramId);
      for (const row of rows) {
        res.write(`data: ${JSON.stringify(telegramToLogEntry(row))}\n\n`);
        lastTelegramId = row.id;
      }
    } catch {}
  }, 1000);

  req.on('close', () => {
    clearInterval(heartbeat);
    clearInterval(tgPoll);
    tail.kill();
  });
});

// ── Google OAuth (for nanobot service integrations: Calendar, Gmail) ─────────
// Scopes the nanobot agent needs to manage Google services on your behalf.
const GOOGLE_SCOPES = [
  'https://www.googleapis.com/auth/calendar',
  'https://www.googleapis.com/auth/gmail.send',
  'https://www.googleapis.com/auth/gmail.readonly',
].join(' ');

function getGoogleCreds() {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    // Credentials stored under tools.google_calendar (matching Pydantic schema)
    const creds        = cfg.tools?.google_calendar || {};
    const clientId     = creds.clientId;
    const clientSecret = creds.clientSecret;
    return { clientId, clientSecret };
  } catch {
    return {};
  }
}

function readGoogleTokens() {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    return cfg.tools?.google_calendar?.tokens || null;
  } catch {
    return null;
  }
}

function writeGoogleTokens(tokenData) {
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}
  if (!cfg.tools) cfg.tools = {};
  if (!cfg.tools.google_calendar) cfg.tools.google_calendar = {};
  cfg.tools.google_calendar.tokens = tokenData;
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8');
}

function buildRedirectUri(req) {
  // Google Cloud registered redirect URI: http://localhost:3001/api/google/callback
  // Always use the Host header; localhost is always http.
  const host = req.headers['x-forwarded-host'] || req.headers.host || '';
  const proto = host.startsWith('localhost') || host.startsWith('127.') ? 'http' : 'https';
  return `${proto}://${host}/api/google/callback`;
}

// Simple in-memory state store (CSRF protection, 10-min TTL)
const _oauthStates = new Map();
function createState() {
  const state = Math.random().toString(36).slice(2) + Date.now().toString(36);
  _oauthStates.set(state, Date.now());
  setTimeout(() => _oauthStates.delete(state), 10 * 60 * 1000);
  return state;
}
function consumeState(state) {
  if (!_oauthStates.has(state)) return false;
  _oauthStates.delete(state);
  return true;
}

// GET /api/google/auth — redirect the browser to Google's consent screen
app.get('/api/google/auth', (req, res) => {
  const { clientId } = getGoogleCreds();
  if (!clientId) {
    return res.status(400).json({ error: 'Google Client ID not configured. Add it in Settings first.' });
  }
  const state = createState();
  const params = new URLSearchParams({
    client_id:     clientId,
    redirect_uri:  buildRedirectUri(req),
    response_type: 'code',
    scope:         GOOGLE_SCOPES,
    access_type:   'offline',   // get a refresh token
    prompt:        'consent',   // always show consent screen so we always get refresh_token
    state,
  });
  res.redirect(`https://accounts.google.com/o/oauth2/v2/auth?${params}`);
});

// GET /api/google/callback — Google redirects here with ?code=...
// Registered in Google Cloud Console as: http://localhost:3001/api/google/callback
app.get('/api/google/callback', async (req, res) => {
  const { code, state, error } = req.query;

  if (error) {
    return res.send(`<script>
      window.opener?.postMessage({ type: 'google_auth_error', message: '${error}' }, '*');
      window.close();
    </script><p>Google auth failed: ${error}. You can close this tab.</p>`);
  }

  if (!consumeState(state)) {
    return res.status(400).send('<p>Invalid or expired OAuth state. Please try again.</p>');
  }

  const { clientId, clientSecret } = getGoogleCreds();
  if (!clientId || !clientSecret) {
    return res.status(400).send('<p>Google credentials not configured. Add Client ID and Secret in Settings.</p>');
  }

  try {
    const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        code,
        client_id:     clientId,
        client_secret: clientSecret,
        redirect_uri:  buildRedirectUri(req),
        grant_type:    'authorization_code',
      }),
    });

    const tokens = await tokenRes.json();
    if (tokens.error) throw new Error(tokens.error_description || tokens.error);

    // Read existing tokens (to preserve refresh_token if not returned)
    const existing = readGoogleTokens() || {};

    // Persist tokens to config.json under tools.google_calendar.tokens
    const tokenData = {
      access_token:  tokens.access_token,
      refresh_token: tokens.refresh_token || existing.refresh_token,
      token_uri:     'https://oauth2.googleapis.com/token',
      client_id:     clientId,
      client_secret: clientSecret,
      scope:         tokens.scope,
      expiry_date:   Date.now() + (tokens.expires_in || 3600) * 1000,
    };
    writeGoogleTokens(tokenData);

    // Close the popup and notify the opener (Settings panel)
    res.send(`<!DOCTYPE html><html><body>
      <p>✅ Google connected! You can close this tab.</p>
      <script>
        if (window.opener) {
          window.opener.postMessage({ type: 'google_auth_success', message: 'Google account connected successfully!' }, '*');
          setTimeout(() => window.close(), 1500);
        }
      </script>
    </body></html>`);
  } catch (err) {
    serverLog('ERROR', 'oauth', `Google OAuth error: ${err.message}`);
    res.send(`<script>
      window.opener?.postMessage({ type: 'google_auth_error', message: '${err.message.replace(/'/g, "\\'")}' }, '*');
      window.close();
    </script><p>OAuth failed: ${err.message}. <a href="javascript:window.close()">Close</a></p>`);
  }
});

// GET /api/google/status — returns whether tokens are stored and non-expired
app.get('/api/google/status', (req, res) => {
  try {
    const { clientId } = getGoogleCreds();
    const tokens = readGoogleTokens();
    if (!tokens?.access_token) return res.json({ connected: false, hasCredentials: !!clientId });
    const expired = tokens.expiry_date && Date.now() > tokens.expiry_date;
    res.json({
      connected: true,
      expired,
      hasCredentials: !!clientId,
      scope: tokens.scope,
      expiry_date: tokens.expiry_date,
    });
  } catch {
    res.json({ connected: false });
  }
});

// POST /api/google/disconnect — remove stored tokens from config.json
app.post('/api/google/disconnect', (req, res) => {
  try {
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}
    if (cfg.tools?.google_calendar?.tokens) {
      delete cfg.tools.google_calendar.tokens;
      fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8');
    }
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Telegram ─────────────────────────────────────────────────────────────────

// GET /api/telegram/messages — recent message history
app.get('/api/telegram/messages', (req, res) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '200', 10), 500);
    const msgs = db.prepare(
      'SELECT * FROM telegram_messages ORDER BY id DESC LIMIT ?'
    ).all(limit).reverse();
    res.json(msgs);
  } catch (e) {
    res.json([]);
  }
});

// GET /api/telegram/status — whether Telegram is configured
app.get('/api/telegram/status', (req, res) => {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    const tg = cfg?.channels?.telegram || {};
    res.json({
      enabled: !!tg.enabled,
      hasToken: !!(tg.token || '').trim(),
    });
  } catch {
    res.json({ enabled: false, hasToken: false });
  }
});

// GET /api/telegram/stream — SSE stream of new messages (1-second polling)
// Uses SSE `id:` field so the browser sends Last-Event-ID on auto-reconnect,
// allowing the server to resume from the correct position without missing messages.
app.get('/api/telegram/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  if (res.socket) res.socket.setNoDelay(true);

  const heartbeat = setInterval(() => res.write(': ping\n\n'), 15000);

  // Determine starting lastId:
  // 1. Last-Event-ID header (browser sends this on auto-reconnect after error)
  // 2. ?lastId= query param (explicit client-side position)
  // 3. 0 → fall back to MAX(id) so we only push NEW messages
  const headerLastId = parseInt(req.headers['last-event-id'] || '0', 10);
  const queryLastId  = parseInt(req.query.lastId || '0', 10);
  let lastId = headerLastId || queryLastId;

  if (!lastId) {
    try {
      const row = db.prepare('SELECT MAX(id) as maxId FROM telegram_messages').get();
      lastId = row?.maxId || 0;
    } catch {}
  }

  const poll = setInterval(() => {
    try {
      const msgs = db.prepare(
        'SELECT * FROM telegram_messages WHERE id > ? ORDER BY id ASC LIMIT 50'
      ).all(lastId);
      for (const msg of msgs) {
        // Include `id:` field so browser tracks position for reconnect
        res.write(`id: ${msg.id}\ndata: ${JSON.stringify(msg)}\n\n`);
        lastId = msg.id;
      }
    } catch {}
  }, 1000);

  req.on('close', () => {
    clearInterval(heartbeat);
    clearInterval(poll);
  });
});

// ── WhatsApp (pairing QR from bridge) ────────────────────────────────────────
const WHATSAPP_QR_FILE = path.join(NANOBOT_HOME, 'whatsapp-pending-qr.json');
const WHATSAPP_STATUS_FILE = path.join(NANOBOT_HOME, 'whatsapp-status.json');

// GET /api/whatsapp/status — whether WhatsApp is enabled and pairing/connected
app.get('/api/whatsapp/status', (req, res) => {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    const wa = cfg?.channels?.whatsapp || {};
    const enabled = !!wa.enabled;
    let pairing = false;
    let connected = false;
    try {
      if (fs.existsSync(WHATSAPP_QR_FILE)) {
        const data = JSON.parse(fs.readFileSync(WHATSAPP_QR_FILE, 'utf8'));
        pairing = !!(data.qr && data.qr.length > 0);
      }
      if (fs.existsSync(WHATSAPP_STATUS_FILE)) {
        const data = JSON.parse(fs.readFileSync(WHATSAPP_STATUS_FILE, 'utf8'));
        connected = data.status === 'connected';
      }
    } catch {}
    res.json({ enabled, pairing, connected });
  } catch {
    res.json({ enabled: false, pairing: false, connected: false });
  }
});

// GET /api/whatsapp/qr — returns current QR string if pairing, else null
app.get('/api/whatsapp/qr', (req, res) => {
  try {
    if (!fs.existsSync(WHATSAPP_QR_FILE)) {
      return res.json({ status: 'connected', qr: null });
    }
    const data = JSON.parse(fs.readFileSync(WHATSAPP_QR_FILE, 'utf8'));
    if (!data.qr) return res.json({ status: 'connected', qr: null });
    res.json({ status: 'pending', qr: data.qr, timestamp: data.timestamp });
  } catch {
    res.json({ status: 'unknown', qr: null });
  }
});

// ── Workspace Docs ───────────────────────────────────────────────────────────
const WORKSPACE_DOCS = ['SOUL.md', 'AGENTS.md', 'USER.md', 'TOOLS.md', 'HEARTBEAT.md'];

app.get('/api/workspace/docs', (req, res) => {
  const files = WORKSPACE_DOCS.map(name => {
    const filePath = path.join(WORKSPACE_DIR, name);
    let content = null;
    let exists  = false;
    try {
      content = fs.readFileSync(filePath, 'utf8');
      exists  = true;
    } catch {}
    return { name, path: filePath, exists, content };
  });
  res.json(files);
});

// ── Skills ───────────────────────────────────────────────────────────────────
const WORKSPACE_DIR = path.join(NANOBOT_HOME, 'workspace');
const SKILL_IGNORED     = new Set(['.gitkeep', '.DS_Store', '.git']);
const SKILL_META_FILES  = new Set(['skill.json']); // metadata — shown in toggle, not in file tabs

function readSkillsDir(dirPath) {
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    return entries
      .filter(e => e.isDirectory() && !SKILL_IGNORED.has(e.name))
      .map(dir => {
        const skillPath = path.join(dirPath, dir.name);
        const files = fs.readdirSync(skillPath, { withFileTypes: true })
          .filter(e => e.isFile() && !SKILL_IGNORED.has(e.name) && !SKILL_META_FILES.has(e.name) && !e.name.startsWith('.'))
          .map(e => e.name)
          .sort();

        // Read enabled state from skill.json (default: true if missing)
        let enabled = true;
        try {
          const meta = JSON.parse(fs.readFileSync(path.join(skillPath, 'skill.json'), 'utf8'));
          if (typeof meta.enabled === 'boolean') enabled = meta.enabled;
        } catch { /* no skill.json or parse error — treat as enabled */ }

        return { name: dir.name, files, enabled };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    return [];
  }
}

app.get('/api/skills', (req, res) => {
  res.json({
    workspace: readSkillsDir(path.join(WORKSPACE_DIR, 'skills')),
    auto:      readSkillsDir(path.join(WORKSPACE_DIR, 'skills-auto')),
  });
});

app.get('/api/skills/content', (req, res) => {
  const { source, skill, file } = req.query;

  if (!['skills', 'skills-auto'].includes(source)) {
    return res.status(400).json({ error: 'Invalid source' });
  }
  if (!skill || /[./\\]/.test(skill) || !file || /[/\\]/.test(file)) {
    return res.status(400).json({ error: 'Invalid path component' });
  }

  const filePath = path.resolve(WORKSPACE_DIR, source, skill, file);
  const allowed  = path.resolve(WORKSPACE_DIR, source);

  if (!filePath.startsWith(allowed + path.sep)) {
    return res.status(400).json({ error: 'Path traversal not allowed' });
  }

  try {
    const content = fs.readFileSync(filePath, 'utf8');
    res.json({ content });
  } catch {
    res.status(404).json({ error: 'File not found' });
  }
});

// ── Skills Toggle — write skill.json enabled flag ────────────────────────────
app.post('/api/skills/toggle', (req, res) => {
  const { source, skillName, enabled } = req.body;

  if (!['skills', 'skills-auto'].includes(source)) {
    return res.status(400).json({ error: 'Invalid source' });
  }
  if (!skillName || /[./\\]/.test(skillName)) {
    return res.status(400).json({ error: 'Invalid skill name' });
  }
  if (typeof enabled !== 'boolean') {
    return res.status(400).json({ error: 'enabled must be a boolean' });
  }

  const skillPath = path.resolve(WORKSPACE_DIR, source, skillName);
  const allowed   = path.resolve(WORKSPACE_DIR, source);

  if (!skillPath.startsWith(allowed + path.sep)) {
    return res.status(400).json({ error: 'Path traversal not allowed' });
  }
  if (!fs.existsSync(skillPath)) {
    return res.status(404).json({ error: `Skill '${skillName}' not found` });
  }

  try {
    fs.writeFileSync(path.join(skillPath, 'skill.json'), JSON.stringify({ enabled }, null, 2) + '\n');
    res.json({ ok: true, skillName, enabled });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Skills Promote — create a GitHub PR to merge a skills-auto skill into workspace/skills ──
async function githubRequest(token, method, urlPath, body) {
  const res = await fetch(`https://api.github.com${urlPath}`, {
    method,
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      'User-Agent': 'nanobot-powerup',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) {
    let msg = data.message || `GitHub API ${res.status}`;
    if (res.status === 403 && msg.includes('Resource not accessible by personal access token')) {
      msg = 'GitHub token lacks permission to create pull requests. Use a classic Personal Access Token with the "repo" scope (github.com/settings/tokens → Generate new token (classic) → check "repo").';
    }
    throw new Error(msg);
  }
  return data;
}

// ── Skills Delete — remove a skill from skills-auto ──────────────────────────
app.delete('/api/skills', (req, res) => {
  const { skillName } = req.body || {};

  if (!skillName || /[./\\]/.test(skillName)) {
    return res.status(400).json({ error: 'Invalid skill name' });
  }

  const skillPath = path.resolve(WORKSPACE_DIR, 'skills-auto', skillName);
  const allowed   = path.resolve(WORKSPACE_DIR, 'skills-auto');

  if (!skillPath.startsWith(allowed + path.sep)) {
    return res.status(400).json({ error: 'Path traversal not allowed' });
  }

  if (!fs.existsSync(skillPath)) {
    return res.status(404).json({ error: 'Skill not found' });
  }

  try {
    fs.rmSync(skillPath, { recursive: true, force: true });
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/skills/promote', async (req, res) => {
  const { skillName } = req.body || {};

  if (!skillName || /[./\\]/.test(skillName)) {
    return res.status(400).json({ error: 'Invalid skill name' });
  }

  // Reload config from disk so we pick up tokens saved via UI or inject_keys
  try {
    nanobotConfig = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (_) { /* keep in-memory config */ }

  const token = nanobotConfig.tools?.github?.token || process.env.GITHUB_TOKEN;
  const repo  = nanobotConfig.tools?.github?.repo  || process.env.GITHUB_REPO;

  if (!token) {
    serverLog('ERROR', 'skills', `promote '${skillName}': GitHub token not configured`);
    return res.status(500).json({ error: 'GitHub token not configured — set tools.github.token in config.json or GITHUB_TOKEN env var' });
  }
  if (!repo) {
    serverLog('ERROR', 'skills', `promote '${skillName}': GitHub repo not configured`);
    return res.status(500).json({ error: 'GitHub repo not configured — set tools.github.repo ("owner/repo") in config.json or GITHUB_REPO env var' });
  }

  const skillDir = path.resolve(WORKSPACE_DIR, 'skills-auto', skillName);
  if (!skillDir.startsWith(path.resolve(WORKSPACE_DIR, 'skills-auto') + path.sep)) {
    return res.status(400).json({ error: 'Path traversal not allowed' });
  }
  if (!fs.existsSync(skillDir)) {
    return res.status(404).json({ error: `Skill '${skillName}' not found in skills-auto` });
  }

  const skillFiles = fs.readdirSync(skillDir, { withFileTypes: true })
    .filter(e => e.isFile() && !SKILL_IGNORED.has(e.name) && !e.name.startsWith('.'))
    .map(e => ({ name: e.name, content: fs.readFileSync(path.join(skillDir, e.name)) }));

  if (!skillFiles.length) {
    return res.status(400).json({ error: 'No files found in skill directory' });
  }

  try {
    const branchName = `skill-auto/${skillName}`;

    // Resolve base commit + tree
    const baseRef    = await githubRequest(token, 'GET', `/repos/${repo}/git/ref/heads/main`);
    const baseSha    = baseRef.object.sha;
    const baseCommit = await githubRequest(token, 'GET', `/repos/${repo}/git/commits/${baseSha}`);
    const baseTree   = baseCommit.tree.sha;

    // Create blobs and build tree entries (all in parallel)
    const treeEntries = await Promise.all(skillFiles.map(async ({ name, content }) => {
      const blob = await githubRequest(token, 'POST', `/repos/${repo}/git/blobs`, {
        content: content.toString('base64'),
        encoding: 'base64',
      });
      return { path: `workspace/skills/${skillName}/${name}`, mode: '100644', type: 'blob', sha: blob.sha };
    }));

    const newTree   = await githubRequest(token, 'POST', `/repos/${repo}/git/trees`, { base_tree: baseTree, tree: treeEntries });
    const newCommit = await githubRequest(token, 'POST', `/repos/${repo}/git/commits`, {
      message: `feat(skills): promote auto-generated skill '${skillName}'\n\nFiles: ${skillFiles.map(f => f.name).join(', ')}`,
      tree: newTree.sha,
      parents: [baseSha],
    });

    // Create or force-update branch
    let branchExists = false;
    try { await githubRequest(token, 'GET', `/repos/${repo}/git/ref/heads/${branchName}`); branchExists = true; } catch {}

    if (branchExists) {
      await githubRequest(token, 'PATCH', `/repos/${repo}/git/refs/heads/${branchName}`, { sha: newCommit.sha, force: true });
    } else {
      await githubRequest(token, 'POST', `/repos/${repo}/git/refs`, { ref: `refs/heads/${branchName}`, sha: newCommit.sha });
    }

    // Check for an existing open PR, create one if absent
    const owner = repo.split('/')[0];
    const existingPrs = await githubRequest(token, 'GET', `/repos/${repo}/pulls?head=${owner}:${branchName}&state=open`);
    let prUrl, prNumber;

    if (existingPrs.length > 0) {
      prUrl    = existingPrs[0].html_url;
      prNumber = existingPrs[0].number;
    } else {
      const fileList = skillFiles.map(f => `- \`workspace/skills/${skillName}/${f.name}\``).join('\n');
      const pr = await githubRequest(token, 'POST', `/repos/${repo}/pulls`, {
        title: `feat(skills): promote auto-generated skill '${skillName}'`,
        body:  `## Auto-generated skill: \`${skillName}\`\n\nThis PR was raised automatically by nanobot to promote an autonomously created skill from the instance layer to the base layer.\n\n### Files\n${fileList}`,
        head: branchName,
        base: 'main',
      });
      prUrl    = pr.html_url;
      prNumber = pr.number;
    }

    serverLog('INFO', 'skills', `PR #${prNumber} for '${skillName}': ${prUrl}`);
    res.json({ prUrl, prNumber, branch: branchName });
  } catch (e) {
    serverLog('ERROR', 'skills', `promote '${req.body?.skillName}': ${e.message}`);
    res.status(500).json({ error: e.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────

// Catch-all: serve React app (SPA fallback)
app.get('*', (req, res) => {
  const index = path.join(CLIENT_BUILD, 'index.html');
  if (fs.existsSync(index)) {
    res.sendFile(index);
  } else {
    res.status(404).json({ error: 'Client build not found' });
  }
});

// ─── Start ──────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`🤖 Nanobot Chat Server running on http://localhost:${PORT}`);
  console.log(`🔌 Nanobot WebSocket: ${NANOBOT_WS}`);
  console.log(`🗄️  Database: ${DB_PATH}`);
});
