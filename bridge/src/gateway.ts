import WebSocket from 'ws';
import { bridgeLog } from './logger.js';

const GATEWAY_URL = process.env.NANOBOT_WS || 'ws://localhost:18791';

/**
 * Forward a message to the NanoBot gateway and return the reply.
 * Uses a stable session key per device so conversation context is retained.
 */
export async function forwardToGateway(deviceId: string, content: string, system?: string): Promise<string> {
  const sessionId = `edge-${deviceId}`;
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(GATEWAY_URL);
    const parts: string[] = [];
    const timer = setTimeout(() => { ws.close(); resolve(parts.join('').trim()); }, 120_000);

    ws.once('open', () => {
      ws.send(JSON.stringify({ session_id: sessionId, content, system }));
      bridgeLog.info('gateway', `[${deviceId}] → gateway: ${content.slice(0, 80)}`);
    });

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.type === 'message' && msg.content) parts.push(msg.content);
        if (msg.type === 'done' || (msg.type === 'message' && msg.content)) {
          clearTimeout(timer);
          ws.close();
          resolve(parts.join('').trim());
        }
      } catch { /* ignore */ }
    });

    ws.once('close', () => { clearTimeout(timer); resolve(parts.join('').trim()); });
    ws.once('error', (e) => { clearTimeout(timer); reject(e); });
  });
}
