# ── Stage 1: Build React ──────────────────────────────────────────────────────
FROM node:20-alpine AS react-builder

WORKDIR /build/client
COPY client/package*.json ./
RUN npm ci --silent

COPY client/ ./
# Production build — REACT_APP_API_URL is empty so all API calls use relative paths
RUN npm run build

# ── Stage 2: Production Express server ───────────────────────────────────────
FROM node:20-alpine

WORKDIR /app

# Server dependencies only
COPY server/package*.json ./
RUN npm ci --only=production --silent

COPY server/ ./

# Copy React build output — Express will serve this as static files
COPY --from=react-builder /build/client/build ./public

# DB and logs live on the shared nanobot volume; use env vars for paths
ENV DB_PATH=/data/chat.db
ENV NANOBOT_WS=ws://nanobot-gateway:18791
ENV PORT=3001

EXPOSE 3001
CMD ["node", "index.js"]
