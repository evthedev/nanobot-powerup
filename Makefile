VENV = .venv
BIN  = $(VENV)/bin

.PHONY: setup sync-workspace sync-skills up down restart restart-gateway restart-dashboard logs logs-dashboard \
        status shell venv-clean help

# Default target
help:
	@echo "Nanobot Local Control"
	@echo "=================================="
	@echo "  make setup              - Run interactive local setup (creates venv)"
	@echo "  make sync-workspace     - Sync all workspace files (docs + skills) from repo to ~/.nanobot"
	@echo "  make sync-skills        - Re-sync base skills only from repo to ~/.nanobot"
	@echo "  make up                 - Start all containers (gateway, dashboard, nginx, WhatsApp bridge)"
	@echo "  make down               - Stop all containers"
	@echo "  make restart            - Restart all services"
	@echo ""
	@echo "  Dev workflow (no rebuild needed):"
	@echo "  make restart-gateway    - Reload Python changes instantly"
	@echo "  make restart-dashboard  - Reload Express server changes instantly"
	@echo "    (React client reloads automatically via HMR on port 3000)"
	@echo ""
	@echo "  make logs               - Follow gateway logs"
	@echo "  make logs-dashboard     - Follow dashboard server logs"
	@echo "  make logs-client        - Follow React dev server logs"
	@echo "  make status             - Show container status"
	@echo "  make shell              - Drop into gateway shell"
	@echo "  make venv-clean         - Delete the virtual environment"

setup:
	@python3 setup-local.py

sync-workspace:
	@echo "Syncing workspace docs → ~/.nanobot/workspace/ ..."
	@rsync -a --exclude=skills/ --exclude=HEARTBEAT.md --exclude=USER.md --exclude=memory/ ./workspace/ ~/.nanobot/workspace/
	@echo "Syncing base skills → ~/.nanobot/workspace/skills/ ..."
	@rsync -a --delete ./workspace/skills/ ~/.nanobot/workspace/skills/
	@echo "Done."

sync-skills:
	@echo "Syncing base skills → ~/.nanobot/workspace/skills/ ..."
	@rsync -av --delete ./workspace/skills/ ~/.nanobot/workspace/skills/
	@echo "Done."

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

# Instant reload — picks up ./nanobot/** changes via PYTHONPATH volume mount
restart-gateway:
	docker compose restart nanobot-gateway

# Instant reload — node --watch detects index.js changes automatically,
# but use this if you want to force a restart.
restart-dashboard:
	docker compose restart dashboard

logs:
	docker compose logs -f nanobot-gateway

logs-dashboard:
	docker compose logs -f dashboard

logs-client:
	docker compose logs -f dashboard-client

status:
	docker compose ps

shell:
	docker compose exec nanobot-gateway /bin/bash

venv-clean:
	rm -rf $(VENV)
