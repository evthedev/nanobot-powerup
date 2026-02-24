#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# nanobot EC2 bootstrap — run once on a fresh Amazon Linux 2023 / Ubuntu 24.04
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_REPO/main/deploy/ec2-setup.sh | bash
# Or after git clone:
#   bash deploy/ec2-setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NANOBOT_DATA="/opt/nanobot"
AWS_REGION="${AWS_REGION:-ap-southeast-2}"

echo "=== nanobot EC2 setup ==="
echo "Repo:        $REPO_DIR"
echo "Data dir:    $NANOBOT_DATA"
echo "AWS region:  $AWS_REGION"
echo ""

# ── 1. Install Docker + Docker Compose ───────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  if command -v apt-get &>/dev/null; then
    # Ubuntu / Debian
    apt-get update -q
    apt-get install -y -q ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
  else
    # Amazon Linux 2023
    dnf install -y docker
    systemctl enable --now docker
    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-"$(uname -m)" \
      -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
  fi
  usermod -aG docker "${SUDO_USER:-$USER}" || true
  echo "Docker installed."
else
  echo "Docker already installed: $(docker --version)"
fi

# ── 2. Create /opt/nanobot data directory and initial config ─────────────────
echo ""
echo "Setting up $NANOBOT_DATA ..."
mkdir -p "$NANOBOT_DATA"/{logs,workspace/screenshots,workspace/skills/review,sessions,memory}

CONFIG="$NANOBOT_DATA/config.json"
if [ ! -f "$CONFIG" ]; then
  echo "Creating default config (edit $CONFIG to add your API keys)..."
  cat > "$CONFIG" << 'CONFIG_EOF'
{
  "agents": {
    "defaults": {
      "workspace": "/root/.nanobot/workspace",
      "model": "openai/gpt-4o-mini",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20
    }
  },
  "channels": {
    "web": { "enabled": true, "port": 18791, "allowFrom": [] },
    "telegram": { "enabled": false, "token": "", "allowFrom": [] }
  },
  "providers": {
    "openrouter": { "apiKey": "REPLACE_WITH_OPENROUTER_KEY" }
  },
  "gateway": { "host": "0.0.0.0", "port": 18790 },
  "tools": {
    "web": { "search": { "apiKey": "REPLACE_WITH_BRAVE_KEY", "maxResults": 5 } },
    "exec": { "timeout": 600 },
    "restrictToWorkspace": false,
    "mcpServers": {
      "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
    }
  }
}
CONFIG_EOF
  echo ""
  echo "⚠️  ACTION REQUIRED: Edit $CONFIG and replace:"
  echo "   - REPLACE_WITH_OPENROUTER_KEY  → your OpenRouter API key"
  echo "   - REPLACE_WITH_BRAVE_KEY       → your Brave Search API key"
  echo ""
fi

# Copy review skill
SKILL_SRC="$REPO_DIR/workspace/skills/review/SKILL.md"   # if it exists in repo
SKILL_DST="$NANOBOT_DATA/workspace/skills/review/SKILL.md"
if [ -f "$SKILL_SRC" ] && [ ! -f "$SKILL_DST" ]; then
  cp "$SKILL_SRC" "$SKILL_DST"
  echo "Copied review skill."
fi

# ── 3. Open firewall ports (if using ufw) ────────────────────────────────────
if command -v ufw &>/dev/null; then
  echo "Opening ports 22, 80, 443 in ufw..."
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

# ── 4. Build images and start the stack ──────────────────────────────────────
echo ""
echo "Building Docker images (this takes 3-5 minutes first time)..."
cd "$REPO_DIR"

# Production: no override file, use /opt/nanobot, ports 80+443
docker compose build

echo ""
echo "Starting nanobot stack..."
docker compose up -d

echo ""
echo "=== Setup complete ==="
echo ""
docker compose ps
echo ""
echo "Access the dashboard at: https://$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')"
echo "Username: nanobot"
echo "Password: Nb9kQmX3pL7!"
echo ""
echo "Note: Your browser will show a self-signed certificate warning — click 'Advanced > Proceed'."
echo "To use a real cert, point a domain at this IP and run: certbot --nginx -d yourdomain.com"
