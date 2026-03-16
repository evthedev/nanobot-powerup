import WebSocket from 'ws';
import crypto from 'crypto';

export interface DeviceConfig {
  secret: string;
  pollIntervalSeconds: number;
}

export interface DeviceState {
  deviceId: string;
  config: DeviceConfig;
  ws: WebSocket | null;           // live WS connection, null if poll-only
  directives: { command: string; queued_at: number }[];
  status: Record<string, unknown>;
  lastSeen: number;
  lastForwardedMsgHash: string | null;
}

export class DeviceRegistry {
  private devices = new Map<string, DeviceState>();

  getOrCreate(deviceId: string, config?: Partial<DeviceConfig>): DeviceState {
    if (!this.devices.has(deviceId)) {
      this.devices.set(deviceId, {
        deviceId,
        config: { secret: config?.secret ?? '', pollIntervalSeconds: config?.pollIntervalSeconds ?? 30 },
        ws: null,
        directives: [],
        status: { last_seen: 0 },
        lastSeen: 0,
        lastForwardedMsgHash: null,
      });
    }
    return this.devices.get(deviceId)!;
  }

  get(deviceId: string): DeviceState | undefined {
    return this.devices.get(deviceId);
  }

  list(): DeviceState[] {
    return [...this.devices.values()];
  }

  registerWs(deviceId: string, ws: WebSocket): void {
    const d = this.getOrCreate(deviceId);
    d.ws = ws;
    d.lastSeen = Date.now() / 1000;
  }

  unregisterWs(deviceId: string): void {
    const d = this.devices.get(deviceId);
    if (d) d.ws = null;
  }

  remove(deviceId: string): void {
    this.devices.delete(deviceId);
  }

  isWsConnected(deviceId: string): boolean {
    const d = this.devices.get(deviceId);
    return !!(d?.ws?.readyState === WebSocket.OPEN);
  }

  pushDirective(deviceId: string, command: string): boolean {
    const d = this.getOrCreate(deviceId);
    if (d.ws?.readyState === WebSocket.OPEN) {
      // Push immediately down the live socket
      d.ws.send(JSON.stringify({
        type: 'message.create',
        id: crypto.randomUUID(),
        ts: Date.now(),
        content: command,
        done: true,
      }));
      return true;
    }
    // Fallback: queue for next poll
    d.directives.push({ command, queued_at: Date.now() / 1000 });
    return false;
  }

  drainDirectives(deviceId: string): { command: string; queued_at: number }[] {
    const d = this.devices.get(deviceId);
    if (!d) return [];
    const out = [...d.directives];
    d.directives = [];
    return out;
  }

  updateStatus(deviceId: string, status: Record<string, unknown>): void {
    const d = this.getOrCreate(deviceId);
    d.status = { ...d.status, ...status, last_seen: Date.now() / 1000 };
    d.lastSeen = Date.now() / 1000;
  }
}
