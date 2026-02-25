output "public_ip" {
  description = "Elastic IP of the nanobot instance"
  value       = aws_eip.nanobot.public_ip
}

output "dashboard_url" {
  description = "URL of the nanobot dashboard"
  value       = "https://${aws_eip.nanobot.public_ip}"
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ubuntu@${aws_eip.nanobot.public_ip}"
}

output "config_edit_command" {
  description = "Command to edit the nanobot config (add API keys) after first boot"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ubuntu@${aws_eip.nanobot.public_ip} 'sudo nano /opt/nanobot/config.json'"
}

output "setup_log_command" {
  description = "Command to tail the first-boot setup log"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ubuntu@${aws_eip.nanobot.public_ip} 'sudo tail -f /var/log/nanobot-setup.log'"
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.nanobot.id
}

output "data_volume_id" {
  description = "EBS data volume ID (snapshot this to back up config/memory)"
  value       = aws_ebs_volume.data.id
}

# ── GitHub Actions setup ──────────────────────────────────────────────────────
# After apply, run the commands below and paste the values into:
# GitHub repo → Settings → Secrets and variables → Actions → New repository secret

output "next_steps" {
  description = "What to do after terraform apply"
  value = <<-EOT

    ── GitHub Actions secrets (run these, paste output into GitHub) ──
    Secret name : EC2_HOST
    Secret value: ${aws_eip.nanobot.public_ip}

    Secret name : EC2_SSH_KEY
    Secret value: run →  cat ~/.ssh/${var.key_pair_name}.pem

    ── Add your API keys ─────────────────────────────────────────────
    ${format("ssh -i ~/.ssh/%s.pem ubuntu@%s 'sudo nano /opt/nanobot/config.json'", var.key_pair_name, aws_eip.nanobot.public_ip)}

  EOT
}
