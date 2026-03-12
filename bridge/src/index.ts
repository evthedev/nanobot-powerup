#!/usr/bin/env node
/**
 * nanobot Edge Bridge
 *
 * HTTP + WebSocket server for edge device integration.
 * Handles device sync, directive queuing, and real-time streaming.
 *
 * Usage:
 *   npm run build && npm start
 */

// Polyfill crypto for Baileys in ESM
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { BridgeServer } from './server.js';
import { EdgeBridgeServer } from './edge_bridge.js';
import { bridgeLog } from './logger.js';
import { homedir } from 'os';
import { join } from 'path';

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const HOST = process.env.BRIDGE_HOST || '127.0.0.1';  // 0.0.0.0 for Docker
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.nanobot', 'whatsapp-auth');
const TOKEN = process.env.BRIDGE_TOKEN || undefined;
const EDGE_PORT = parseInt(process.env.REACHY_BRIDGE_PORT || '18790', 10);
const EDGE_ENABLED = process.env.EDGE_DEVICES_ENABLED === 'true';
const WHATSAPP_ENABLED = process.env.WHATSAPP_ENABLED !== 'false';

bridgeLog.info('main', 'nanobot Bridge');

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN, HOST);

if (EDGE_ENABLED) {
  const edge = new EdgeBridgeServer(EDGE_PORT);
  edge.start();
  process.on('SIGINT', () => edge.stop());
  process.on('SIGTERM', () => edge.stop());
}

// Handle graceful shutdown
process.on('SIGINT', async () => {
  bridgeLog.info('main', 'Shutting down...');
  await server.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

if (WHATSAPP_ENABLED) {
  server.start().catch((error) => {
    bridgeLog.error('main', `Failed to start bridge: ${error}`);
    process.exit(1);
  });
} else {
  bridgeLog.info('main', 'WhatsApp bridge disabled (WHATSAPP_ENABLED=false)');
}
