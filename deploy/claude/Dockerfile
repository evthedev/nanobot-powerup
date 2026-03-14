FROM node:20-bookworm-slim

# Install git + curl (needed for ttyd download and claude oauth)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd static binary (x86_64)
RUN curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
    -o /usr/local/bin/ttyd && chmod +x /usr/local/bin/ttyd

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace

EXPOSE 7681

CMD ["ttyd", "-p", "7681", "--writable", "--base-path", "/ttyd", "-t", "fontSize=14", "bash"]
