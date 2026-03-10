/**
 * WhatsApp client wrapper using Baileys.
 * Based on OpenClaw's working implementation.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { writeFileSync, mkdirSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  downloadMediaMessage,
  getContentType,
  extensionForMediaMessage,
} from '@whiskeysockets/baileys';

import { Boom } from '@hapi/boom';
import qrcode from 'qrcode-terminal';
import pino from 'pino';

const VERSION = '0.1.0';

/** Directory for downloaded WhatsApp media (images etc.). Same path as Telegram channel. */
const MEDIA_DIR = process.env.NANOBOT_MEDIA_DIR || join(homedir(), '.nanobot', 'media');

const IMAGE_MESSAGE = 'imageMessage';
const VIDEO_MESSAGE = 'videoMessage';

export interface InboundMessage {
  id: string;
  sender: string;
  pn: string;
  direction: 'inbound' | 'outbound';
  content: string;
  timestamp: number;
  isGroup: boolean;
  /** Local file paths for downloaded media (images/videos) so the agent can pass them to the LLM. */
  media?: string[];
}

export interface WhatsAppClientOptions {
  authDir: string;
  onMessage: (msg: InboundMessage) => void;
  onQR: (qr: string) => void;
  onStatus: (status: string) => void;
}

export class WhatsAppClient {
  private sock: any = null;
  private options: WhatsAppClientOptions;
  private reconnecting = false;

  constructor(options: WhatsAppClientOptions) {
    this.options = options;
  }

  async connect(): Promise<void> {
    const logger = pino({ level: 'silent' });
    const { state, saveCreds } = await useMultiFileAuthState(this.options.authDir);
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Using Baileys version: ${version.join('.')}`);

    // Create socket following OpenClaw's pattern
    this.sock = makeWASocket({
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, logger),
      },
      version,
      logger,
      printQRInTerminal: false,
      browser: ['nanobot', 'cli', VERSION],
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });

    // Handle WebSocket errors
    if (this.sock.ws && typeof this.sock.ws.on === 'function') {
      this.sock.ws.on('error', (err: Error) => {
        console.error('WebSocket error:', err.message);
      });
    }

    // Handle connection updates
    this.sock.ev.on('connection.update', async (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Display QR code in terminal
        console.log('\n📱 Scan this QR code with WhatsApp (Linked Devices):\n');
        qrcode.generate(qr, { small: true });
        this.options.onQR(qr);
      }

      if (connection === 'close') {
        const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

        console.log(`Connection closed. Status: ${statusCode}, Will reconnect: ${shouldReconnect}`);
        this.options.onStatus('disconnected');

        if (shouldReconnect && !this.reconnecting) {
          this.reconnecting = true;
          // 408 = stale session; clear creds so next connect generates a fresh QR
          if (statusCode === 408) {
            try {
              const fs = await import('fs');
              for (const f of fs.readdirSync(this.options.authDir)) {
                fs.rmSync(`${this.options.authDir}/${f}`, { recursive: true, force: true });
              }
              console.log('Stale session cleared, will show QR on reconnect');
            } catch {}
          }
          console.log('Reconnecting in 5 seconds...');
          setTimeout(() => {
            this.reconnecting = false;
            this.connect();
          }, 5000);
        }
      } else if (connection === 'open') {
        console.log('✅ Connected to WhatsApp');
        this.options.onStatus('connected');
      }
    });

    // Save credentials on update
    this.sock.ev.on('creds.update', saveCreds);

    // Handle incoming messages
    this.sock.ev.on('messages.upsert', async ({ messages, type }: { messages: any[]; type: string }) => {
      if (type !== 'notify') return;

      for (const msg of messages) {
        // Skip status updates
        if (msg.key.remoteJid === 'status@broadcast') continue;

        const content = this.extractMessageContent(msg);
        if (!content) continue;

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;
        const direction: 'inbound' | 'outbound' = msg.key.fromMe ? 'outbound' : 'inbound';

        let media: string[] | undefined;
        if (direction === 'inbound') {
          const paths = await this.downloadMediaToFile(msg);
          if (paths?.length) media = paths;
        }

        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          direction,
          content,
          timestamp: msg.messageTimestamp as number,
          isGroup,
          media,
        });
      }
    });
  }

  private extractMessageContent(msg: any): string | null {
    const message = msg.message;
    if (!message) return null;

    // Unwrap view-once envelope
    const m = message.viewOnceMessage?.message
      || message.viewOnceMessageV2?.message
      || message.viewOnceMessageV2Extension?.message
      || message;

    // Text message
    if (m.conversation) {
      return m.conversation;
    }

    // Extended text (reply, link preview)
    if (m.extendedTextMessage?.text) {
      return m.extendedTextMessage.text;
    }

    // Image with or without caption (so agent receives the image and optional caption)
    if (m.imageMessage) {
      const cap = m.imageMessage.caption;
      return cap ? `[Image] ${cap}` : '[Image]';
    }

    // Video with caption
    if (m.videoMessage?.caption) {
      return `[Video] ${m.videoMessage.caption}`;
    }

    // Video without caption
    if (m.videoMessage) {
      return '[Video]';
    }

    // Document with caption
    if (m.documentMessage?.caption) {
      return `[Document] ${m.documentMessage.caption}`;
    }

    // Document without caption
    if (m.documentMessage) {
      return '[Document]';
    }

    // Voice/Audio message
    if (m.audioMessage) {
      return `[Voice Message]`;
    }

    return null;
  }

  /** Download media from message to MEDIA_DIR and return local file path, or null on failure. */
  private async downloadMediaToFile(msg: any): Promise<string[] | null> {
    if (!this.sock || !msg.message) return null;
    // Unwrap view-once envelope so getContentType sees the inner imageMessage/videoMessage
    const unwrapped = msg.message.viewOnceMessage?.message
      || msg.message.viewOnceMessageV2?.message
      || msg.message.viewOnceMessageV2Extension?.message
      || msg.message;
    const contentType = getContentType(unwrapped);
    if (!contentType || (contentType !== IMAGE_MESSAGE && contentType !== VIDEO_MESSAGE)) return null;
    // Use unwrapped message for download so Baileys finds the media keys
    const msgForDownload = unwrapped === msg.message ? msg : { ...msg, message: unwrapped };

    try {
      const buffer = await downloadMediaMessage(
        msgForDownload,
        'buffer',
        {},
        {
          logger: pino({ level: 'silent' }),
          reuploadRequest: this.sock.updateMediaMessage,
        }
      );
      if (!buffer || !Buffer.isBuffer(buffer)) return null;

      if (!existsSync(MEDIA_DIR)) {
        mkdirSync(MEDIA_DIR, { recursive: true });
      }

      let ext = '.jpg';
      try {
        ext = extensionForMediaMessage(msg.message) || ext;
        if (!ext.startsWith('.')) ext = '.' + ext;
      } catch {
        // keep .jpg for image, .mp4 for video fallback
        if (contentType === VIDEO_MESSAGE) ext = '.mp4';
      }

      const safeId = (msg.key?.id || 'media').replace(/[^a-zA-Z0-9]/g, '_');
      const filename = `wa_${safeId}_${Date.now()}${ext}`;
      const filePath = join(MEDIA_DIR, filename);
      writeFileSync(filePath, buffer);
      return [filePath];
    } catch (err) {
      console.error('WhatsApp bridge: failed to download media:', err);
      return null;
    }
  }

  async sendMessage(to: string, text: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    await this.sock.sendMessage(to, { text });
  }

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
