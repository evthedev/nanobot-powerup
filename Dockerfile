# linux/amd64 required: cloakbrowser only provides x64 Linux binaries (no arm64)
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js 20, Chromium + dependencies for Playwright MCP, Tesseract OCR + Poppler for image/PDF recognition
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs \
        chromium libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libasound2 libpango-1.0-0 libcairo2 fonts-liberation \
        tesseract-ocr tesseract-ocr-eng poppler-utils && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Tell Playwright to use system Chromium instead of downloading its own
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf nanobot bridge

# Copy the full source and install
COPY nanobot/ nanobot/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN npm install && npm run build
WORKDIR /app

# Install CloakBrowser + pre-download stealth Chromium binary (~200MB, cached in image layer)
RUN pip install cloakbrowser && \
    python -c "from cloakbrowser import ensure_binary; ensure_binary()"

# Install Scrapling with all optional deps (patchright, curl_cffi, browserforge are not pulled
# by bare 'pip install scrapling' — they are extras required by StealthyFetcher and Fetcher).
# Patchright uses PLAYWRIGHT_BROWSERS_PATH to locate its browser, but that env var is already
# pointed at /usr/bin for the system Chromium used by Playwright/CloakBrowser. Override it to
# a dedicated path so patchright installs its patched Chromium without conflicting.
ENV PATCHRIGHT_BROWSERS_PATH=/root/.patchright
RUN pip install "scrapling[all]" && \
    PLAYWRIGHT_BROWSERS_PATH=/root/.patchright scrapling install

# Create config directory
RUN mkdir -p /root/.nanobot

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["status"]
