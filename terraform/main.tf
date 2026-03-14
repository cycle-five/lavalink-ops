terraform {
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.21"
    }
  }
}

provider "vultr" {
  api_key     = var.vultr_api_key
  rate_limit  = 100
  retry_limit = 3
}

# --- Variables ---

variable "vultr_api_key" {
  description = "Vultr API key"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Vultr region (e.g. ewr, lax, ams)"
  type        = string
  default     = "ewr"
}

variable "plan" {
  description = "Vultr instance plan"
  type        = string
  default     = "vc2-2c-4gb"
}

variable "repo_url" {
  description = "Git repo URL for lavalink-ops"
  type        = string
  default     = "https://github.com/cycle-five/lavalink-ops.git"
}

variable "admin_port" {
  description = "Admin panel port"
  type        = number
  default     = 8080
}

variable "ssh_allowed_ipv4_subnet" {
  description = "IPv4 subnet allowed to access SSH (set to your IP or network; default is 0.0.0.0 for all IPv4)"
  type        = string
  default     = "0.0.0.0"
}

variable "ssh_allowed_ipv4_subnet_size" {
  description = "CIDR prefix length for the allowed SSH IPv4 subnet (e.g. 32 for a single IP; 0 allows all IPv4)"
  type        = number
  default     = 0
}

# --- Firewall ---

resource "vultr_firewall_group" "lavalink" {
  description = "lavalink-ops firewall"
}

resource "vultr_firewall_rule" "ssh" {
  firewall_group_id = vultr_firewall_group.lavalink.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = var.ssh_allowed_ipv4_subnet
  subnet_size       = var.ssh_allowed_ipv4_subnet_size
  port              = "22"
}

resource "vultr_firewall_rule" "ssh_v6" {
  firewall_group_id = vultr_firewall_group.lavalink.id
  protocol          = "tcp"
  ip_type           = "v6"
  subnet            = "::"
  subnet_size       = 0
  port              = "22"
}

resource "vultr_firewall_rule" "lavalink" {
  firewall_group_id = vultr_firewall_group.lavalink.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "2333"
}

resource "vultr_firewall_rule" "lavalink_v6" {
  firewall_group_id = vultr_firewall_group.lavalink.id
  protocol          = "tcp"
  ip_type           = "v6"
  subnet            = "::"
  subnet_size       = 0
  port              = "2333"
}

# Note: Admin panel (8080), yt-cipher (8001), bgutil-pot (4416) are NOT exposed.
# Access the admin panel via SSH tunnel: ssh -L 8080:localhost:8080 root@<ip>

# --- Instance ---

resource "vultr_instance" "lavalink_node" {
  plan              = var.plan
  region            = var.region
  os_id             = 2136 # Debian 12 x64
  label             = "lavalink-ops"
  enable_ipv6       = true
  firewall_group_id = vultr_firewall_group.lavalink.id

  user_data = <<EOF
#!/bin/bash
set -euo pipefail

# 1. Enable non-local binding for Lavalink RoutePlanner
echo "net.ipv6.ip_nonlocal_bind=1" >> /etc/sysctl.conf
sysctl -p

# 2. Install Docker via the official APT repository (avoids curl-to-shell execution).
#    Follows https://docs.docker.com/engine/install/debian/
#    First update syncs package lists so we can install prerequisites.
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
# Download Docker's official GPG key (ASCII-armored .asc).
# All packages installed from this repo are cryptographically verified against this key by apt.
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
# Second update picks up the newly added Docker repository before installing.
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3. Pull down the Lavalink-Ops stack
apt-get install -y git

# Clone and set up the stack
git clone ${var.repo_url} /opt/lavalink-ops
cd /opt/lavalink-ops

# One-click setup: generates secrets, syncs config, creates dirs
./setup.sh

# Start the stack
docker compose up --build -d
EOF
}

# --- Outputs ---

output "instance_ipv4" {
  value       = vultr_instance.lavalink_node.main_ip
  description = "Server IPv4 address"
}

output "instance_ipv6_subnet" {
  value       = "${vultr_instance.lavalink_node.v6_network}/${vultr_instance.lavalink_node.v6_network_size}"
  description = "IPv6 subnet (e.g. 2001:db8::/64) for application.yml routePlanner"
}

output "ssh_tunnel_command" {
  value       = "ssh -L ${var.admin_port}:localhost:${var.admin_port} root@${vultr_instance.lavalink_node.main_ip}"
  description = "SSH tunnel to access the admin panel."
}

output "lavalink_endpoint" {
  value       = "${vultr_instance.lavalink_node.main_ip}:2333"
  description = "Lavalink WebSocket endpoint for your bot"
}
