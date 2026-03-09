# EC2 Ops Cheat Sheet

> **Rule of thumb:** CloakBrowser + Chromium layers need ~20–30 GB on root volume minimum.

---

## SSH Access

**Problem:** No local key — `EC2_SSH_KEY` lives only in GitHub Secrets (write-only).  
**Solution:** EC2 Instance Connect pushes a temp public key (60s TTL).

```bash
./ec2ssh                   # interactive shell
./ec2ssh "some command"    # run and exit
```

`ec2ssh` now supports parameterised target selection:

```bash
# via env vars
EC2_INSTANCE_ID=i-xxxx EC2_HOST=1.2.3.4 ./ec2ssh

# via flags
./ec2ssh --instance-id i-xxxx --host 1.2.3.4
./ec2ssh --region ap-southeast-2 --user ubuntu --key /tmp/my-ec2-key
./ec2ssh --instance-id i-xxxx --host 1.2.3.4 "docker ps"
```

Supported env vars: `EC2_INSTANCE_ID`, `EC2_HOST`, `AWS_REGION`, `EC2_SSH_USER`, `EC2_SSH_KEY_PATH`.
Equivalent flags: `--instance-id`, `--host`, `--region`, `--user`, `--key`.

---

## Scenario 1: Docker build fails with "no space left on device"

**Symptom:**
```
write .../chromium_headless_shell-1194/.../headless_shell: no space left on device
```
or `_rust.abi3.so` / any layer extract during `docker compose build`.

**Diagnose:**
```bash
./ec2ssh "df -h /"
./ec2ssh "docker system df"
./ec2ssh "sudo du -sh /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/"
./ec2ssh "sudo du -sh /var/lib/docker/*"
```

**Fix — clear build cache (safe, always reclaimable):**
```bash
./ec2ssh "docker builder prune -af"
```

**Fix — remove unused images:**
```bash
./ec2ssh "docker image prune -af"
```

**Fix — full Docker cleanup (images, cache, volumes):**
```bash
./ec2ssh "docker system prune -af --volumes && docker builder prune -af"
```

> `image prune -af` won't touch images used by running containers — **stop containers first** (`docker compose down`) so old nanobot images can be pruned.  
> CI deploy now does: down → image prune -af → builder prune -af → build → up, and root volume default is 30GB for new Terraform instances.

---

## Scenario 2: Clear containerd snapshot cache

Use when build cache prune isn't enough and snapshots are consuming space.

```bash
./ec2ssh "sudo systemctl stop docker.socket docker containerd"
./ec2ssh "sudo rm -rf /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/*"
./ec2ssh "sudo systemctl start containerd docker"
```

---

## Scenario 3: `rm` reports success but `du` still shows old size

Files are held open by a running process — space isn't freed until the process releases them.

```bash
./ec2ssh "sudo lsof +D /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/ 2>/dev/null | head -20"
```

Or the deletion worked and `du` is showing stale cache — verify with:
```bash
./ec2ssh "df -h /var/lib/containerd"
```

---

## Scenario 4: `systemctl stop docker` warns "triggering units still active"

Stop the socket explicitly first:
```bash
./ec2ssh "sudo systemctl stop docker.socket docker containerd"
```

---

## Scenario 5: Containers not running after failed deploy

```bash
./ec2ssh "docker ps -a"
./ec2ssh "docker compose -f /opt/nanobot-app/docker-compose.yml logs --tail=50"
./ec2ssh "docker compose -f /opt/nanobot-app/docker-compose.yml up -d --force-recreate"
```

---

## Scenario 6: Check AWS profile / credentials

```bash
aws configure list
echo "Profile: ${AWS_PROFILE:-default}"
```

---

## Scenario 7: Find instance ID from IP

```bash
aws ec2 describe-instances \
  --region "${AWS_REGION:-ap-southeast-2}" \
  --filters "Name=ip-address,Values=${EC2_HOST:-13.54.226.177}" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text
```

---

## Instance Quick Reference

| | |
|---|---|
| Instance ID | default in `ec2ssh` (`EC2_INSTANCE_ID` / `--instance-id` to override) |
| Host/IP | default in `ec2ssh` (`EC2_HOST` / `--host` to override) |
| Region | `ap-southeast-2` by default (`AWS_REGION` / `--region`) |
| OS user | `ubuntu` by default (`EC2_SSH_USER` / `--user`) |
| Data volume | `/opt/nanobot` (EBS, persists across deploys) |
| App dir | `/opt/nanobot-app` (replaced on each deploy) |
