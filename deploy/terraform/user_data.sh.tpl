#!/usr/bin/env bash
# Runs once on first boot via EC2 user_data.
# Logs go to /var/log/nanobot-setup.log
set -euo pipefail
exec > >(tee /var/log/nanobot-setup.log) 2>&1

echo "=== nanobot first-boot setup ==="
export DEBIAN_FRONTEND=noninteractive
export AWS_REGION="${aws_region}"

# ── Mount data EBS volume to /opt/nanobot ─────────────────────────────────────
# The volume is attached as /dev/xvdf (kernel renames /dev/sdf → /dev/xvdf).
# Wait up to 30s for the device to appear (attachment may lag a few seconds).
DATA_DEVICE=""
for dev in /dev/xvdf /dev/nvme1n1; do
  for i in $(seq 1 30); do
    if [ -b "$dev" ]; then DATA_DEVICE="$dev"; break 2; fi
    sleep 1
  done
done

if [ -z "$DATA_DEVICE" ]; then
  echo "WARNING: data device not found — /opt/nanobot will use root volume"
else
  echo "Data device: $DATA_DEVICE"
  if ! blkid "$DATA_DEVICE" &>/dev/null; then
    echo "Formatting $DATA_DEVICE as ext4..."
    mkfs -t ext4 "$DATA_DEVICE"
  fi
  mkdir -p /opt/nanobot
  mount "$DATA_DEVICE" /opt/nanobot
  # Persist across reboots
  UUID=$(blkid -s UUID -o value "$DATA_DEVICE")
  echo "UUID=$UUID /opt/nanobot ext4 defaults,nofail 0 2" >> /etc/fstab
  echo "Data volume mounted at /opt/nanobot"
fi

# ── Swap file (2GB) — covers Playwright/Chromium memory spikes on t3.micro ────
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "Swap enabled: $(swapon --show)"
fi

# ── Install Docker ─────────────────────────────────────────────────────────────
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
echo "Docker installed: $(docker --version)"

# ── Clone repo ────────────────────────────────────────────────────────────────
REPO_DIR="/opt/nanobot-app"
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone --branch "${repo_branch}" "${repo_url}" "$REPO_DIR"
  echo "Repo cloned to $REPO_DIR"
else
  echo "Repo already exists, pulling latest..."
  git -C "$REPO_DIR" pull
fi

# ── Create /opt/nanobot structure + default config ────────────────────────────
NANOBOT_DATA="/opt/nanobot"
mkdir -p "$NANOBOT_DATA"/{logs,workspace/screenshots,sessions,memory}
mkdir -p "$NANOBOT_DATA"/workspace/skills/{review,travel-research,trip-mapper,google-calendar,australian-news,memory,ping-test,recommendation-enhancement,reddit-api-access}

if [ ! -f "$NANOBOT_DATA/config.json" ]; then
  cat > "$NANOBOT_DATA/config.json" << 'CONFIG_EOF'
{
  "agents": {
    "defaults": {
      "workspace": "/root/.nanobot/workspace",
      "model": "google/gemini-3-flash-preview",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20
    }
  },
  "channels": {
    "web": { "enabled": true, "port": 18791, "allowFrom": [] },
    "telegram": { "enabled": false, "token": "", "allowFrom": [] },
    "whatsapp": { "enabled": false, "bridgeUrl": "ws://nanobot-whatsapp-bridge:3002", "bridgeToken": "", "allowFrom": [] }
  },
  "providers": {
    "openrouter": { "apiKey": "REPLACE_WITH_OPENROUTER_KEY" }
  },
  "gateway": { "host": "0.0.0.0", "port": 18790 },
  "tools": {
    "web": { "search": { "provider": "tavily", "tavilyApiKey": "REPLACE_WITH_TAVILY_KEY", "maxResults": 5 } },
    "exec": { "timeout": 600 },
    "restrictToWorkspace": false,
    "google": { "mapsApiKey": "" },
    "mcpServers": {
      "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
    }
  }
}
CONFIG_EOF
fi

# Give ubuntu ownership so GitHub Actions can write without sudo
chown -R ubuntu:ubuntu "$NANOBOT_DATA"

echo ""
echo "=== Setup complete ==="
echo "Next: SSH in and edit /opt/nanobot/config.json to add your API keys"
echo "Then: cd $REPO_DIR && docker compose up -d"
