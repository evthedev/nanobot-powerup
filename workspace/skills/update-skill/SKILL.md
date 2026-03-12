---
name: update-skill
description: Update a promoted (base-layer) skill file at runtime, keep the live copy immediately active, and open or update a GitHub PR to version-control the change.
triggers:
  - "update the skill"
  - "improve the skill"
  - "fix the skill"
  - "edit the skill"
  - "modify the skill"
  - "change the skill"
---

# Update Skill

Updates a base-layer skill (`~/.nanobot/workspace/skills/`) immediately at runtime,
then opens or updates a GitHub PR so the change is version-controlled.

**Always tell the user upfront:** a PR will be created or updated as a result of this action.

---

## Step 0 — Confirm with the user before doing anything

Tell the user:
> "I'm about to update the `<skill>` skill. The live copy will change immediately.
> A GitHub PR will be opened (or updated if one already exists) to version-control this change.
> Your **next deploy will override the live copy** with whatever is in the repo — so the PR must be merged before then to keep this change."

Wait for confirmation unless the user has already explicitly asked you to proceed.

⚠️ **You MUST complete ALL steps in this workflow, including the git push and PR creation in Step 3. Editing the file alone is NOT sufficient. The workflow is not complete until a PR URL has been reported to the user.**

---

## Step 1 — Check PR state before editing

```bash
cd /opt/nanobot-app
git fetch origin
SKILL="<skill-name>"
BRANCH="skill-update/$SKILL"
gh pr list --head "$BRANCH" --json number,url,state,title
```

Use the output to determine which message to show the user (see Messaging Rules below).

---

## Step 2 — Edit the live copy

Edit the file directly:
```
~/.nanobot/workspace/skills/<skill-name>/SKILL.md
```

Use `edit_file` or `write_file`. Make only the changes discussed — do not rewrite unrelated sections.

---

## Step 3 — Copy to repo and push (MANDATORY — do not skip)

First, find the repo root:
```bash
# EC2: repo is at /opt/nanobot-app
# Local dev: repo is mounted from host — find it
REPO_DIR="/opt/nanobot-app"
if [ ! -d "$REPO_DIR/.git" ]; then
  REPO_DIR=$(find /app /root /home -maxdepth 3 -name ".git" -type d 2>/dev/null | head -1 | xargs dirname 2>/dev/null || echo "")
fi
if [ -z "$REPO_DIR" ]; then
  echo "REPO_NOT_FOUND: Cannot locate git repo. Live skill updated but PR skipped."
  exit 1
fi
echo "REPO_DIR=$REPO_DIR"
```

Then run the git/PR steps:
```bash
cd $REPO_DIR
SKILL="<skill-name>"
BRANCH="skill-update/$SKILL"

# Sync live copy → repo copy
cp ~/.nanobot/workspace/skills/$SKILL/SKILL.md workspace/skills/$SKILL/SKILL.md

# Checkout or create the branch
git fetch origin
if git ls-remote --exit-code --heads origin "$BRANCH" > /dev/null 2>&1; then
  git checkout "$BRANCH" && git pull origin "$BRANCH"
else
  git checkout -b "$BRANCH"
fi

git config user.email "nanobot@self-heal"
git config user.name "nanobot"
git add workspace/skills/$SKILL/SKILL.md
git commit -m "skill($SKILL): <one-line reason for this change>"
git push origin "$BRANCH"

# Count commits ahead of main
COMMITS_AHEAD=$(git rev-list --count origin/main.."$BRANCH")

# Open PR only if none exists
PR_URL=$(gh pr list --head "$BRANCH" --json url --jq '.[0].url')
if [ -z "$PR_URL" ]; then
  PR_URL=$(gh pr create \
    --title "Skill update: $SKILL" \
    --body "## What changed
<reason>

## Tested
Live copy already active on EC2. Verify behaviour before merging.

## ⚠️ Deploy note
The next deploy will rsync the repo over the live copy. **Merge this PR before deploying** or the live change will be lost." \
    --base main \
    --head "$BRANCH")
  echo "PR_CREATED:$PR_URL"
else
  echo "PR_UPDATED:$PR_URL COMMITS_AHEAD:$COMMITS_AHEAD"
fi
```

---

## Step 4 — Message the user

Read the output from Step 3 and send the appropriate message (see Messaging Rules).

---

## Messaging Rules

Apply exactly one of these messages based on the situation:

| Situation | Message to user |
|---|---|
| PR created (first edit) | "✅ Live skill updated. A PR has been opened: `<url>` — merge it to version-control this change. ⚠️ Your next deploy will override the live copy if this PR is not merged first." |
| PR updated (subsequent edit) | "✅ Live skill updated. Existing PR `<url>` has been updated — it is now `N` commit(s) ahead of main. ⚠️ Your next deploy will override the live copy if this PR is not merged first." |
| PR exists but was **closed without merging** | "⚠️ Live skill updated. The previous PR was closed without merging — those changes are lost from version control. A new PR has been opened: `<url>`." |
| PR was already **merged** since last edit | "ℹ️ The previous PR was merged. Starting a fresh branch for this edit. New PR: `<url>`." |
| Push fails — branch diverged | "❌ Could not push — the branch has diverged from remote. Live copy is updated but the PR was not. Run this to inspect: `git diff origin/<branch>` inside the gateway container." |
| `gh` not authenticated | "❌ Live skill updated but PR could not be created — `gh` CLI is not authenticated. Run `gh auth login` inside the gateway container or set `GITHUB_TOKEN`." |

---

## Hard rules

- **Never push directly to `main`** — always use the `skill-update/<skill>` branch
- **Never modify `skill.json`** unless the user explicitly asks
- **One branch per skill** — reuse `skill-update/<skill>` across all edits to that skill
- **Live copy first** — always edit the live copy before touching the repo copy, so the change is active immediately even if the git push fails
- **Do not rewrite unrelated sections** — surgical edits only

---

## Requirements

- `gh` CLI is pre-installed in the gateway container
- `GITHUB_TOKEN` is injected automatically from `config.json` via `write_docker_env.py` — no manual setup needed
- `GH_REPO` env var holds the repo slug (e.g. `evthedev/nanobot-powerup`) — used by `gh` automatically
- `/opt/nanobot-app` is the git repo root (standard EC2 layout)
- Verify with: `gh auth status` inside the gateway container
