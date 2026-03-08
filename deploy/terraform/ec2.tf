# Ubuntu 24.04 LTS — matches ec2-setup.sh
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# ── EC2 instance ──────────────────────────────────────────────────────────────

resource "aws_instance" "nanobot" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.nanobot.id]

  # Root volume: OS + Docker layers (Python, Node, Chromium, Patchright). 30GB default avoids "no space left" during layer extraction.
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gb
    delete_on_termination = true
    encrypted             = true

    tags = { Name = "${var.project_name}-root" }
  }

  # Bootstrap: install Docker, clone repo, run ec2-setup.sh
  # API keys are NOT set here — SSH in after provisioning to fill ~/.nanobot/config.json
  user_data = base64encode(templatefile("${path.module}/user_data.sh.tpl", {
    repo_url   = var.repo_url
    repo_branch = var.repo_branch
    aws_region = var.aws_region
  }))

  # Replace instance (not in-place update) when user_data changes
  user_data_replace_on_change = false

  tags = { Name = var.project_name }
}

# ── Separate data EBS volume (/opt/nanobot) ───────────────────────────────────
# Kept separate from root so you can snapshot config/memory without touching the OS,
# and survive instance replacement.

resource "aws_ebs_volume" "data" {
  availability_zone = local.az
  size              = var.data_volume_size_gb
  type              = "gp3"
  encrypted         = true

  tags = { Name = "${var.project_name}-data" }
}

resource "aws_volume_attachment" "data" {
  device_name  = "/dev/sdf"
  volume_id    = aws_ebs_volume.data.id
  instance_id  = aws_instance.nanobot.id
  # Stop instance before detach to avoid data corruption
  stop_instance_before_detaching = true
}

# ── Elastic IP (stable public IP survives instance stop/start) ────────────────

resource "aws_eip" "nanobot" {
  instance = aws_instance.nanobot.id
  domain   = "vpc"

  depends_on = [aws_internet_gateway.main]

  tags = { Name = "${var.project_name}-eip" }
}
