# nanobot-powerup

This is the nanobot-powerup repository — the infrastructure and application stack for the nanobot AI assistant.

## Repo structure

- `nanobot/` — Python gateway (AI agent, cron, channels: Telegram, WhatsApp, web, edge devices)
- `bridge/` — TypeScript WhatsApp/edge bridge service
- `dashboard/` — React + Express chat dashboard
- `deploy/` — Nginx config, Terraform, CI/CD scripts
- `workspace/` — Agent workspace files synced to `/opt/nanobot/workspace` on deploy
- `.github/workflows/deploy.yml` — GitHub Actions: Terraform provision + Docker deploy to EC2

## Environments

| Name       | AWS region      | EC2 instance         |
|------------|-----------------|----------------------|
| clyde      | ap-southeast-2  | i-04a3f10548f4f97f0  |
| shantelle  | ap-southeast-2  | i-05be7ee8db89f4571  |

## Deploy

Push to `main` → GitHub Actions provisions infra (Terraform) and deploys via SSH.
**Never deploy directly to EC2.** All changes go through git → GitHub Actions.

## Stack

All services run as Docker containers managed by `docker-compose.yml`:

- `nanobot-gateway` — AI agent process (Python)
- `nanobot-dashboard` — chat UI (Express API + React, port 3001)
- `nanobot-whatsapp-bridge` — WhatsApp + edge device bridge (Node, port 3002/18790)
- `nanobot-nginx` — reverse proxy, HTTPS, basic auth (ports 80/443)
- `nanobot-claude` — Claude Code web terminal at `/claude` (ttyd, port 7681)

Persistent state lives on the host at `/opt/nanobot/` (mounted into containers as `/root/.nanobot/`).
The repo itself is cloned at `/opt/nanobot-app/` and mounted into `nanobot-claude` as `/workspace`.

## Secrets

Secrets are stored as GitHub Actions environment secrets (per environment: clyde / shantelle).
They are injected into `config.json` at deploy time via `deploy/inject_keys.py`.
`ANTHROPIC_API_KEY` is written to `.env.docker` and passed to the `claude-terminal` container.
