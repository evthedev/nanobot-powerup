import Database from 'better-sqlite3';
import { join } from 'path';
import { homedir } from 'os';
import { randomUUID } from 'crypto';

const DB_PATH = process.env.DB_PATH || join(homedir(), '.nanobot', 'chat.db');

export class DB {
  private db: InstanceType<typeof Database>;

  constructor() {
    this.db = new Database(DB_PATH);
    this.db.pragma('journal_mode = WAL');
    this.migrate();
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS edge_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL DEFAULT 'default',
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
      CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'New Conversation',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        message_count INTEGER DEFAULT 0,
        model TEXT DEFAULT 'nanobot'
      );
      CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        tokens_used INTEGER DEFAULT 0,
        model TEXT,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
      );
    `);
  }

  logActivity(source: string, sender: string, content: string): void {
    this.db.prepare('INSERT INTO activity_log (source, sender, content) VALUES (?, ?, ?)')
      .run(source, sender, content.slice(0, 500));
  }

  logEdgeSync(deviceId: string, direction: 'inbound' | 'outbound', eventType: string, payload: unknown): void {
    this.db.prepare('INSERT INTO edge_sync_log (device_id, direction, event_type, payload) VALUES (?, ?, ?, ?)')
      .run(deviceId, direction, eventType, JSON.stringify(payload));
  }

  upsertConversation(convId: string, title: string): void {
    this.db.prepare(`
      INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at, model)
      VALUES (?, ?, datetime('now'), datetime('now'), 'nanobot')
    `).run(convId, title);
  }

  insertMessage(convId: string, role: 'user' | 'assistant', content: string): void {
    this.db.prepare(`
      INSERT INTO messages (id, conversation_id, role, content, created_at)
      VALUES (?, ?, ?, ?, datetime('now'))
    `).run(randomUUID(), convId, role, content);
    this.db.prepare(`
      UPDATE conversations SET updated_at = datetime('now'),
      message_count = (SELECT COUNT(*) FROM messages WHERE conversation_id = ?)
      WHERE id = ?
    `).run(convId, convId);
  }

  getMessages(deviceId: string, limit = 100): unknown[] {
    return this.db.prepare(`
      SELECT id, source, sender, content, created_at FROM activity_log
      WHERE source = ? OR (source = 'assistant' AND sender = ?) OR (source = 'bridge' AND sender = ?)
      ORDER BY created_at ASC LIMIT ?
    `).all(deviceId, deviceId, deviceId, limit);
  }

  getConversation(convId: string): unknown {
    return this.db.prepare('SELECT * FROM conversations WHERE id = ?').get(convId);
  }

  getConversations(limit = 50): unknown[] {
    return this.db.prepare(`
      SELECT id, title, created_at, updated_at, message_count, model
      FROM conversations ORDER BY updated_at DESC LIMIT ?
    `).all(limit);
  }

  getStats(): { conversations: number; messages: number } {
    const convs = (this.db.prepare('SELECT COUNT(*) as n FROM conversations').get() as { n: number }).n;
    const msgs = (this.db.prepare('SELECT COUNT(*) as n FROM messages').get() as { n: number }).n;
    return { conversations: convs, messages: msgs };
  }

  getActivitySince(sinceTs: number, excludeSource: string): unknown[] {
    const since = new Date(sinceTs * 1000).toISOString().replace('T', ' ').slice(0, 23);
    return this.db.prepare(`
      SELECT source, sender, content, created_at FROM activity_log
      WHERE created_at >= ? AND source != ?
      ORDER BY created_at ASC LIMIT 20
    `).all(since, excludeSource);
  }

  close(): void { this.db.close(); }
}
