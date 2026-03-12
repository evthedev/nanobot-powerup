terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
    tls = { source = "hashicorp/tls", version = "~> 4.0" }
  }
  # Local state — this module bootstraps the remote backend, so it can't use it
  backend "local" {}
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region"    { type = string }
variable "project_name"  { type = string }

# ── S3 state bucket ───────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "${var.project_name}-tf-state-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "state" {
  bucket        = local.bucket_name
  force_destroy = false
  tags          = { Name = local.bucket_name }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# ── IAM user for CI ───────────────────────────────────────────────────────────

resource "aws_iam_user" "ci" {
  name = "${var.project_name}-ci"
}

resource "aws_iam_user_policy_attachment" "ec2" {
  user       = aws_iam_user.ci.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2FullAccess"
}

resource "aws_iam_user_policy_attachment" "s3" {
  user       = aws_iam_user.ci.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_access_key" "ci" {
  user = aws_iam_user.ci.name
}

# ── EC2 key pair ──────────────────────────────────────────────────────────────

resource "tls_private_key" "ec2" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "ec2" {
  key_name   = "${var.project_name}-key"
  public_key = tls_private_key.ec2.public_key_openssh
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "state_bucket"          { value = aws_s3_bucket.state.bucket }
output "aws_access_key_id"     { value = aws_iam_access_key.ci.id }
output "aws_secret_access_key" {
  value     = aws_iam_access_key.ci.secret
  sensitive = true
}
output "ec2_key_pair_name"     { value = aws_key_pair.ec2.key_name }
output "ec2_ssh_key" {
  value     = tls_private_key.ec2.private_key_pem
  sensitive = true
}
