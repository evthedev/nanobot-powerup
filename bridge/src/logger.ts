/**
 * Bridge logger — writes to ~/.nanobot/logs/bridge.log in Loguru-compatible format
 * so logs surface in the dashboard /logs page when tailed.
 */

import { appendFileSync, mkdirSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const NANOBOT_HOME = process.env.NANOBOT_HOME || join(homedir(), '.nanobot');
const LOG_DIR = join(NANOBOT_HOME, 'logs');
const LOG_FILE = join(LOG_DIR, 'bridge.log');

function log(level: string, module: string, msg: string): void {
  const now = new Date();
  const ts = now.toISOString().replace('T', ' ').replace('Z', '').slice(0, 23);
  const padded = level.padEnd(8);
  const line = `${ts} | ${padded} | bridge.${module}:- - ${msg}\n`;
  try {
    if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });
    appendFileSync(LOG_FILE, line);
  } catch (_) { /* ignore */ }
  if (level === 'ERROR' || level === 'CRITICAL') {
    console.error(`[${module}]`, msg);
  } else {
    console.log(`[${module}]`, msg);
  }
}

export const bridgeLog = {
  info: (module: string, msg: string) => log('INFO', module, msg),
  warn: (module: string, msg: string) => log('WARN', module, msg),
  error: (module: string, msg: string) => log('ERROR', module, msg),
};
