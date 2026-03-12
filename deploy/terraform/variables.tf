variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Name prefix for all resources"
  type        = string
  default     = "nanobot"
}

variable "instance_type" {
  description = "EC2 instance type. t3.micro (2 vCPU / 2GB) is sufficient for a PoC — idle stack uses ~760MB. A 2GB swap file in user_data covers Playwright spikes. Upgrade to t3.medium if you're running Playwright heavily or seeing OOM kills."
  type        = string
  default     = "t3.micro"
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair to use for SSH access"
  type        = string
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size (GB). Needs ~25GB+ for Docker builds: Python + Node + system Chromium + Patchright headless shell; build extraction can double layer size temporarily."
  type        = number
  default     = 30
}

variable "data_volume_size_gb" {
  description = "Separate EBS data volume for /opt/nanobot (config, memory, sessions, workspace). Kept separate so you can snapshot/restore without touching the OS volume"
  type        = number
  default     = 10
}

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed to SSH to the instance. Restrict to your IP(s) for security"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "repo_url" {
  description = "Git repo URL to clone on first boot (the nanobot-powerup repo)"
  type        = string
  default     = "https://github.com/evthedev/nanobot-powerup.git"
}

variable "repo_branch" {
  description = "Git branch to check out"
  type        = string
  default     = "main"
}
