/**
 * Edge device bridge HTTP server.
 *
 * Endpoints:
 *   POST /api/devices/:id/sync     — device polls (HMAC-signed)
 *   POST /api/devices/:id/command  — queue directive for device
 *   DELETE /api/devices/:id/command/:idx — remove one directive
 *   DELETE /api/devices/:id/command      — clear all directives
 *   GET  /api/devices              — list all known devices + last_seen
 *   GET  /api/devices/:id/status   — single device status + queue
 *
 * Legacy endpoints (backward compat):
 *   POST /api/sync                 → routed to device_id "default"
 *   POST /api/dashboard/command    → routed to device_id "default"
 *   DELETE /api/dashboard/command/:idx
 *   DELETE /api/dashboard/command
 *   GET  /api/dashboard/status     → device_id "default"
 */

import { createServer, IncomingMessage, ServerResponse } from 'http';
import { createHmac, timingSafeEqual } from 'crypto';
import { homedir } from 'os';
import { join } from 'path';
import { randomUUID } from 'crypto';
import { readFileSync } from 'fs';
import WebSocket, { WebSocketServer } from 'ws';
import Database from 'better-sqlite3';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DeviceStatus {
  [key: string]: unknown;
  last_seen: number;
}

/** Typed telemetry item (device → brain). */
export interface TelemetryItem {
  kind: 'message' | 'event' | 'metric' | 'snapshot';
  // kind=message
  content?: string;
  // kind=event
  type?: string;
  [key: string]: unknown;
}

interface SyncPayload {
  // New protocol
  telemetry?: unknown[];
  // Legacy compat
  pending_feedback?: unknown[];
  // Status blob (device reports its own state)
  status?: Record<string, unknown>;
  // Legacy status field names
  reachy_status?: Record<string, unknown>;
  vision_status?: unknown;
  pending_facts?: unknown[];
}

interface DeviceConfig {
  enabled: boolean;
  secret: string;
  poll_interval_seconds: number;
  stream_mode: string | null;
}

interface DeviceState {
  directives: { command: string; queued_at: number }[];
  status: DeviceStatus;
  config: DeviceConfig;
}

// ── Config loader ─────────────────────────────────────────────────────────────

interface LoadedConfig {
  devices: Record<string, DeviceConfig>;
}

function loadDeviceConfigs(): LoadedConfig {
  try {
    const cfgPath = process.env.NANOBOT_CONFIG || join(homedir(), '.nanobot', 'config.json');
    const raw = JSON.parse(readFileSync(cfgPath, 'utf8'));
    const edgeDevices = raw?.channels?.edgeDevices ?? raw?.channels?.edge_devices ?? {};
    const devices: Record<string, DeviceConfig> = {};
    for (const [id, d] of Object.entries(edgeDevices.devices ?? {})) {
      const dc = d as Record<string, unknown>;
      devices[id] = {
        enabled: dc.enabled !== false,
        secret: (dc.secret ?? dc.Secret ?? '') as string,
        poll_interval_seconds: (dc.pollIntervalSeconds ?? dc.poll_interval_seconds ?? 30) as number,
        stream_mode: (dc.streamMode ?? dc.stream_mode ?? null) as string | null,
      };
    }
    // Legacy: if no edgeDevices but legacy bridge config present, auto-register default device
    if (Object.keys(devices).length === 0) {
      const rb = raw?.channels?.reachyBridge ?? raw?.channels?.reachy_bridge ?? {};
      if (rb.enabled && rb.secret) {
        devices['reachy'] = { enabled: true, secret: rb.secret, poll_interval_seconds: 30, stream_mode: null };
      }
    }
    return { devices };
  } catch {
    return { devices: {} };
  }
}

// ── Server ────────────────────────────────────────────────────────────────────

export class EdgeBridgeServer {
  private _devices: Map<string, DeviceState> = new Map();
  private _server: ReturnType<typeof createServer> | null = null;
  private _wss: WebSocketServer | null = null;
  private _db: InstanceType<typeof Database>;
  private _gatewayUrl: string;

  constructor(private port: number) {
    this._gatewayUrl = process.env.NANOBOT_WS || 'ws://nanobot-gateway:18791';
    const dbPath = process.env.DB_PATH || join(homedir(), '.nanobot', 'chat.db');
    this._db = new Database(dbPath);
    this._db.pragma('journal_mode = WAL');
    this._db.exec(`
      CREATE TABLE IF NOT EXISTS edge_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL DEFAULT 'reachy',
        direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        sender TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON activity_log (created_at);
    `);
    this._initDevices();
  }

  private _initDevices(): void {
    const { devices: configs } = loadDeviceConfigs();
    for (const [id, cfg] of Object.entries(configs)) {
      if (cfg.enabled) {
        this._devices.set(id, {
          directives: [],
          status: { last_seen: 0 },
          config: cfg,
        });
      }
    }
    if (this._devices.size > 0) {
      console.log(`🔌 Edge bridge: registered devices: ${[...this._devices.keys()].join(', ')}`);
    } else {
      console.log('🔌 Edge bridge: no devices configured (will accept any device_id)');
    }
  }

  private _getOrCreateDevice(id: string): DeviceState {
    if (!this._devices.has(id)) {
      const { devices: configs } = loadDeviceConfigs();
      const cfg = configs[id] ?? { enabled: true, secret: '', poll_interval_seconds: 30, stream_mode: null };
      this._devices.set(id, { directives: [], status: { last_seen: 0 }, config: cfg });
    }
    return this._devices.get(id)!;
  }

  start(): void {
    this._server = createServer((req, res) => this._route(req, res));
    this._wss = new WebSocketServer({ noServer: true });
    this._server.on('upgrade', (req, socket, head) => {
      const url = req.url ?? '';
      const match = url.match(/^\/api\/devices\/([^/?]+)\/stream/);
      if (!match) { socket.destroy(); return; }
      this._wss!.handleUpgrade(req, socket, head, (ws) => {
        this._handleStream(ws, req, match[1]);
      });
    });
    this._server.listen(this.port, '0.0.0.0', () => {
      console.log(`🔌 Edge bridge HTTP+WS server on :${this.port}`);
    });
  }

  stop(): void {
    this._wss?.close();
    this._server?.close();
    this._db.close();
  }

  private async _route(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = req.url ?? '';
    const method = req.method ?? '';

    try {
      // ── New endpoints ──────────────────────────────────────────────────────
      const syncMatch = url.match(/^\/api\/devices\/([^/]+)\/sync$/);
      const cmdMatch = url.match(/^\/api\/devices\/([^/]+)\/command$/);
      const cmdIdxMatch = url.match(/^\/api\/devices\/([^/]+)\/command\/(\d+)$/);
      const statusMatch = url.match(/^\/api\/devices\/([^/]+)\/status$/);

      if (method === 'POST' && syncMatch) {
        await this._handleSync(req, res, syncMatch[1]);
      } else if (method === 'POST' && cmdMatch) {
        await this._handleCommand(req, res, cmdMatch[1]);
      } else if (method === 'DELETE' && cmdIdxMatch) {
        this._handleDeleteDirective(res, cmdIdxMatch[1], parseInt(cmdIdxMatch[2], 10));
      } else if (method === 'DELETE' && cmdMatch) {
        this._handleClearDirectives(res, cmdMatch[1]);
      } else if (method === 'GET' && url === '/api/devices') {
        this._handleListDevices(res);
      } else if (method === 'GET' && statusMatch) {
        this._handleStatus(res, statusMatch[1]);

      // ── Legacy endpoints (backward compat) ──────────────────────────────
      } else if (method === 'POST' && url === '/api/sync') {
        await this._handleSync(req, res, 'reachy');
      } else if (method === 'POST' && url === '/api/dashboard/command') {
        await this._handleCommand(req, res, 'reachy');
      } else if (method === 'DELETE' && url.match(/^\/api\/dashboard\/command\/\d+$/)) {
        const idx = parseInt(url.split('/').pop()!, 10);
        this._handleDeleteDirective(res, 'reachy', idx);
      } else if (method === 'DELETE' && url === '/api/dashboard/command') {
        this._handleClearDirectives(res, 'reachy');
      } else if (method === 'GET' && url === '/api/dashboard/status') {
        this._handleStatus(res, 'reachy');

      } else {
        res.writeHead(404).end();
      }
    } catch (e) {
      console.error('Edge bridge error:', e);
      res.writeHead(500).end(JSON.stringify({ error: String(e) }));
    }
  }

  // ── WebSocket stream handler ───────────────────────────────────────────────

  private _handleStream(ws: WebSocket, req: IncomingMessage, deviceId: string): void {
    const device = this._getOrCreateDevice(deviceId);

    // Auth: Authorization: Bearer <secret>
    const auth = req.headers['authorization'] ?? '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';
    if (device.config.secret && token !== device.config.secret) {
      ws.send(JSON.stringify({ type: 'error', id: randomUUID(), ts: Date.now(), code: 'auth_failed', message: 'Invalid secret' }));
      ws.close(1008, 'Unauthorized');
      return;
    }

    console.log(`🔌 [${deviceId}] stream connected`);
    const _frame = (type: string, extra: Record<string, unknown> = {}) =>
      JSON.stringify({ type, id: randomUUID(), ts: Date.now(), ...extra });

    ws.send(_frame('hello'));

    ws.on('message', async (raw) => {
      let msg: Record<string, unknown>;
      try { msg = JSON.parse(raw.toString()); } catch { return; }

      if (msg.type === 'ping') {
        ws.send(_frame('pong', { id: msg.id }));
        return;
      }

      if (msg.type === 'message.send') {
        const content = (msg.content as string | undefined)?.trim();
        if (!content) {
          ws.send(_frame('error', { code: 'empty_content', message: 'content is required' }));
          ws.send(_frame('message.create', { content: '', done: true }));
          return;
        }

        // Log to activity_log
        try {
          this._db.prepare('INSERT INTO activity_log (source, sender, content) VALUES (?, ?, ?)')
            .run(deviceId, deviceId, content.slice(0, 500));
        } catch { /* non-fatal */ }

        ws.send(_frame('typing.start'));

        try {
          const sessionId = `edge-${deviceId}-${randomUUID()}`;
          await new Promise<void>((resolve, reject) => {
            const gws = new WebSocket(this._gatewayUrl);
            const timer = setTimeout(() => { gws.close(); resolve(); }, 120000);
            gws.once('open', () => {
              gws.send(JSON.stringify({ session_id: sessionId, content }));
            });
            gws.on('message', (data) => {
              try {
                const gmsg = JSON.parse(data.toString());
                if (gmsg.type === 'message' && gmsg.content) {
                  // Stream each word as a delta
                  const words = (gmsg.content as string).split(' ');
                  words.forEach((word, i) => {
                    ws.send(_frame('message.create', { content: i === 0 ? word : ' ' + word, done: false }));
                  });
                }
                if (gmsg.type === 'done') {
                  clearTimeout(timer);
                  gws.close();
                  resolve();
                }
              } catch { /* ignore */ }
            });
            gws.once('close', () => { clearTimeout(timer); resolve(); });
            gws.once('error', (e) => { clearTimeout(timer); reject(e); });
          });
        } catch (e) {
          ws.send(_frame('error', { code: 'internal_error', message: String(e) }));
        }

        ws.send(_frame('typing.stop'));
        ws.send(_frame('message.create', { content: '', done: true }));
      }
    });

    ws.on('close', () => console.log(`🔌 [${deviceId}] stream disconnected`));
    ws.on('error', (e) => console.error(`🔌 [${deviceId}] stream error:`, e));
  }

  private _readBody(req: IncomingMessage): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on('data', (c: Buffer) => chunks.push(c));
      req.on('end', () => resolve(Buffer.concat(chunks)));
      req.on('error', reject);
    });
  }

  private _verifyHmac(body: Buffer, sig: string, secret: string): boolean {
    if (!secret) return true;
    const expected = createHmac('sha256', secret).update(body).digest('hex');
    try {
      return timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
    } catch {
      return false;
    }
  }

  private _json(res: ServerResponse, status: number, body: unknown): void {
    res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body));
  }

  private async _handleSync(req: IncomingMessage, res: ServerResponse, deviceId: string): Promise<void> {
    const body = await this._readBody(req);
    const sig = (req.headers['x-bridge-signature'] as string) ?? '';
    const device = this._getOrCreateDevice(deviceId);

    if (!this._verifyHmac(body, sig, device.config.secret)) {
      res.writeHead(401).end('Unauthorized');
      return;
    }

    const payload: SyncPayload = JSON.parse(body.toString());

    // Normalise telemetry — accept both new `telemetry` and legacy `pending_feedback`
    const rawTelemetry: unknown[] = Array.isArray(payload.telemetry)
      ? payload.telemetry
      : Array.isArray(payload.pending_feedback)
        ? payload.pending_feedback
        : [];

    const telemetry: TelemetryItem[] = rawTelemetry.map(item =>
      typeof item === 'string'
        ? { kind: 'message' as const, content: item }
        : item as TelemetryItem
    );

    // Merge device status blob
    const statusBlob = payload.status ?? payload.reachy_status ?? {};

    // Build context digest — activity from other channels since device's last_seen
    const context = this._buildContext(deviceId, device.status.last_seen);

    // Update last_seen now (after context query so we don't include current sync)
    device.status = { ...device.status, ...statusBlob, last_seen: Date.now() / 1000 };
    this._db.prepare(
      'INSERT INTO edge_sync_log (device_id, direction, event_type, payload) VALUES (?, ?, ?, ?)'
    ).run(deviceId, 'inbound', 'sync', JSON.stringify({ status: statusBlob, telemetry }));

    // Write message-kind telemetry to activity_log
    for (const item of telemetry) {
      if (item.kind === 'message' && item.content) {
        this._db.prepare(
          'INSERT INTO activity_log (source, sender, content) VALUES (?, ?, ?)'
        ).run(deviceId, deviceId, (item.content as string).slice(0, 500));
      }
    }

    // Forward message-kind telemetry to gateway
    for (const item of telemetry) {
      if (item.kind === 'message' && item.content) {
        this._forwardToGateway(deviceId, item.content).catch(e =>
          console.error(`Edge bridge [${deviceId}]: gateway forward error:`, e)
        );
      }
    }

    // Drain directives
    const directives = [...device.directives];
    device.directives = [];

    if (directives.length > 0) {
      this._db.prepare(
        'INSERT INTO edge_sync_log (device_id, direction, event_type, payload) VALUES (?, ?, ?, ?)'
      ).run(deviceId, 'outbound', 'directives', JSON.stringify({ directives }));
    }

    this._json(res, 200, {
      status: 'synced',
      directives,
      context,
      poll_interval_seconds: device.config.poll_interval_seconds,
      // Legacy compat fields
      pending_commands: directives,
      knowledge_update: context,
    });
  }

  private _buildContext(deviceId: string, lastSeenTs: number): object[] {
    if (!lastSeenTs) return [];
    try {
      const since = new Date(lastSeenTs * 1000).toISOString().replace('T', ' ').slice(0, 23);
      const rows = this._db.prepare(
        `SELECT source, sender, content, created_at FROM activity_log
         WHERE created_at >= ? AND source != ?
         ORDER BY created_at ASC LIMIT 20`
      ).all(since, deviceId) as { source: string; sender: string; content: string; created_at: string }[];
      return rows.map(r => ({
        source: r.source,
        sender: r.sender,
        summary: r.content.slice(0, 200),
        at: r.created_at,
      }));
    } catch {
      return [];
    }
  }

  private static readonly ALLOWED_DIRECTIVES = new Set([
    'wake', 'sleep', 'restart_app', 'restart_picoclaw', 'set_volume', 'capture_frame',
  ]);

  private async _handleCommand(req: IncomingMessage, res: ServerResponse, deviceId: string): Promise<void> {
    const body = await this._readBody(req);
    const { command } = JSON.parse(body.toString());
    if (!command) { res.writeHead(400).end('missing command'); return; }
    if (!EdgeBridgeServer.ALLOWED_DIRECTIVES.has(String(command))) {
      this._json(res, 400, { error: `Unknown directive: ${command}` });
      return;
    }
    const device = this._getOrCreateDevice(deviceId);
    device.directives.push({ command, queued_at: Date.now() / 1000 });
    console.log(`🔌 [${deviceId}] directive queued: ${command}`);
    this._json(res, 200, { queued: true });
  }

  private _handleDeleteDirective(res: ServerResponse, deviceId: string, idx: number): void {
    const device = this._getOrCreateDevice(deviceId);
    if (isNaN(idx) || idx < 0 || idx >= device.directives.length) {
      res.writeHead(404).end();
    } else {
      device.directives.splice(idx, 1);
      this._json(res, 200, { deleted: true, remaining: device.directives.length });
    }
  }

  private _handleClearDirectives(res: ServerResponse, deviceId: string): void {
    const device = this._getOrCreateDevice(deviceId);
    device.directives = [];
    this._json(res, 200, { cleared: true });
  }

  private _handleListDevices(res: ServerResponse): void {
    const now = Date.now() / 1000;
    const list = [...this._devices.entries()].map(([id, d]) => {
      const pollInterval = d.config.poll_interval_seconds;
      const age = now - d.status.last_seen;
      const online = d.status.last_seen > 0 && age < pollInterval * 3;
      return {
        device_id: id,
        last_seen: d.status.last_seen,
        online,
        poll_interval_seconds: pollInterval,
        stream_mode: d.config.stream_mode,
        pending_directives: d.directives.length,
        status: d.status,
      };
    }).sort((a, b) => b.last_seen - a.last_seen);
    this._json(res, 200, { devices: list });
  }

  private _handleStatus(res: ServerResponse, deviceId: string): void {
    const device = this._getOrCreateDevice(deviceId);
    this._json(res, 200, {
      device_id: deviceId,
      status: device.status,
      directives: device.directives,
      poll_interval_seconds: device.config.poll_interval_seconds,
      // Legacy compat
      reachy: device.status,
      pending_commands: device.directives,
    });
  }

  private async _forwardToGateway(deviceId: string, content: string): Promise<void> {
    const sessionId = `edge-${deviceId}-${randomUUID()}`;
    const reply = await new Promise<string>((resolve, reject) => {
      const ws = new WebSocket(this._gatewayUrl);
      const parts: string[] = [];
      const timer = setTimeout(() => { ws.close(); resolve(parts.join('').trim()); }, 120000);
      ws.once('open', () => {
        ws.send(JSON.stringify({ session_id: sessionId, content }));
        console.log(`🔌 [${deviceId}] → gateway: ${content.slice(0, 60)}`);
      });
      ws.on('message', (data) => {
        try {
          const msg = JSON.parse(data.toString());
          if (msg.type === 'message' && msg.content) parts.push(msg.content);
          // Resolve on first message — edge sessions have no subagents so we don't
          // need to wait for the deferred 'done' (which fires after 90s).
          if ((msg.type === 'message' && msg.content) || msg.type === 'done') {
            clearTimeout(timer); ws.close(); resolve(parts.join('').trim());
          }
        } catch { /* ignore non-JSON */ }
      });
      ws.once('close', () => { clearTimeout(timer); resolve(parts.join('').trim()); });
      ws.once('error', (e) => { clearTimeout(timer); reject(e); });
    });
    if (reply) {
      const device = this._getOrCreateDevice(deviceId);
      device.directives.push({ command: `reply:${reply}`, queued_at: Date.now() / 1000 });
      console.log(`🔌 [${deviceId}] reply queued (${reply.length} chars)`);
      // Write assistant reply to activity_log so dashboard can show the conversation
      try {
        this._db.prepare('INSERT INTO activity_log (source, sender, content) VALUES (?, ?, ?)')
          .run('assistant', deviceId, reply.slice(0, 500));
      } catch { /* non-fatal */ }
    }
  }
}
