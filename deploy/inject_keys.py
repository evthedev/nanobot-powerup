#!/usr/bin/env python3
"""Inject secrets into /opt/nanobot/config.json on the EC2 instance.

Usage:
  python3 inject_keys.py --secrets /tmp/nanobot_secrets.json   # preferred
  python3 inject_keys.py                                        # fallback: env vars
"""
import json
import os
import sys


def set_nested(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


cfg_path = "/opt/nanobot/config.json"
with open(cfg_path) as f:
    cfg = json.load(f)

_src: dict = {}
if "--secrets" in sys.argv:
    secrets_path = sys.argv[sys.argv.index("--secrets") + 1]
    with open(secrets_path) as f:
        _src = json.load(f)
    print(f"  reading secrets from {secrets_path}")


def _get(key: str) -> str:
    return _src.get(key, os.environ.get(key, "")).strip()


grok_api_key          = _get("GROK_API_KEY")
nvidia_api_key        = _get("NVIDIA_API_KEY")
openrouter_key        = _get("OPENROUTER_API_KEY")
brave_key             = _get("BRAVE_API_KEY")
tavily_key            = _get("TAVILY_API_KEY")
maps_key              = _get("GOOGLE_STATIC_MAPS_API_KEY")
telegram_token        = _get("TELEGRAM_BOT_TOKEN")
bridge_token          = _get("BRIDGE_TOKEN")
whatsapp_allow_from   = _get("WHATSAPP_ALLOW_FROM")
reachy_bridge_enabled = _get("REACHY_BRIDGE_ENABLED").lower() in ("1", "true", "yes")
bridge_secret         = _get("BRIDGE_SECRET")
google_client_id      = _get("GOOGLE_CLIENT_ID")
google_client_secret  = _get("GOOGLE_CLIENT_SECRET")
capsolver_api_key     = _get("CAPSOLVER_API_KEY")
gmail_email           = _get("GMAIL_EMAIL")
gmail_app_password    = _get("GMAIL_APP_PASSWORD")
github_token          = _get("GITHUB_TOKEN")
github_repo           = _get("GITHUB_REPO")
nanobot_env_name      = _get("NANOBOT_ENV_NAME")

if grok_api_key and not grok_api_key.startswith("REPLACE"):
    set_nested(cfg, "providers.grok.apiKey", grok_api_key)
    print(f"  grok key set ({len(grok_api_key)} chars)")

if nvidia_api_key and not nvidia_api_key.startswith("REPLACE"):
    set_nested(cfg, "providers.nvidia.apiKey", nvidia_api_key)
    print(f"  nvidia key set ({len(nvidia_api_key)} chars)")

if openrouter_key and not openrouter_key.startswith("REPLACE"):
    set_nested(cfg, "providers.openrouter.apiKey", openrouter_key)
    print(f"  openrouter key set ({len(openrouter_key)} chars)")

if tavily_key and not tavily_key.startswith("REPLACE"):
    set_nested(cfg, "tools.web.search.provider", "tavily")
    set_nested(cfg, "tools.web.search.tavilyApiKey", tavily_key)
    print(f"  tavily key set ({len(tavily_key)} chars)")
elif brave_key and not brave_key.startswith("REPLACE"):
    set_nested(cfg, "tools.web.search.apiKey", brave_key)
    print("  brave key set (tavily not provided, using brave)")

if maps_key and not maps_key.startswith("REPLACE"):
    set_nested(cfg, "tools.google.mapsApiKey", maps_key)
    print(f"  google maps key set ({len(maps_key)} chars)")

if telegram_token and not telegram_token.startswith("REPLACE"):
    set_nested(cfg, "channels.telegram.enabled", True)
    set_nested(cfg, "channels.telegram.token", telegram_token)
    print(f"  telegram token set, bot enabled")

if bridge_token or whatsapp_allow_from:
    set_nested(cfg, "channels.whatsapp.enabled", True)
    set_nested(cfg, "channels.whatsapp.bridge_url", "ws://nanobot-whatsapp-bridge:3002")
    if bridge_token and not bridge_token.startswith("REPLACE"):
        set_nested(cfg, "channels.whatsapp.bridge_token", bridge_token)
    if whatsapp_allow_from:
        allow_list = [n.strip() for n in whatsapp_allow_from.split(",") if n.strip()]
        set_nested(cfg, "channels.whatsapp.allow_from", allow_list)
    print(f"  whatsapp channel enabled")

if reachy_bridge_enabled:
    set_nested(cfg, "channels.reachyBridge.enabled", True)
    set_nested(cfg, "channels.reachyBridge.url", "http://nanobot-whatsapp-bridge:18790")
    if bridge_secret:
        set_nested(cfg, "channels.reachyBridge.secret", bridge_secret)
    print("  reachy bridge enabled")

if google_client_id and not google_client_id.startswith("REPLACE"):
    set_nested(cfg, "tools.google_calendar.clientId", google_client_id)
    print(f"  google client ID set")

if google_client_secret and not google_client_secret.startswith("REPLACE"):
    set_nested(cfg, "tools.google_calendar.clientSecret", google_client_secret)
    print(f"  google client secret set")

if capsolver_api_key and not capsolver_api_key.startswith("REPLACE"):
    set_nested(cfg, "tools.capsolver.api_key", capsolver_api_key)
    print(f"  capsolver key set ({len(capsolver_api_key)} chars)")

if gmail_email and not gmail_email.startswith("REPLACE"):
    set_nested(cfg, "tools.gmail.email", gmail_email)
    print(f"  gmail email set ({gmail_email})")

if gmail_app_password and not gmail_app_password.startswith("REPLACE"):
    set_nested(cfg, "tools.gmail.app_password", gmail_app_password)
    print(f"  gmail app_password set ({len(gmail_app_password)} chars)")

if github_token and not github_token.startswith("REPLACE"):
    set_nested(cfg, "tools.github.token", github_token)
    print(f"  github token set ({len(github_token)} chars)")

if github_repo and not github_repo.startswith("REPLACE"):
    set_nested(cfg, "tools.github.repo", github_repo)
    print(f"  github repo set ({github_repo})")

if nanobot_env_name and not nanobot_env_name.startswith("REPLACE"):
    set_nested(cfg, "runtime.environment_name", nanobot_env_name)
    print(f"  runtime environment set ({nanobot_env_name})")

if not cfg.get("agents", {}).get("defaults", {}).get("model"):
    set_nested(cfg, "agents.defaults.model", "google/gemini-3-flash-preview")
    print("  agent model: google/gemini-3-flash-preview (default)")

set_nested(cfg, "ssl_verify", False)
print("  ssl_verify: False (bypass corporate proxy cert)")

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

print("config.json updated.")
