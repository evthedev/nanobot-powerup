#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import shutil
import socket
from pathlib import Path

def print_banner(text):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)

def run_command(cmd, cwd=None, env=None, check=True):
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, env=env, check=check)

def set_nested(d, path, value):
    if not value:
        return
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value

def check_port(port):
    """Check if a port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) != 0

def check_binaries():
    print("\n[1/8] Checking for required binaries...")
    required = {
        "python3": "Python 3 is required.",
        "node": "Node.js is required (for dashboard and bridge).",
        "npm": "npm is required.",
        "docker": "Docker is required.",
        "git": "Git is required.",
        "rsync": "rsync is required for syncing workspace skills."
    }
    missing = []
    for bin_name, msg in required.items():
        if shutil.which(bin_name) is None:
            missing.append(f"- {bin_name}: {msg}")
    
    if missing:
        print("\n❌ Missing required binaries:")
        print("\n".join(missing))
        print("\nPlease install these and try again.")
        sys.exit(1)
    
    # Check for docker
    if shutil.which("docker") is None:
        print("❌ 'docker' binary not found. Please install Docker.")
        sys.exit(1)

    # Check for docker compose plugin
    try:
        subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
        print("✓ docker compose plugin found.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 'docker compose' (V2) is not installed. Please install the Docker Compose plugin.")
        sys.exit(1)
    
    # Check if docker daemon is reachable (warning only)
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
        print("✓ Docker daemon is reachable.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("! Warning: Could not connect to Docker daemon. Ensure Docker is running.")
        print("  (Setup will continue, but 'make up' may fail later if Docker is not started.)")
    
    # Check for required project files
    htpasswd_path = Path("deploy/nginx/.htpasswd")
    if not htpasswd_path.exists():
        print(f"\n! Warning: {htpasswd_path} not found.")
        print("  Nginx basic auth will fail. Creating a default (nanobot:nanobot)...")
        htpasswd_path.parent.mkdir(parents=True, exist_ok=True)
        with open(htpasswd_path, "w") as f:
            # Default hash for 'nanobot' password
            f.write("nanobot:$apr1$ZBa6rtlb$3WxH2ON28ahB9oKu6M5nK0\n")
    
    print("✓ Basic system and project checks passed.")

def main():
    print_banner("Nanobot Local Setup (Docker Edition)")

    # 1. Check binaries
    check_binaries()

    # 2. Check ports
    print("\n[2/8] Checking for port availability...")
    ports_to_check = {3001: "Dashboard Backend", 18790: "Gateway API", 18791: "WebSocket Channel"}
    for port, label in ports_to_check.items():
        if not check_port(port):
            print(f"❌ Port {port} ({label}) is already in use. Please stop the conflicting service.")
            sys.exit(1)
    print("✓ Ports 3001, 18790, 18791 are available.")

    # 3. Create Virtual Environment
    print("\n[3/8] Creating virtual environment...")
    uv_available = shutil.which("uv") is not None
    
    if uv_available:
        print("✓ uv found, using it for faster installs.")
        run_command(["uv", "venv", ".venv"])
        python_bin = str(Path(".venv/bin/python"))
        pip_cmd = ["uv", "pip"]
    else:
        print("! uv not found, falling back to standard venv.")
        run_command([sys.executable, "-m", "venv", ".venv"])
        python_bin = str(Path(".venv/bin/python"))
        pip_cmd = [python_bin, "-m", "pip"]

    # 4. Install package in editable mode
    print("\n[4/8] Installing nanobot package in venv...")
    run_command([*pip_cmd, "install", "-e", ".[dev]"])

    # 5. Scaffold config and workspace
    print("\n[5/8] Scaffolding configuration...")
    run_command([python_bin, "-m", "nanobot", "onboard"])

    config_path = Path.home() / ".nanobot" / "config.json"
    workspace_path = Path.home() / ".nanobot" / "workspace"

    # 6. Configure config.json
    print("\n[6/8] Configuring nanobot settings...")
    with open(config_path) as f:
        cfg = json.load(f)

    print("\nPlease enter your API keys (leave blank to skip):")
    
    # LLM Providers
    print("\n--- LLM Providers ---")
    print("  Priority: Grok (xAI) → NVIDIA NIM → OpenRouter")
    grok_key = input("  Grok (xAI) API Key (xai-...): ").strip()
    nvidia_key = input("  NVIDIA NIM API Key (nvapi-...): ").strip()
    openrouter_key = input("  OpenRouter API Key (sk-or-v1-...): ").strip()
    
    # Tools
    print("\n--- Tools & Search ---")
    tavily_key = input("  Tavily API Key (tvly-...): ").strip()
    brave_key = input("  Brave Search API Key: ").strip()
    maps_key = input("  Google Static Maps API Key (for trip-mapper): ").strip()
    
    # Telegram
    print("\n--- Telegram (Optional: chat with nanobot via Telegram) ---")
    print("  1. Message @BotFather on Telegram")
    print("  2. Send /newbot and follow the prompts")
    print("  3. Copy the bot token it gives you (format: 123456789:ABC...)")
    telegram_token = input("  Telegram Bot Token: ").strip()

    # WhatsApp
    print("\n--- WhatsApp (Optional: monitor & summarise to Telegram) ---")
    print("  The bridge runs in Docker. Provide a shared token for auth (recommended).")
    print("  Allowed numbers: comma-separated, no + (e.g. 61401234567,61498765432)")
    whatsapp_bridge_token = input("  WhatsApp Bridge Token (leave blank to skip): ").strip()
    whatsapp_allowed = input("  Allowed phone numbers: ").strip()

    # Google OAuth (for Calendar)
    print("\n--- Google OAuth (Optional: for Calendar integration) ---")
    print("  Note: You must add 'http://localhost:3001/api/google/auth/callback' to ")
    print("  Authorized Redirect URIs in your Google Cloud Console.")
    google_client_id = input("  Google Client ID: ").strip()
    google_client_secret = input("  Google Client Secret: ").strip()

    # Gmail (App Password)
    print("\n--- Gmail App Password (Optional: for sending emails) ---")
    print("  Generate one at: Google Account → Security → App passwords")
    gmail_email = input("  Gmail Address: ").strip()
    gmail_app_password = input("  Gmail App Password (16 chars): ").strip()

    # Capsolver
    print("\n--- Capsolver (Optional: for CAPTCHA solving in stealth-browser) ---")
    capsolver_api_key = input("  Capsolver API Key: ").strip()

    # Apply defaults/provided values
    set_nested(cfg, "providers.grok.apiKey", grok_key)
    set_nested(cfg, "providers.nvidia.apiKey", nvidia_key)
    set_nested(cfg, "providers.openrouter.apiKey", openrouter_key)
    
    # Search Prioritization: Tavily > Brave
    if tavily_key:
        set_nested(cfg, "tools.web.search.provider", "tavily")
        set_nested(cfg, "tools.web.search.tavilyApiKey", tavily_key)
        if brave_key:
            set_nested(cfg, "tools.web.search.apiKey", brave_key)
    elif brave_key:
        set_nested(cfg, "tools.web.search.provider", "brave")
        set_nested(cfg, "tools.web.search.apiKey", brave_key)
    
    set_nested(cfg, "tools.google.mapsApiKey", maps_key)
    # Google OAuth credentials — stored under tools.google_calendar
    # Tokens are written here by the dashboard OAuth flow.
    set_nested(cfg, "tools.google_calendar.clientId", google_client_id)
    set_nested(cfg, "tools.google_calendar.clientSecret", google_client_secret)
    # Gmail (App Password SMTP)
    set_nested(cfg, "tools.gmail.email", gmail_email)
    set_nested(cfg, "tools.gmail.app_password", gmail_app_password)
    # Capsolver
    set_nested(cfg, "tools.capsolver.api_key", capsolver_api_key)
    
    # Telegram
    if telegram_token:
        set_nested(cfg, "channels.telegram.enabled", True)
        set_nested(cfg, "channels.telegram.token", telegram_token)
        print("  ✓ Telegram bot token set, channel enabled.")

    # WhatsApp (bridge runs in Docker; gateway connects to ws://nanobot-whatsapp-bridge:3002)
    if whatsapp_bridge_token or whatsapp_allowed:
        set_nested(cfg, "channels.whatsapp.enabled", True)
        set_nested(cfg, "channels.whatsapp.bridge_url", "ws://nanobot-whatsapp-bridge:3002")
        if whatsapp_bridge_token:
            set_nested(cfg, "channels.whatsapp.bridge_token", whatsapp_bridge_token)
        if whatsapp_allowed:
            allow_list = [n.strip() for n in whatsapp_allowed.split(",") if n.strip()]
            set_nested(cfg, "channels.whatsapp.allow_from", allow_list)
        print("  ✓ WhatsApp channel enabled (bridge runs with make up).")
    
    # Core system settings
    set_nested(cfg, "channels.web.enabled", True)
    set_nested(cfg, "channels.web.port", 18791)
    
    # Model Selection & Prioritization
    # Priority 1: Grok (xAI)
    if grok_key:
        print("  ✓ Grok (xAI) provided. Setting as primary provider.")
        set_nested(cfg, "agents.defaults.model", "grok-3-mini")
        set_nested(cfg, "agents.defaults.smart_model", "grok-3")
    # Priority 2: NVIDIA NIM
    elif nvidia_key:
        print("  ✓ NVIDIA NIM provided. Setting as primary provider.")
        # Llama 3.3 70B has much better tool-calling than 3.1 70B at the same speed.
        set_nested(cfg, "agents.defaults.model", "nvidia_nim/meta/llama-3.3-70b-instruct")
        # Llama 3.1 405B is the most capable model on NIM, used for smart subagents.
        set_nested(cfg, "agents.defaults.smart_model", "nvidia_nim/meta/llama-3.1-405b-instruct")
    # Priority 3: OpenRouter
    elif openrouter_key:
        print("  ✓ OpenRouter provided. Setting as primary provider.")
        set_nested(cfg, "agents.defaults.model", "google/gemini-3-flash-preview")
        set_nested(cfg, "agents.defaults.smart_model", "anthropic/claude-3.5-sonnet")
    else:
        print("  ! No LLM keys provided. You will need to add one to ~/.nanobot/config.json before running.")

    # Setup MCP for Playwright
    set_nested(cfg, "tools.mcpServers.playwright", {
        "command": "npx",
        "args": ["@playwright/mcp@latest", "--output-dir", "/root/.nanobot/workspace/screenshots"]
    })

    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"Updated {config_path}")

    # 7. Sync workspace files (docs, heartbeat, etc.) then base skills with --delete
    print("\n[7/8] Syncing workspace files and skills...")
    local_workspace = Path(__file__).parent / "workspace"
    # Sync non-skills workspace files (AGENTS.md, SOUL.md, etc.) without --delete
    # so runtime-only dirs (memory/, screenshots/, sessions/) are preserved.
    run_command(["rsync", "-a", "--exclude=skills/", str(local_workspace) + "/", str(workspace_path) + "/"])
    # Sync base skills with --delete so renamed/removed skills don't linger at runtime.
    local_skills = local_workspace / "skills"
    runtime_skills = workspace_path / "skills"
    runtime_skills.mkdir(parents=True, exist_ok=True)
    run_command(["rsync", "-a", "--delete", str(local_skills) + "/", str(runtime_skills) + "/"])

    # 8. Generate docker-compose.override.yml
    print("\n[8/8] Generating docker-compose.override.yml...")
    nanobot_home = Path.home() / ".nanobot"
    override_content = f"""services:

  # ── Python gateway ───────────────────────────────────────────────────────
  # ./nanobot is mounted live; PYTHONPATH=/app makes Python prefer it over the
  # installed package. `docker compose restart nanobot-gateway` picks up any
  # Python source change instantly — no image rebuild required.
  nanobot-gateway:
    volumes:
      - {nanobot_home}:/root/.nanobot
      - ./nanobot:/app/nanobot          # live source mount
    environment:
      - PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
      - PLAYWRIGHT_BROWSERS_PATH=/usr/bin
      - PYTHONPATH=/app                 # /app/nanobot shadows the installed pkg

  # ── WhatsApp bridge (needs ~/.nanobot for auth on Mac; base uses /opt/nanobot) ─
  nanobot-whatsapp-bridge:
    volumes:
      - {nanobot_home}:/root/.nanobot

  # ── Express API server ─────────────────────────────────────────────────────
  # index.js is mounted live; node --watch auto-restarts on every save.
  # No image rebuild needed for server-side changes.
  dashboard:
    volumes:
      - {nanobot_home}:/root/.nanobot
      - ./dashboard/server/index.js:/app/index.js   # live server mount
    command: ["node", "--watch", "index.js"]
    ports:
      - "3001:3001"

  # ── React dev server (HMR) ─────────────────────────────────────────────────
  # Runs CRA's dev server with hot-module replacement on port 3000.
  # /api calls are proxied to the Express container via setupProxy.js.
  # Access the UI at http://localhost:3000 during development.
  dashboard-client:
    image: node:20-alpine
    working_dir: /app
    volumes:
      - ./dashboard/client:/app
      - client_node_modules:/app/node_modules   # isolate container node_modules
    command: sh -c "npm install --silent && npm start"
    ports:
      - "3000:3000"
    environment:
      - CHOKIDAR_USEPOLLING=true        # required for inotify through Docker on macOS
      - PROXY_TARGET=http://nanobot-dashboard:3001
      - WDS_SOCKET_HOST=localhost
      - WDS_SOCKET_PORT=3000
    depends_on:
      - dashboard

volumes:
  client_node_modules:
"""
    override_path = Path(__file__).parent / "docker-compose.override.yml"
    with open(override_path, "w") as f:
        f.write(override_content)
    print(f"Created {override_path}")

    print_banner("Setup Complete!")
    print("\nStart all services:")
    print("  make up")
    print("\nDev access:")
    print("  http://localhost:3000  — React dev server (HMR, instant UI changes)")
    print("  http://localhost:3001  — Express API (auto-restarts on server saves)")
    print("\nPython changes (gateway):")
    print("  Edit nanobot/ then: make restart-gateway")
    print("\nLogs:")
    print("  make logs              — gateway logs")
    print("  make logs-dashboard    — dashboard server logs")
    print("\nEnjoy your nanobot!")

if __name__ == "__main__":
    main()
