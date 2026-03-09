#!/usr/bin/env node
/**
 * nanobot WhatsApp Bridge
 * 
 * This bridge connects WhatsApp Web to nanobot's Python backend
 * via WebSocket. It handles authentication, message forwarding,
 * and reconnection logic.
 * 
 * Usage:
 *   npm run build && npm start
 *   
 * Or with custom settings:
 *   BRIDGE_PORT=3001 AUTH_DIR=~/.nanobot/whatsapp npm start
 */

// Polyfill crypto for Baileys in ESM
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { BridgeServer } from './server.js';
import { ReachyBridgeServer } from './reachy.js';
import { homedir } from 'os';
import { join } from 'path';

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const HOST = process.env.BRIDGE_HOST || '127.0.0.1';  // 0.0.0.0 for Docker
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.nanobot', 'whatsapp-auth');
const TOKEN = process.env.BRIDGE_TOKEN || undefined;
const REACHY_PORT = parseInt(process.env.REACHY_BRIDGE_PORT || '18790', 10);
const REACHY_SECRET = process.env.BRIDGE_SECRET || '';
const REACHY_ENABLED = process.env.REACHY_BRIDGE_ENABLED === 'true';

console.log('🐈 nanobot WhatsApp Bridge');
console.log('========================\n');

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN, HOST);

if (REACHY_ENABLED) {
  const reachy = new ReachyBridgeServer(REACHY_PORT, REACHY_SECRET);
  reachy.start();
  process.on('SIGINT', () => reachy.stop());
  process.on('SIGTERM', () => reachy.stop());
}

// Handle graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n\nShutting down...');
  await server.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

// Start the server
server.start().catch((error) => {
  console.error('Failed to start bridge:', error);
  process.exit(1);
});
