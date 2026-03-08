#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-time bootstrap: run once per AWS account / GitHub environment.
#
# Prerequisites: terraform, gh (GitHub CLI), AWS credentials in env or ~/.aws
#
# Usage:
#   GITHUB_ENV=clyde   AWS_REGION=ap-southeast-2 PROJECT_NAME=nanobot           bash deploy/bootstrap.sh
#   GITHUB_ENV=shantelle AWS_REGION=us-east-1    PROJECT_NAME=nanobot-shantelle bash deploy/bootstrap.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

GITHUB_ENV="${GITHUB_ENV:?Set GITHUB_ENV to the GitHub environment name (e.g. clyde)}"
AWS_REGION="${AWS_REGION:-ap-southeast-2}"
PROJECT_NAME="${PROJECT_NAME:-nanobot}"
BOOTSTRAP_DIR="deploy/terraform/bootstrap"
STATE_DIR="$(pwd)/deploy/terraform/bootstrap/state"
mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/${GITHUB_ENV}.tfstate"

echo "=== bootstrap: $GITHUB_ENV ==="
echo "  AWS_REGION:   $AWS_REGION"
echo "  PROJECT_NAME: $PROJECT_NAME"
echo ""

# ── Run bootstrap Terraform ───────────────────────────────────────────────────
terraform -chdir="$BOOTSTRAP_DIR" init -backend-config="path=$STATE_FILE" -reconfigure

terraform -chdir="$BOOTSTRAP_DIR" apply -auto-approve \
  -var="aws_region=$AWS_REGION" \
  -var="project_name=$PROJECT_NAME"

# ── Read outputs ──────────────────────────────────────────────────────────────
STATE_BUCKET=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket)
ACCESS_KEY_ID=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw aws_access_key_id)
SECRET_KEY=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw aws_secret_access_key)
KEY_PAIR_NAME=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw ec2_key_pair_name)
SSH_KEY=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw ec2_ssh_key)

# ── Set GitHub environment secrets/variables ──────────────────────────────────
GITHUB_REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

echo "Setting GitHub secrets for environment: $GITHUB_ENV"
gh secret set AWS_ACCESS_KEY_ID     --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$ACCESS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$SECRET_KEY"
gh secret set TF_STATE_BUCKET       --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$STATE_BUCKET"
gh secret set EC2_KEY_PAIR_NAME     --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$KEY_PAIR_NAME"
gh secret set EC2_SSH_KEY           --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$SSH_KEY"
gh variable set AWS_REGION          --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$AWS_REGION"
gh variable set PROJECT_NAME        --repo "$GITHUB_REPO" --env "$GITHUB_ENV" --body "$PROJECT_NAME"

echo ""
echo "=== Bootstrap complete for $GITHUB_ENV ==="
echo "Bootstrap state saved to: $STATE_FILE"
echo "WARNING: state contains secrets — do NOT commit it. Back it up securely (e.g. encrypted storage)."
