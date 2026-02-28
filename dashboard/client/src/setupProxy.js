/**
 * CRA development proxy — routes /api requests to the Express dashboard server.
 *
 * In Docker Compose dev mode, the dashboard Express server is reachable at
 * http://nanobot-dashboard:3001 (Docker service name), set via PROXY_TARGET.
 * Locally (outside Docker), it defaults to http://localhost:3001.
 */
const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function (app) {
  const target = process.env.PROXY_TARGET || 'http://localhost:3001';

  app.use(
    '/api',
    createProxyMiddleware({
      target,
      changeOrigin: true,
      xfwd: true,
      logLevel: 'warn',
      // Required for SSE (logs/stream, telegram/stream): disable response buffering
      selfHandleResponse: false,
      on: {
        proxyRes: (proxyRes) => {
          const ct = proxyRes.headers['content-type'] || '';
          if (ct.includes('text/event-stream')) {
            proxyRes.headers['cache-control'] = 'no-cache';
            proxyRes.headers['x-accel-buffering'] = 'no';
          }
        },
      },
    })
  );
};
