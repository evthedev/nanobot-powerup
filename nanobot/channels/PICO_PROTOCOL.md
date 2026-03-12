# Picoclaw → Nanobot Connector

Connect to nanobot's edge channel over WebSocket. Picoclaw is the client; nanobot is the server.

## Connect

```
wss://<nanobot-host>:18791/picoclaw/ws[?device_id=<string>]
Authorization: Bearer <token>
```

On success: 101 Switching Protocols, then server sends a `hello` frame. On bad/missing token: HTTP 401, connection rejected.

`device_id` is optional. Each unique value gets its own conversation context. Defaults to `"default"` if absent. Use it if you have more than one picoclaw device connecting to the same nanobot instance.

## Wire Format

All frames are JSON text frames with this envelope:

```json
{"type": "<string>", "id": "<uuid>", "ts": <unix_ms>}
```

Type-specific fields sit at the top level alongside `type`, `id`, `ts`. No nested objects.

## Send a Message

```json
{"type": "message.send", "id": "...", "ts": ..., "content": "turn on the lights"}
```

`content` is required and non-empty.

## Receive a Response

```json
{"type": "message.create", "id": "...", "ts": ..., "content": "Done, lights are on.", "done": true}
```

`content` is a **delta** (new text only). If multiple frames arrive for one turn, concatenate them. The frame with `done: true` is the final frame — this is the authoritative turn-complete signal. Wait for it before sending the next message.

Server may also send the full response in a single `done: true` frame. Handle both.

## Optional UX Frames

`typing.start` and `typing.stop` may arrive around a response. They are hints for UI (LED, animation). They are **not guaranteed**, especially on error paths. Do not rely on them for control flow — use `done: true`.

## Errors

```json
{"type": "error", "id": "...", "ts": ..., "code": "internal_error", "message": "agent loop failed"}
```

Codes: `auth_failed`, `empty_content`, `rate_limited`, `internal_error`.

The connection stays open after errors (except `auth_failed` pre-upgrade). An error during a turn is always followed by `message.create {done: true}`.

## Keepalive

Send `{"type": "ping", "id": "...", "ts": ...}` every 30 seconds. Server replies `pong` with your `id` echoed back. If no `pong` within 10 seconds, assume dead — close and reconnect.

## Reconnect

Picoclaw owns reconnection. Use exponential backoff. The conversation context survives reconnects and server restarts (nanobot persists it server-side by `device_id`).

## Forward Compatibility

Ignore unknown `type` values. New fields may appear on existing types. Nothing will be removed without a version bump.

## Quick Reference

| Direction | Type | Key Fields |
|-----------|------|------------|
| → server | `message.send` | `content` |
| → server | `ping` | — |
| ← server | `hello` | — |
| ← server | `message.create` | `content`, `done` |
| ← server | `typing.start` | — |
| ← server | `typing.stop` | — |
| ← server | `error` | `code`, `message` |
| ← server | `pong` | `id` (echoed) |
