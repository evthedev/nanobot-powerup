#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install.sh — NanoBot integration for Reachy Mini
#
# Run this on the Reachy RPi:
#   bash install.sh
#
# What it does:
#   1. Writes call_nanobot.py to external_content/external_tools/
#   2. Appends NanoBot env vars to .env (idempotent)
#   3. Checks httpx is available in the venv
#   4. Smoke-tests the NanoBot endpoint
#
# Approach — AUTOLOAD_EXTERNAL_TOOLS:
#   call_nanobot is injected as an additional tool into Reachy's existing
#   active profile. No profile override, no instructions change, no
#   personality change — Reachy stays exactly as it was.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✖${NC}  $*"; exit 1; }
step() { echo -e "\n${BOLD}▶ $*${NC}"; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════╗"
echo "║   Reachy Mini — NanoBot integration installer   ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Constants ─────────────────────────────────────────────────────────────────
APP_DIR="$HOME/reachy_mini_conversation_app"
TOOLS_DIR="$APP_DIR/external_content/external_tools"
ENV_FILE="$APP_DIR/.env"
VENV="$APP_DIR/.venv"

NANOBOT_CHAT_URL="https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/chat/e8e2007c-9a8c-47b5-a90e-4cbb83449f7f"
NANOBOT_AUTH="nanobot:Nb9kQmX3pL7!"
NANOBOT_TIMEOUT="30"

# ── Step 0: preflight ─────────────────────────────────────────────────────────
step "Preflight checks"

[[ -d "$APP_DIR" ]] || fail "$APP_DIR not found — is reachy_mini_conversation_app installed?"
ok "Found $APP_DIR"

[[ -f "$ENV_FILE" ]] || { warn ".env not found — creating empty one"; touch "$ENV_FILE"; }
ok "Found .env"

# ── Step 1: directory ─────────────────────────────────────────────────────────
step "Creating external_tools directory"

mkdir -p "$TOOLS_DIR"
ok "external_content/external_tools/"

# ── Step 2: write call_nanobot.py ─────────────────────────────────────────────
step "Writing call_nanobot.py"

cat > "$TOOLS_DIR/call_nanobot.py" << 'PYEOF'
"""
NanoBot bridge tool for Reachy Mini.

Deployed to: ~/reachy_mini_conversation_app/external_content/external_tools/call_nanobot.py

Loaded via AUTOLOAD_EXTERNAL_TOOLS=1 — injected into Reachy's active profile
without overriding its instructions, personality, or tool list.

Follows the same pattern as the official pollen-robotics starter example:
  external_content/external_tools/starter_custom_tool.py
  https://github.com/pollen-robotics/reachy_mini_conversation_app

Required .env entries (add to ~/reachy_mini_conversation_app/.env):
    NANOBOT_CHAT_URL   The /chat/<id> URL from your browser, e.g.
                       https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/chat/e8e2007c-...
    NANOBOT_AUTH       Basic-auth credentials in "username:password" form, e.g. nanobot:secret
    NANOBOT_TIMEOUT    (optional) seconds to wait for NanoBot. Default: 30
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_CHAT_URL: str = os.environ.get("NANOBOT_CHAT_URL", "").rstrip("/")
_TIMEOUT_S: float = float(os.environ.get("NANOBOT_TIMEOUT", "30"))
_CHAT_URL_RE = re.compile(r"^(https?://[^/]+)/chat/([^/?#]+)$")

_raw_auth = os.environ.get("NANOBOT_AUTH", "")
_AUTH: tuple[str, str] | None = tuple(_raw_auth.split(":", 1)) if ":" in _raw_auth else None  # type: ignore[assignment]


def _api_url() -> str | None:
    """Derive POST /api/conversations/:id/messages from the /chat/:id browser URL."""
    m = _CHAT_URL_RE.match(_CHAT_URL)
    if not m:
        return None
    return f"{m.group(1)}/api/conversations/{m.group(2)}/messages"


class CallNanobot(Tool):
    """Bridge to NanoBot — Ev's cloud AI agent."""

    name = "call_nanobot"
    description = (
        "Send a request to NanoBot, Ev's personal AI agent running in the cloud. "
        "Use this for calendar events, reminders, email, WhatsApp messages, "
        "memory of past conversations, web searches, and any task requiring "
        "persistent knowledge about Ev."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The request to send to NanoBot, in plain English.",
            }
        },
        "required": ["message"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        message: str = kwargs.get("message", "").strip()
        if not message:
            return {"response": "No message was provided to NanoBot."}

        api_url = _api_url()
        if not api_url:
            logger.error("NANOBOT_CHAT_URL is missing or malformed: %r", _CHAT_URL)
            return {
                "response": (
                    "I'm not connected to NanoBot. "
                    "NANOBOT_CHAT_URL is missing or has an unexpected format."
                )
            }

        logger.info("call_nanobot → %s | message: %s", api_url, message[:120])

        try:
            collected: list[str] = []

            async with httpx.AsyncClient(
                timeout=_TIMEOUT_S,
                auth=_AUTH,
                verify=False,
            ) as client:
                async with client.stream(
                    "POST",
                    api_url,
                    json={"content": message},
                    headers={"Accept": "text/event-stream"},
                ) as resp:
                    resp.raise_for_status()

                    async for raw_line in resp.aiter_lines():
                        if not raw_line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(raw_line[6:])
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type")

                        if event_type == "done":
                            content = event.get("content", "").strip()
                            if content:
                                collected.append(content)

                        elif event_type == "stream_end":
                            break

                        elif event_type == "error":
                            err = event.get("error", "unknown error")
                            logger.error("NanoBot error event: %s", err)
                            return {"response": f"NanoBot encountered an error: {err}"}

            if collected:
                response = " ".join(collected)
                logger.info("call_nanobot ← %s", response[:120])
                return {"response": response}

            return {"response": "NanoBot processed the request but returned no response."}

        except httpx.TimeoutException:
            logger.warning("call_nanobot timed out after %ss", _TIMEOUT_S)
            return {"response": "NanoBot is taking too long to respond. Please try again in a moment."}
        except httpx.HTTPStatusError as exc:
            logger.error("call_nanobot HTTP error: %s", exc.response.status_code)
            return {"response": f"NanoBot returned an error: HTTP {exc.response.status_code}."}
        except Exception as exc:  # noqa: BLE001
            logger.exception("call_nanobot unexpected error")
            return {"response": f"I couldn't reach NanoBot: {exc}"}
PYEOF

ok "Wrote $TOOLS_DIR/call_nanobot.py"

# ── Step 3: append .env (idempotent) ─────────────────────────────────────────
step "Updating .env"

append_if_missing() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        warn "${key} already set in .env — skipping"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
        ok "Added ${key}"
    fi
}

# Blank line separator (only if .env is non-empty and doesn't end with blank line)
if [[ -s "$ENV_FILE" ]] && [[ $(tail -c1 "$ENV_FILE" | wc -l) -eq 0 ]]; then
    echo "" >> "$ENV_FILE"
fi

grep -q "NanoBot integration" "$ENV_FILE" 2>/dev/null || \
    echo "# ── NanoBot integration (added by install.sh) ───────────────────────────────" >> "$ENV_FILE"

# AUTOLOAD_EXTERNAL_TOOLS injects call_nanobot into whatever profile is active,
# without overriding instructions, personality, or the existing tool list.
append_if_missing "REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY" "./external_content/external_tools"
append_if_missing "AUTOLOAD_EXTERNAL_TOOLS"              "1"
append_if_missing "NANOBOT_CHAT_URL"                     "$NANOBOT_CHAT_URL"
append_if_missing "NANOBOT_AUTH"                         "$NANOBOT_AUTH"
append_if_missing "NANOBOT_TIMEOUT"                      "$NANOBOT_TIMEOUT"

# ── Step 4: check httpx ───────────────────────────────────────────────────────
step "Checking httpx"

PYTHON="python3"
if [[ -f "$VENV/bin/python" ]]; then
    PYTHON="$VENV/bin/python"
    ok "Using venv Python: $PYTHON"
fi

if "$PYTHON" -c "import httpx" 2>/dev/null; then
    HTTPX_VER=$("$PYTHON" -c "import httpx; print(httpx.__version__)")
    ok "httpx $HTTPX_VER is available"
else
    warn "httpx not found — installing into venv"
    if [[ -f "$VENV/bin/pip" ]]; then
        "$VENV/bin/pip" install --quiet httpx
        ok "httpx installed"
    else
        warn "No venv pip found — trying pip3"
        pip3 install --quiet httpx
        ok "httpx installed via pip3"
    fi
fi

# ── Step 5: smoke test ────────────────────────────────────────────────────────
step "Smoke test — calling NanoBot endpoint"

API_URL="https://ec2-13-54-226-177.ap-southeast-2.compute.amazonaws.com/api/conversations/e8e2007c-9a8c-47b5-a90e-4cbb83449f7f/messages"

if ! command -v curl &>/dev/null; then
    warn "curl not available — skipping smoke test"
else
    echo "  Sending: 'ping' → NanoBot..."
    RESPONSE=$(curl -s -k -m 30 \
        -u "$NANOBOT_AUTH" \
        -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d '{"content": "Reply with just the word pong."}' \
        | grep '"type":"done"' | head -1 || true)

    if [[ -n "$RESPONSE" ]]; then
        CONTENT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.loads(sys.stdin.read().split('data: ',1)[1]); print(d.get('content','')[:120])" 2>/dev/null || echo "(raw) $RESPONSE")
        ok "NanoBot replied: $CONTENT"
    else
        warn "No 'done' event received — NanoBot may be slow or unreachable"
        warn "Check connectivity and try: curl -k -u '$NANOBOT_AUTH' '$API_URL'"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete.${NC}"
echo ""
echo "Files written:"
echo "  $TOOLS_DIR/call_nanobot.py"
echo "  $ENV_FILE  (appended)"
echo ""
echo "Reachy's active profile and personality are unchanged."
echo "call_nanobot is loaded as an additional tool via AUTOLOAD_EXTERNAL_TOOLS=1."
echo ""
echo "To launch:"
echo "  cd $APP_DIR"
echo "  source .venv/bin/activate"
echo "  reachy-mini-conversation-app"
echo ""
echo "Expected startup log line:"
echo "  ✓ Loaded external tool: call_nanobot"
