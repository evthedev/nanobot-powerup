#!/usr/bin/env python3
"""Write deploy secrets to /tmp/nanobot_secrets.json on the Actions runner.
Called by deploy.yml before scp-ing the file to EC2.
Reading from env vars here (on the runner) is safe — no SSH shell involved."""
import json
import os

secrets = {
    "GROK_API_KEY":               os.environ.get("GROK_API_KEY", ""),
    "OPENROUTER_API_KEY":         os.environ.get("OPENROUTER_API_KEY", ""),
    "NVIDIA_API_KEY":             os.environ.get("NVIDIA_API_KEY", ""),
    "BRAVE_API_KEY":              os.environ.get("BRAVE_API_KEY", ""),
    "TAVILY_API_KEY":             os.environ.get("TAVILY_API_KEY", ""),
    "GOOGLE_STATIC_MAPS_API_KEY": os.environ.get("GOOGLE_STATIC_MAPS_API_KEY", ""),
    "GOOGLE_CLIENT_ID":           os.environ.get("GOOGLE_CLIENT_ID", ""),
    "GOOGLE_CLIENT_SECRET":       os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    "TELEGRAM_BOT_TOKEN":         os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "BRIDGE_TOKEN":               os.environ.get("BRIDGE_TOKEN", ""),
    "WHATSAPP_ALLOW_FROM":        os.environ.get("WHATSAPP_ALLOW_FROM", ""),
    "CAPSOLVER_API_KEY":          os.environ.get("CAPSOLVER_API_KEY", ""),
    "GMAIL_EMAIL":                os.environ.get("GMAIL_EMAIL", ""),
    "GMAIL_APP_PASSWORD":         os.environ.get("GMAIL_APP_PASSWORD", ""),
    "GITHUB_TOKEN":               os.environ.get("GH_PAT", ""),
    "GITHUB_REPO":                os.environ.get("GH_REPO", ""),
}

out = "/tmp/nanobot_secrets.json"
with open(out, "w") as f:
    json.dump(secrets, f)
print(f"secrets written to {out}")
