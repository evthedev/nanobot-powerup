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
    console.error('Nanobot Error:', err.message);
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

// SSE endpoint — streams live log lines to the dashboard
app.get('/api/logs/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  // Send a heartbeat comment every 15s to keep connection alive
  const heartbeat = setInterval(() => res.write(': ping\n\n'), 15000);

  // tail -n 200 -f: send last 200 lines then follow new ones
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

  req.on('close', () => {
    clearInterval(heartbeat);
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
    const clientId     = cfg.tools?.google_calendar?.clientId;
    const clientSecret = cfg.tools?.google_calendar?.clientSecret;
    return { clientId, clientSecret };
  } catch {
    return {};
  }
}

function buildRedirectUri(req) {
  // Use http for localhost (Google allows it); always HTTPS behind nginx in prod
  const host = req.headers.host || '';
  const proto = host.startsWith('localhost') || host.startsWith('127.') ? 'http' : 'https';
  return `${proto}://${host}/api/google/auth/callback`;
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

// GET /api/google/auth/start — redirect the browser to Google's consent screen
app.get('/api/google/auth/start', (req, res) => {
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

// GET /api/google/auth/callback — Google redirects here with ?code=...
app.get('/api/google/auth/callback', async (req, res) => {
  const { code, state, error } = req.query;

  if (error) {
    return res.send(`<script>window.opener?.postMessage({type:'google_auth',error:'${error}'},'*');window.close();</script>
      <p>Google auth failed: ${error}. You can close this tab.</p>`);
  }

  if (!consumeState(state)) {
    return res.status(400).send('<p>Invalid or expired OAuth state. Please try again.</p>');
  }

  const { clientId, clientSecret } = getGoogleCreds();
  if (!clientId || !clientSecret) {
    return res.status(400).send('<p>Google credentials not configured.</p>');
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

    // Persist tokens inside config.json under tools.google_calendar.tokens
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}
    cfg.tools = cfg.tools || {};
    cfg.tools.google_calendar = cfg.tools.google_calendar || {};
    cfg.tools.google_calendar.tokens = {
      access_token:  tokens.access_token,
      refresh_token: tokens.refresh_token || cfg.tools.google_calendar.tokens?.refresh_token,
      expiry_date:   Date.now() + (tokens.expires_in || 3600) * 1000,
      scope:         tokens.scope,
    };
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8');

    // Close the popup and notify the opener (Settings panel)
    res.send(`<!DOCTYPE html><html><body>
      <p>✅ Google connected successfully! You can close this tab.</p>
      <script>
        if (window.opener) {
          window.opener.postMessage({ type: 'google_auth', success: true }, '*');
          setTimeout(() => window.close(), 1500);
        }
      </script>
    </body></html>`);
  } catch (err) {
    console.error('Google OAuth error:', err.message);
    res.status(500).send(`<p>OAuth failed: ${err.message}. <a href="javascript:window.close()">Close</a></p>`);
  }
});

// GET /api/google/auth/status — returns whether tokens are stored and non-expired
app.get('/api/google/auth/status', (req, res) => {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    const tokens = cfg.tools?.google_calendar?.tokens;
    if (!tokens?.access_token) return res.json({ connected: false });
    const expired = tokens.expiry_date && Date.now() > tokens.expiry_date;
    res.json({
      connected: true,
      expired,
      scope: tokens.scope,
      expiry_date: tokens.expiry_date,
    });
  } catch {
    res.json({ connected: false });
  }
});

// DELETE /api/google/auth/revoke — remove stored tokens
app.delete('/api/google/auth/revoke', (req, res) => {
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
