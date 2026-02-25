#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-time bootstrap: creates the AWS resources that GitHub Actions needs
# before it can run Terraform for the first time.
#
# Run once from your machine (needs AWS CLI + GitHub CLI installed):
#   bash deploy/bootstrap.sh
#
# What it creates:
#   - S3 bucket for Terraform state
#   - EC2 key pair (downloads private key)
#   - IAM user with just enough permissions for Terraform + EC2
#   - Sets all required GitHub secrets/variables automatically
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-ap-southeast-2}"
PROJECT="nanobot"
STATE_BUCKET="${PROJECT}-tf-state-$(aws sts get-caller-identity --query Account --output text)"
KEY_PAIR_NAME="${PROJECT}-key"
IAM_USER="${PROJECT}-ci"
KEY_FILE="$HOME/.ssh/${KEY_PAIR_NAME}.pem"

echo "=== nanobot bootstrap ==="
echo "Region:       $AWS_REGION"
echo "State bucket: $STATE_BUCKET"
echo "Key pair:     $KEY_PAIR_NAME"
echo "IAM user:     $IAM_USER"
echo ""

# ── 1. S3 state bucket ────────────────────────────────────────────────────────
if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  echo "✓ S3 bucket already exists: $STATE_BUCKET"
else
  echo "Creating S3 bucket: $STATE_BUCKET"
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$AWS_REGION"
  else
    aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$AWS_REGION" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION"
  fi
  aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$STATE_BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  echo "✓ S3 bucket created"
fi

# ── 2. EC2 key pair ───────────────────────────────────────────────────────────
if aws ec2 describe-key-pairs --key-names "$KEY_PAIR_NAME" --region "$AWS_REGION" &>/dev/null; then
  echo "✓ Key pair already exists: $KEY_PAIR_NAME"
  if [ ! -f "$KEY_FILE" ]; then
    echo "  WARNING: $KEY_FILE not found locally — you may need to re-create the key pair"
    echo "  Run: aws ec2 delete-key-pair --key-name $KEY_PAIR_NAME --region $AWS_REGION"
    echo "  Then re-run this script."
  fi
else
  echo "Creating EC2 key pair: $KEY_PAIR_NAME"
  aws ec2 create-key-pair \
    --key-name "$KEY_PAIR_NAME" \
    --region "$AWS_REGION" \
    --query 'KeyMaterial' \
    --output text > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "✓ Key pair created, saved to $KEY_FILE"
fi

# ── 3. IAM user for CI ────────────────────────────────────────────────────────
if aws iam get-user --user-name "$IAM_USER" &>/dev/null; then
  echo "✓ IAM user already exists: $IAM_USER"
else
  echo "Creating IAM user: $IAM_USER"
  aws iam create-user --user-name "$IAM_USER"
  # Permissions needed by Terraform: EC2 full + VPC + IAM passrole (for instance profile) + S3 for state
  aws iam attach-user-policy --user-name "$IAM_USER" \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess
  aws iam attach-user-policy --user-name "$IAM_USER" \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
  echo "✓ IAM user created with EC2 + S3 permissions"
fi

# Create access key (always create fresh — show user once)
echo "Creating IAM access key..."
CREDS=$(aws iam create-access-key --user-name "$IAM_USER")
ACCESS_KEY_ID=$(echo "$CREDS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['AccessKey']['AccessKeyId'])")
SECRET_KEY=$(echo "$CREDS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['AccessKey']['SecretAccessKey'])")
echo "✓ Access key created"

# ── 4. Set GitHub secrets/variables ──────────────────────────────────────────
if ! command -v gh &>/dev/null; then
  echo ""
  echo "⚠️  GitHub CLI (gh) not found. Set these GitHub secrets manually:"
  echo ""
  echo "  Secrets (Settings → Secrets → Actions):"
  echo "    AWS_ACCESS_KEY_ID     = $ACCESS_KEY_ID"
  echo "    AWS_SECRET_ACCESS_KEY = $SECRET_KEY"
  echo "    TF_STATE_BUCKET       = $STATE_BUCKET"
  echo "    EC2_KEY_PAIR_NAME     = $KEY_PAIR_NAME"
  echo "    EC2_SSH_KEY           = (contents of $KEY_FILE)"
  echo ""
  echo "  Variables (Settings → Variables → Actions):"
  echo "    AWS_REGION = $AWS_REGION"
else
  echo "Setting GitHub secrets via gh CLI..."
  gh secret set AWS_ACCESS_KEY_ID     --body "$ACCESS_KEY_ID"
  gh secret set AWS_SECRET_ACCESS_KEY --body "$SECRET_KEY"
  gh secret set TF_STATE_BUCKET       --body "$STATE_BUCKET"
  gh secret set EC2_KEY_PAIR_NAME     --body "$KEY_PAIR_NAME"
  gh secret set EC2_SSH_KEY           < "$KEY_FILE"
  gh variable set AWS_REGION          --body "$AWS_REGION"
  echo "✓ All GitHub secrets and variables set"
fi

echo ""
echo "=== Bootstrap complete ==="
echo ""
echo "Push to main to trigger your first deploy:"
echo "  git commit --allow-empty -m 'trigger first deploy' && git push"
