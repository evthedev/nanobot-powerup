const { createProxyMiddleware } = require('http-proxy-middleware');

// Disable CRA proxy buffering so SSE streams (chat messages + log stream) arrive in real-time.
// Without this, the proxy buffers chunked responses and the client sees nothing until the
// connection closes — breaking the streaming typewriter effect entirely.
const sseHeaders = (proxyRes) => {
  proxyRes.headers['cache-control'] = 'no-cache';
  proxyRes.headers['x-accel-buffering'] = 'no';
  delete proxyRes.headers['content-encoding']; // prevent gzip interference
};

module.exports = function (app) {
  app.use(
    '/api',
    createProxyMiddleware({
      target: 'http://localhost:3001',
      changeOrigin: true,
      onProxyRes: sseHeaders,
    })
  );
};
