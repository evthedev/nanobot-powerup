/**
 * WebSocket server for Python-Node.js bridge communication.
 * Security: binds to 127.0.0.1 only; optional BRIDGE_TOKEN auth.
 */

import { WebSocketServer, WebSocket } from 'ws';
import { writeFileSync, unlinkSync, existsSync } from 'fs';
import { join } from 'path';
import { WhatsAppClient, InboundMessage } from './whatsapp.js';

const QR_FILE = 'whatsapp-pending-qr.json';
const STATUS_FILE = 'whatsapp-status.json';

interface SendCommand {
  type: 'send';
  to: string;
  text: string;
}

interface SendImageCommand {
  type: 'send_image';
  to: string;
  url: string;
  caption?: string;
}

interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error';
  [key: string]: unknown;
}

export class BridgeServer {
  private wss: WebSocketServer | null = null;
  private wa: WhatsAppClient | null = null;
  private clients: Set<WebSocket> = new Set();

  constructor(private port: number, private authDir: string, private token?: string, private host: string = '127.0.0.1') {}

  async start(): Promise<void> {
    // host: 127.0.0.1 for local; 0.0.0.0 for Docker (internal network only)
    this.wss = new WebSocketServer({ host: this.host, port: this.port });
    console.log(`🌉 Bridge server listening on ws://${this.host}:${this.port}`);
    if (this.token) console.log('🔒 Token authentication enabled');

    // Initialize WhatsApp client
    this.wa = new WhatsAppClient({
      authDir: this.authDir,
      onMessage: (msg) => this.broadcast({ type: 'message', ...msg }),
      onQR: (qr) => {
        this.broadcast({ type: 'qr', qr });
        this.writeQrToFile(qr);
      },
      onStatus: (status) => {
        this.broadcast({ type: 'status', status });
        this.writeStatusFile(status);
        if (status === 'connected') this.clearQrFile();
      },
    });

    // Handle WebSocket connections
    this.wss.on('connection', (ws) => {
      if (this.token) {
        // Require auth handshake as first message
        const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
        ws.once('message', (data) => {
          clearTimeout(timeout);
          try {
            const msg = JSON.parse(data.toString());
            if (msg.type === 'auth' && msg.token === this.token) {
              console.log('🔗 Python client authenticated');
              this.setupClient(ws);
            } else {
              ws.close(4003, 'Invalid token');
            }
          } catch {
            ws.close(4003, 'Invalid auth message');
          }
        });
      } else {
        console.log('🔗 Python client connected');
        this.setupClient(ws);
      }
    });

    // Connect to WhatsApp
    await this.wa.connect();
  }

  private setupClient(ws: WebSocket): void {
    this.clients.add(ws);

    ws.on('message', async (data) => {
      try {
        const cmd = JSON.parse(data.toString()) as SendCommand;
        await this.handleCommand(cmd);
        ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
      } catch (error) {
        console.error('Error handling command:', error);
        ws.send(JSON.stringify({ type: 'error', error: String(error) }));
      }
    });

    ws.on('close', () => {
      console.log('🔌 Python client disconnected');
      this.clients.delete(ws);
    });

    ws.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.clients.delete(ws);
    });
  }

  private async handleCommand(cmd: SendCommand | SendImageCommand): Promise<void> {
    if (cmd.type === 'send' && this.wa) {
      await this.wa.sendMessage(cmd.to, cmd.text);
    } else if (cmd.type === 'send_image' && this.wa) {
      await this.wa.sendImageMessage(cmd.to, cmd.url, cmd.caption);
    }
  }

  private broadcast(msg: BridgeMessage): void {
    const data = JSON.stringify(msg);
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(data);
      }
    }
  }

  /** Write QR to shared file so dashboard can display it without SSH. */
  private writeQrToFile(qr: string): void {
    try {
      const qrPath = join(this.authDir, '..', QR_FILE);
      writeFileSync(qrPath, JSON.stringify({ qr, timestamp: Date.now() }), 'utf8');
    } catch (e) {
      console.error('Failed to write QR file:', e);
    }
  }

  /** Clear QR file when connected. */
  private clearQrFile(): void {
    try {
      const qrPath = join(this.authDir, '..', QR_FILE);
      if (existsSync(qrPath)) unlinkSync(qrPath);
    } catch (e) {
      console.error('Failed to clear QR file:', e);
    }
  }

  /** Write connection status for dashboard. */
  private writeStatusFile(status: string): void {
    try {
      const statusPath = join(this.authDir, '..', STATUS_FILE);
      writeFileSync(statusPath, JSON.stringify({ status, timestamp: Date.now() }), 'utf8');
    } catch (e) {
      console.error('Failed to write status file:', e);
    }
  }

  async stop(): Promise<void> {
    // Close all client connections
    for (const client of this.clients) {
      client.close();
    }
    this.clients.clear();

    // Close WebSocket server
    if (this.wss) {
      this.wss.close();
      this.wss = null;
    }

    // Disconnect WhatsApp
    if (this.wa) {
      await this.wa.disconnect();
      this.wa = null;
    }
  }
}
