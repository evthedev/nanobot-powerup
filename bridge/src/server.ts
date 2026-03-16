import { createServer, IncomingMessage, ServerResponse } from 'http';
import { createHmac, timingSafeEqual, randomUUID } from 'crypto';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import WebSocket, { WebSocketServer } from 'ws';
import { DeviceRegistry } from './device_registry.js';
import { DB } from './db.js';
import { forwardToGateway } from './gateway.js';
import { bridgeLog } from './logger.js';

// ── Config ────────────────────────────────────────────────────────────────────

function loadConfig(): { devices: Record<string, { secret: string; pollIntervalSeconds: number }> } {
  try {
    const cfgPath = process.env.NANOBOT_CONFIG || join(homedir(), '.nanobot', 'config.json');
    const raw = JSON.parse(readFileSync(cfgPath, 'utf8'));
    const edgeDevices = raw?.channels?.edgeDevices ?? raw?.channels?.edge_devices ?? {};
    const devices: Record<string, { secret: string; pollIntervalSeconds: number }> = {};
    for (const [id, d] of Object.entries(edgeDevices.devices ?? {})) {
      const dc = d as Record<string, unknown>;
      devices[id] = {
        secret: (dc.secret ?? '') as string,
        pollIntervalSeconds: (dc.pollIntervalSeconds ?? dc.poll_interval_seconds ?? 30) as number,
      };
    }
    return { devices };
  } catch {
    return { devices: {} };
  }
}

// ── Server ────────────────────────────────────────────────────────────────────

export class BridgeServer {
  private server: ReturnType<typeof createServer>;
  private wss: WebSocketServer;
  private registry = new DeviceRegistry();
  private db: DB;
  private edgeToken: string;

  constructor(private port: number) {
    this.db = new DB();
    this.edgeToken = process.env.EDGE_TOKEN || '';

    // Pre-register configured devices
    const { devices } = loadConfig();
    for (const [id, cfg] of Object.entries(devices)) {
      this.registry.getOrCreate(id, cfg);
    }

    this.server = createServer((req, res) => this._route(req, res).catch(e => {
      bridgeLog.error('server', `Route error: ${e}`);
      res.writeHead(500).end(JSON.stringify({ error: String(e) }));
    }));

    this.wss = new WebSocketServer({ noServer: true });
    this.server.on('upgrade', (req, socket, head) => {
      const url = req.url ?? '';
      if (url.startsWith('/edge/ws')) {
        this.wss.handleUpgrade(req, socket, head, (ws) => this._handleEdgeWs(ws, req));
      } else {
        socket.destroy();
      }
    });
  }

  start(): void {
    this.server.listen(this.port, '0.0.0.0', () => {
      bridgeLog.info('server', `Bridge server listening on :${this.port}`);
    });
  }

  stop(): void {
    this.wss.close();
    this.server.close();
    this.db.close();
  }

  // ── Edge device WebSocket handler ─────────────────────────────────────────

  private _handleEdgeWs(ws: WebSocket, req: IncomingMessage): void {
    // Auth
    const authHeader = (req.headers['authorization'] ?? '') as string;
    const bearer = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : '';
    if (this.edgeToken && bearer !== this.edgeToken) {
      ws.send(JSON.stringify({ type: 'error', code: 'auth_failed', message: 'Unauthorized' }));
      ws.close(1008, 'Unauthorized');
      return;
    }

    // Device ID from query string
    const url = new URL(req.url ?? '/edge/ws', 'http://localhost');
    const deviceId = url.searchParams.get('device_id') || 'default';

    this.registry.registerWs(deviceId, ws);
    bridgeLog.info('edge', `[${deviceId}] WS connected`);

    const frame = (type: string, extra: Record<string, unknown> = {}) =>
      JSON.stringify({ type, id: randomUUID(), ts: Date.now(), ...extra });

    ws.send(frame('hello'));

    // Keepalive
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(frame('ping'));
    }, 30_000);

    ws.on('message', async (raw) => {
      let msg: Record<string, unknown>;
      try { msg = JSON.parse(raw.toString()); } catch {
        ws.send(frame('error', { code: 'parse_error', message: 'Invalid JSON' }));
        return;
      }

      const type = msg.type as string;

      if (type === 'pong') return;
      if (type === 'ping') { ws.send(frame('pong', { id: msg.id })); return; }

      if (type === 'message.send') {
        const content = ((msg.content as string) ?? '').trim();
        if (!content) {
          ws.send(frame('error', { code: 'empty_content', message: 'content is required' }));
          ws.send(frame('message.create', { content: '', done: true }));
          return;
        }

        ws.send(frame('typing.start'));

        // Log inbound
        this.db.logActivity(deviceId, deviceId, content);
        this.db.logEdgeSync(deviceId, 'inbound', 'message', { content });
        const convId = `edge-${deviceId}`;
        this.db.upsertConversation(convId, `Edge: ${deviceId}`);
        this.db.insertMessage(convId, 'user', content);

        // Forward to NanoBot gateway
        try {
          const reply = await forwardToGateway(deviceId, content);
          if (reply) {
            ws.send(frame('message.create', { content: reply, done: true }));
            ws.send(frame('typing.stop'));
            this.db.logActivity('assistant', deviceId, reply);
            this.db.insertMessage(convId, 'assistant', reply);
            this.db.logEdgeSync(deviceId, 'outbound', 'reply', { reply });
          } else {
            ws.send(frame('message.create', { content: '', done: true }));
            ws.send(frame('typing.stop'));
          }
        } catch (e) {
          ws.send(frame('error', { code: 'internal_error', message: String(e) }));
          ws.send(frame('message.create', { content: '', done: true }));
          ws.send(frame('typing.stop'));
        }
        return;
      }
      // Unknown types silently ignored
    });

    ws.on('close', () => {
      clearInterval(ping);
      this.registry.unregisterWs(deviceId);
      bridgeLog.info('edge', `[${deviceId}] WS disconnected`);
    });

    ws.on('error', (e) => {
      bridgeLog.error('edge', `[${deviceId}] WS error: ${e}`);
    });
  }

  // ── HTTP routing ──────────────────────────────────────────────────────────

  private async _route(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const method = req.method ?? 'GET';
    const rawUrl = req.url ?? '/';
    const url = rawUrl.split('?')[0];

    this._cors(res);
    if (method === 'OPTIONS') { res.writeHead(204).end(); return; }

    // ── Device API ──────────────────────────────────────────────────────────

    const syncMatch        = url.match(/^\/api\/devices\/([^/]+)\/sync$/);
    const statusMatch      = url.match(/^\/api\/devices\/([^/]+)\/status$/);
    const messagesMatch    = url.match(/^\/api\/devices\/([^/]+)\/messages$/);
    const msgStreamMatch   = url.match(/^\/api\/devices\/([^/]+)\/messages\/stream$/);
    const conversationMatch = url.match(/^\/api\/devices\/([^/]+)\/conversation$/);
    const commandMatch     = url.match(/^\/api\/devices\/([^/]+)\/command$/);
    const commandIdxMatch  = url.match(/^\/api\/devices\/([^/]+)\/command\/(\d+)$/);
    const messageMatch     = url.match(/^\/api\/devices\/([^/]+)\/message$/);
    const deviceMatch      = url.match(/^\/api\/devices\/([^/]+)$/);

    if (method === 'GET'    && url === '/api/devices')         return this._listDevices(res);
    if (method === 'GET'    && url === '/api/health')          return this._health(res);
    if (method === 'GET'    && url === '/api/stats')           return this._stats(res);
    if (method === 'GET'    && url === '/api/config')          return this._config(res);
    if (method === 'GET'    && url === '/api/conversations')   return this._conversations(res);

    if (method === 'POST'   && syncMatch)           return this._handleSync(req, res, syncMatch[1]);
    if (method === 'GET'    && statusMatch)         return this._deviceStatus(res, statusMatch[1]);
    if (method === 'GET'    && messagesMatch)       return this._deviceMessages(req, res, messagesMatch[1]);
    if (method === 'GET'    && msgStreamMatch)      return this._deviceMessagesStream(req, res, msgStreamMatch[1]);
    if (method === 'GET'    && conversationMatch)   return this._deviceConversation(res, conversationMatch[1]);
    if (method === 'POST'   && commandMatch)        return this._queueCommand(req, res, commandMatch[1]);
    if (method === 'DELETE' && commandIdxMatch)     return this._deleteCommand(res, commandIdxMatch[1], parseInt(commandIdxMatch[2]));
    if (method === 'DELETE' && commandMatch)        return this._clearCommands(res, commandMatch[1]);
    if (method === 'POST'   && messageMatch)        return this._adminMessage(req, res, messageMatch[1]);

    if (method === 'DELETE' && deviceMatch)         return this._removeDevice(res, deviceMatch[1]);
    if (method === 'POST'   && url.match(/^\/api\/devices\/([^/]+)\/disconnect$/)) {
      return this._disconnectDevice(res, url.match(/^\/api\/devices\/([^/]+)\/disconnect$/)![1]);
    }

    // Legacy
    if (method === 'POST'   && url === '/api/sync')                    return this._handleSync(req, res, 'reachy');
    if (method === 'POST'   && url === '/api/dashboard/command')       return this._queueCommand(req, res, 'reachy');
    if (method === 'GET'    && url === '/api/dashboard/status')        return this._deviceStatus(res, 'reachy');

    // ── Static Files ────────────────────────────────────────────────────────

    if (method === 'GET') {
      const STATIC_DIR = process.env.STATIC_DIR || join(process.cwd(), '../dashboard/client/build');
      let filePath = join(STATIC_DIR, url === '/' ? 'index.html' : url);
      
      if (existsSync(filePath) && !filePath.endsWith('/')) {
        const ext = filePath.split('.').pop() || '';
        const types: Record<string, string> = {
          html: 'text/html',
          js: 'application/javascript',
          css: 'text/css',
          png: 'image/png',
          jpg: 'image/jpeg',
          gif: 'image/gif',
          svg: 'image/svg+xml',
          json: 'application/json',
          ico: 'image/x-icon',
        };
        res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain' });
        res.end(readFileSync(filePath));
        return;
      }
      
      // SPA fallback
      const indexHtml = join(STATIC_DIR, 'index.html');
      if (existsSync(indexHtml)) {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(readFileSync(indexHtml));
        return;
      }
    }

    res.writeHead(404).end(JSON.stringify({ error: 'Not found' }));
  }

  // ── Handlers ──────────────────────────────────────────────────────────────

  private _listDevices(res: ServerResponse): void {
    const now = Date.now() / 1000;
    const list = this.registry.list().map(d => {
      const wsConnected = this.registry.isWsConnected(d.deviceId);
      const age = now - d.lastSeen;
      const online = wsConnected || (d.lastSeen > 0 && age < d.config.pollIntervalSeconds * 3);
      return {
        device_id: d.deviceId,
        last_seen: d.lastSeen,
        online,
        ws_connected: wsConnected,
        poll_interval_seconds: d.config.pollIntervalSeconds,
        pending_directives: d.directives.length,
        status: d.status,
      };
    }).sort((a, b) => b.last_seen - a.last_seen);
    this._json(res, 200, { devices: list });
  }

  private _deviceStatus(res: ServerResponse, deviceId: string): void {
    const d = this.registry.getOrCreate(deviceId);
    const wsConnected = this.registry.isWsConnected(deviceId);
    this._json(res, 200, {
      device_id: deviceId,
      status: d.status,
      ws_connected: wsConnected,
      online: wsConnected || (d.lastSeen > 0 && (Date.now() / 1000 - d.lastSeen) < d.config.pollIntervalSeconds * 3),
      directives: d.directives,
      poll_interval_seconds: d.config.pollIntervalSeconds,
      // Legacy compat
      reachy: d.status,
      pending_commands: d.directives,
    });
  }

  private _deviceMessages(req: IncomingMessage, res: ServerResponse, deviceId: string): void {
    const rawLimit = new URL(req.url ?? '/', 'http://localhost').searchParams.get('limit') || '100';
    const limit = Math.min(parseInt(rawLimit) || 100, 500);
    this._json(res, 200, this.db.getMessages(deviceId, limit));
  }

  private _deviceConversation(res: ServerResponse, deviceId: string): void {
    const convId = `edge-${deviceId}`;
    const conv = this.db.getConversation(convId);
    if (conv) {
      this._json(res, 200, conv);
    } else {
      // Return empty conversation shape so dashboard doesn't 503
      this._json(res, 200, {
        id: convId,
        title: `Edge: ${deviceId}`,
        created_at: null,
        updated_at: null,
        message_count: 0,
        model: 'nanobot',
      });
    }
  }

  private _deviceMessagesStream(req: IncomingMessage, res: ServerResponse, deviceId: string): void {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    if (res.socket) res.socket.setNoDelay(true);

    const heartbeat = setInterval(() => res.write(': ping\n\n'), 15_000);
    const url = req.url ?? '';
    let lastId = parseInt(new URL(url, 'http://localhost').searchParams.get('lastId') || '0');

    const poll = setInterval(() => {
      try {
        const rows = this.db.getMessages(deviceId, 50) as Array<{ id: number; source: string; sender: string; content: string; created_at: string }>;
        for (const row of rows) {
          if (row.id > lastId) {
            res.write(`id: ${row.id}\ndata: ${JSON.stringify(row)}\n\n`);
            lastId = row.id;
          }
        }
      } catch { /* ignore */ }
    }, 2_000);

    req.on('close', () => { clearInterval(heartbeat); clearInterval(poll); });
  }

  private async _queueCommand(req: IncomingMessage, res: ServerResponse, deviceId: string): Promise<void> {
    const body = await this._readBody(req);
    const { command } = JSON.parse(body.toString());
    if (!command?.trim()) { res.writeHead(400).end('missing command'); return; }

    // Try to push directly if WS-connected, otherwise queue
    const pushed = this.registry.pushDirective(deviceId, String(command));
    this.db.logActivity('bridge', deviceId, String(command));
    bridgeLog.info('edge', `[${deviceId}] command ${pushed ? 'pushed via WS' : 'queued for poll'}: ${command}`);
    this._json(res, 200, { queued: !pushed, pushed });
  }

  private _deleteCommand(res: ServerResponse, deviceId: string, idx: number): void {
    const d = this.registry.getOrCreate(deviceId);
    if (isNaN(idx) || idx < 0 || idx >= d.directives.length) {
      res.writeHead(404).end();
    } else {
      d.directives.splice(idx, 1);
      this._json(res, 200, { deleted: true, remaining: d.directives.length });
    }
  }

  private _clearCommands(res: ServerResponse, deviceId: string): void {
    const d = this.registry.getOrCreate(deviceId);
    d.directives = [];
    this._json(res, 200, { cleared: true });
  }

  private _disconnectDevice(res: ServerResponse, deviceId: string): void {
    const d = this.registry.get(deviceId);
    if (!d) { res.writeHead(404).end(JSON.stringify({ error: 'Device not found' })); return; }
    if (d.ws?.readyState === WebSocket.OPEN) {
      d.ws.close(1000, 'Disconnected by admin');
      bridgeLog.info('edge', `[${deviceId}] forcibly disconnected by admin`);
      this._json(res, 200, { disconnected: true });
    } else {
      this._json(res, 200, { disconnected: false, reason: 'Device not connected' });
    }
  }

  private _removeDevice(res: ServerResponse, deviceId: string): void {
    const d = this.registry.get(deviceId);
    if (!d) { res.writeHead(404).end(JSON.stringify({ error: 'Device not found' })); return; }
    // Close WS if open
    if (d.ws?.readyState === WebSocket.OPEN) {
      d.ws.close(1000, 'Removed by admin');
    }
    this.registry.remove(deviceId);
    bridgeLog.info('edge', `[${deviceId}] removed from registry by admin`);
    this._json(res, 200, { removed: true });
  }

  private async _adminMessage(req: IncomingMessage, res: ServerResponse, deviceId: string): Promise<void> {
    const body = await this._readBody(req);
    const { content } = JSON.parse(body.toString());
    if (!content?.trim()) { res.writeHead(400).end('missing content'); return; }

    // Log admin message
    this.db.logActivity('bridge', deviceId, String(content));
    const convId = `edge-${deviceId}`;
    this.db.upsertConversation(convId, `Edge: ${deviceId}`);
    this.db.insertMessage(convId, 'user', String(content));

    // Forward to gateway async — reply arrives via pushDirective
    forwardToGateway(deviceId, String(content))
      .then(reply => {
        if (reply) {
          this.registry.pushDirective(deviceId, `reply:${reply}`);
          this.db.logActivity('assistant', deviceId, reply);
          this.db.insertMessage(convId, 'assistant', reply);
        }
      })
      .catch(e => bridgeLog.error('edge', `[${deviceId}] admin message error: ${e}`));

    this._json(res, 200, { sent: true });
  }

  private async _handleSync(req: IncomingMessage, res: ServerResponse, deviceId: string): Promise<void> {
    const body = await this._readBody(req);
    const sig = (req.headers['x-bridge-signature'] as string) ?? '';
    const d = this.registry.getOrCreate(deviceId);

    // HMAC verify
    if (d.config.secret) {
      const expected = createHmac('sha256', d.config.secret).update(body).digest('hex');
      try {
        if (!timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) {
          res.writeHead(401).end('Unauthorized');
          return;
        }
      } catch {
        res.writeHead(401).end('Unauthorized');
        return;
      }
    }

    const payload = JSON.parse(body.toString());
    const telemetry: Array<{ kind: string; content?: string }> = Array.isArray(payload.telemetry)
      ? payload.telemetry
      : Array.isArray(payload.pending_feedback)
        ? (payload.pending_feedback as string[]).map(c => ({ kind: 'message', content: c }))
        : [];

    this.registry.updateStatus(deviceId, payload.status ?? payload.reachy_status ?? {});
    this.db.logEdgeSync(deviceId, 'inbound', 'sync', { telemetry: telemetry.length });

    // Forward message-kind telemetry to gateway
    for (const item of telemetry) {
      if (item.kind !== 'message' || !item.content) continue;
      const timeBucket = Math.floor(Date.now() / 300_000);
      const hash = `${deviceId}:${item.content.trim()}:${timeBucket}`;
      if (hash === d.lastForwardedMsgHash) continue;
      d.lastForwardedMsgHash = hash;

      const convId = `edge-${deviceId}`;
      this.db.logActivity(deviceId, deviceId, item.content);
      this.db.upsertConversation(convId, `Edge: ${deviceId}`);
      this.db.insertMessage(convId, 'user', item.content);

      forwardToGateway(deviceId, item.content)
        .then(reply => {
          if (reply) {
            d.directives.push({ command: `reply:${reply}`, queued_at: Date.now() / 1000 });
            this.db.logActivity('assistant', deviceId, reply);
            this.db.insertMessage(convId, 'assistant', reply);
            this.db.logEdgeSync(deviceId, 'outbound', 'reply', { reply: reply.slice(0, 100) });
          }
        })
        .catch(e => bridgeLog.error('edge', `[${deviceId}] gateway forward error: ${e}`));
    }

    const directives = this.registry.drainDirectives(deviceId);
    this._json(res, 200, {
      status: 'synced',
      directives,
      poll_interval_seconds: d.config.pollIntervalSeconds,
      pending_commands: directives,
      knowledge_update: [],
    });
  }

  private _health(res: ServerResponse): void {
    this._json(res, 200, { status: 'ok', uptime: process.uptime() });
  }

  private _stats(res: ServerResponse): void {
    this._json(res, 200, this.db.getStats());
  }

  private _config(res: ServerResponse): void {
    this._json(res, 200, { edge_token_configured: !!this.edgeToken });
  }

  private _cors(res: ServerResponse): void {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Bridge-Signature');
  }

  private _json(res: ServerResponse, status: number, body: unknown): void {
    res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body));
  }

  private _readBody(req: IncomingMessage): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on('data', c => chunks.push(c));
      req.on('end', () => resolve(Buffer.concat(chunks)));
      req.on('error', reject);
    });
  }

  private _conversations(res: ServerResponse): void {
    this._json(res, 200, this.db.getConversations());
  }
}
