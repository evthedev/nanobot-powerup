/**
 * Reachy bridge HTTP server.
 *
 * Endpoints:
 *   POST /api/sync              — Reachy polls this (HMAC-signed, external)
 *   POST /api/dashboard/command — Shantelle queues commands (localhost only)
 *   GET  /api/dashboard/status  — Shantelle reads cached Reachy state
 *   POST /api/enrich            — Bridge KG/RAG enrichment (HMAC-signed)
 */

import { createServer, IncomingMessage, ServerResponse } from 'http';
import { createHmac, timingSafeEqual } from 'crypto';
import { homedir } from 'os';
import { join } from 'path';
import Database from 'better-sqlite3';

export interface ReachyStatus {
  daemon: string;
  conversation_app: string;
  picoclaw: string;
  last_seen: number;
}

interface SyncPayload {
  reachy_status?: Partial<ReachyStatus>;
  vision_status?: unknown;
  pending_facts?: unknown[];
  pending_feedback?: unknown[];
  local_memory?: unknown;
}

export class ReachyBridgeServer {
  private _pendingCommands: { command: string; queued_at: number }[] = [];
  private _lastStatus: ReachyStatus = { daemon: 'unknown', conversation_app: 'unknown', picoclaw: 'unknown', last_seen: 0 };
  private _server: ReturnType<typeof createServer> | null = null;
  private _db: InstanceType<typeof Database>;

  constructor(private port: number, private secret: string) {
    const dbPath = process.env.DB_PATH || join(homedir(), '.nanobot', 'chat.db');
    this._db = new Database(dbPath);
    this._db.pragma('journal_mode = WAL');
    this._db.exec(`
      CREATE TABLE IF NOT EXISTS reachy_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      )
    `);
  }

  start(): void {
    this._server = createServer((req, res) => this._route(req, res));
    this._server.listen(this.port, '0.0.0.0', () => {
      console.log(`🤖 Reachy bridge HTTP server on :${this.port}`);
    });
  }

  stop(): void {
    this._server?.close();
    this._db.close();
  }

  private async _route(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = req.url ?? '';
    const method = req.method ?? '';

    try {
      if (method === 'POST' && url === '/api/sync') {
        await this._handleSync(req, res);
      } else if (method === 'POST' && url === '/api/dashboard/command') {
        await this._handleCommand(req, res);
      } else if (method === 'GET' && url === '/api/dashboard/status') {
        this._handleStatus(res);
      } else if (method === 'POST' && url === '/api/enrich') {
        await this._handleEnrich(req, res);
      } else {
        res.writeHead(404).end();
      }
    } catch (e) {
      console.error('Reachy bridge error:', e);
      res.writeHead(500).end(JSON.stringify({ error: String(e) }));
    }
  }

  private _readBody(req: IncomingMessage): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on('data', (c: Buffer) => chunks.push(c));
      req.on('end', () => resolve(Buffer.concat(chunks)));
      req.on('error', reject);
    });
  }

  private _verifyHmac(body: Buffer, sig: string): boolean {
    if (!this.secret) return true; // no secret configured → open
    const expected = createHmac('sha256', this.secret).update(body).digest('hex');
    try {
      return timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
    } catch {
      return false;
    }
  }

  private _json(res: ServerResponse, status: number, body: unknown): void {
    const data = JSON.stringify(body);
    res.writeHead(status, { 'Content-Type': 'application/json' }).end(data);
  }

  private async _handleSync(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const body = await this._readBody(req);
    const sig = (req.headers['x-bridge-signature'] as string) ?? '';
    if (!this._verifyHmac(body, sig)) {
      res.writeHead(401).end('Unauthorized');
      return;
    }

    const payload: SyncPayload = JSON.parse(body.toString());

    // Cache Reachy status
    if (payload.reachy_status) {
      this._lastStatus = {
        ...this._lastStatus,
        ...payload.reachy_status,
        last_seen: Date.now() / 1000,
      };
    }

    // Log inbound sync
    this._db.prepare(
      'INSERT INTO reachy_sync_log (direction, event_type, payload) VALUES (?, ?, ?)'
    ).run('inbound', 'sync', JSON.stringify({
      reachy_status: payload.reachy_status,
      vision_status: payload.vision_status,
      pending_facts: payload.pending_facts,
    }));

    // Drain pending commands
    const commands = [...this._pendingCommands];
    this._pendingCommands = [];

    // Log outbound commands if any
    if (commands.length > 0) {
      this._db.prepare(
        'INSERT INTO reachy_sync_log (direction, event_type, payload) VALUES (?, ?, ?)'
      ).run('outbound', 'commands', JSON.stringify({ commands }));
    }

    this._json(res, 200, {
      pending_commands: commands,
      knowledge_update: [],
      trust_config: {},
    });
  }

  private async _handleCommand(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const body = await this._readBody(req);
    const { command } = JSON.parse(body.toString());
    if (!command) { res.writeHead(400).end('missing command'); return; }
    this._pendingCommands.push({ command, queued_at: Date.now() / 1000 });
    console.log(`🤖 Reachy command queued: ${command}`);
    this._json(res, 200, { queued: true });
  }

  private _handleStatus(res: ServerResponse): void {
    this._json(res, 200, { reachy: this._lastStatus });
  }

  private async _handleEnrich(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const body = await this._readBody(req);
    const sig = (req.headers['x-bridge-signature'] as string) ?? '';
    if (!this._verifyHmac(body, sig)) {
      res.writeHead(401).end('Unauthorized');
      return;
    }
    // Stub — extend with real KG/RAG lookup as needed
    this._json(res, 200, { knowledge_context: '', truth_context: '', contact_facts: [] });
  }
}
