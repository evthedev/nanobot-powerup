# linux/amd64 required: patchright (scrapling stealth browser) only provides x64 Linux binaries
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js 20, Chromium + dependencies for Playwright MCP, Tesseract OCR + Poppler for image/PDF recognition
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | gpg --dearmor -o /etc/apt/keyrings/githubcli.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs gh \
        chromium libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libasound2 libpango-1.0-0 libcairo2 fonts-liberation \
        tesseract-ocr tesseract-ocr-eng poppler-utils ffmpeg && \
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

# Install Scrapling with all optional deps and bake the patchright browser binary into the image.
# PATCHRIGHT_BROWSERS_PATH must be set BEFORE 'scrapling install' so the binary lands in the
# image layer, not deferred to runtime (deferred = StealthyFetcher crashes on first use).
ENV PATCHRIGHT_BROWSERS_PATH=/root/.patchright
ENV PYTHONHTTPSVERIFY=0
ENV CURL_CA_BUNDLE=""
ENV REQUESTS_CA_BUNDLE=""
RUN pip install "scrapling[all]" && scrapling install

# Install Tesseract OCR and Python wrapper
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytesseract

# Create config directory
RUN mkdir -p /root/.nanobot

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["status"]
