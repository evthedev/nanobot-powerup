terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # S3 backend — bucket name passed at init time via -backend-config (see deploy.yml)
  # This keeps the bucket name out of the code and in GitHub secrets instead.
  backend "s3" {
    key     = "nanobot/terraform.tfstate"
    encrypt = true
    # bucket and region are injected by CI:
    #   terraform init -backend-config="bucket=$TF_STATE_BUCKET" -backend-config="region=..."
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      ManagedBy   = "terraform"
    }
  }
}
