terraform {
  required_providers {
    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5.0"
    }
  }
}

provider "upcloud" {
  # Credentials via UPCLOUD_USERNAME / UPCLOUD_PASSWORD env vars
  token = var.upcloud_api_token
}

# --- Variables ---

variable "upcloud_api_token" {
  description = "UpCloud API token"
  type        = string
  sensitive   = true
}

variable "zone" {
  description = "UpCloud zone (e.g. us-nyc1, eu-fra1)"
  type        = string
  default     = "us-nyc1"
}

variable "plan" {
  description = "UpCloud server plan"
  type        = string
  default     = "DEV-2xCPU-4GB"
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

variable "ssh_public_key" {
  description = "SSH public key for root login"
  type        = string
  sensitive   = true
}

variable "ssh_allowed_ipv4" {
  description = "IPv4 CIDR allowed to SSH in (0.0.0.0/0 for all)"
  type        = string
  default     = "0.0.0.0/0"
}

# --- Storage ---

resource "upcloud_storage" "boot" {
  size  = 60
  tier  = "standard"
  title = "lavalink-ops boot disk"
  zone  = var.zone
}

# --- Server ---

resource "upcloud_server" "lavalink_node" {
  hostname = "lavalink-ops"
  title    = "lavalink-ops"
  zone     = var.zone
  plan     = var.plan
  firewall = true
  metadata = true

  login {
    user            = "root"
    keys            = [var.ssh_public_key]
    create_password = false
  }

  network_interface {
    ip_address_family = "IPv4"
    type              = "public"
  }

  network_interface {
    ip_address_family = "IPv4"
    type              = "utility"
  }

  network_interface {
    ip_address_family = "IPv6"
    type              = "public"
  }

  storage_devices {
    address = "virtio"
    storage = upcloud_storage.boot.id
    type    = "disk"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # 1. Enable non-local IPv6 binding for Lavalink RoutePlanner
    echo "net.ipv6.ip_nonlocal_bind=1" >> /etc/sysctl.conf
    sysctl -p

    # 2. Install Docker
    apt-get update
    apt-get install -y ca-certificates curl git
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # 3. Clone and start the stack
    git clone ${var.repo_url} /opt/lavalink-ops
    cd /opt/lavalink-ops
    ./setup.sh
    docker compose up --build -d
  EOF
}

# --- Firewall ---

resource "upcloud_firewall_rules" "lavalink_node" {
  server_id = upcloud_server.lavalink_node.id

  # --- Inbound ---

  firewall_rule {
    comment                = "SSH IPv4"
    action                 = "accept"
    direction              = "in"
    family                 = "IPv4"
    protocol               = "tcp"
    source_address_start   = split("/", var.ssh_allowed_ipv4)[0]
    source_address_end     = split("/", var.ssh_allowed_ipv4)[0]
    destination_port_start = "22"
    destination_port_end   = "22"
  }

  firewall_rule {
    comment                = "SSH IPv6"
    action                 = "accept"
    direction              = "in"
    family                 = "IPv6"
    protocol               = "tcp"
    destination_port_start = "22"
    destination_port_end   = "22"
  }

  firewall_rule {
    comment                = "Lavalink WS IPv4"
    action                 = "accept"
    direction              = "in"
    family                 = "IPv4"
    protocol               = "tcp"
    destination_port_start = "2333"
    destination_port_end   = "2333"
  }

  firewall_rule {
    comment                = "Lavalink WS IPv6"
    action                 = "accept"
    direction              = "in"
    family                 = "IPv6"
    protocol               = "tcp"
    destination_port_start = "2333"
    destination_port_end   = "2333"
  }

  firewall_rule {
    comment   = "ICMP IPv4"
    action    = "accept"
    direction = "in"
    family    = "IPv4"
    protocol  = "icmp"
    icmp_type = "8"
  }

  firewall_rule {
    comment   = "ICMPv6 echo request"
    action    = "accept"
    direction = "in"
    family    = "IPv6"
    protocol  = "icmp"
    icmp_type = "128"
  }

  # --- Outbound ---

  firewall_rule {
    comment                = "HTTP out IPv4"
    action                 = "accept"
    direction              = "out"
    family                 = "IPv4"
    protocol               = "tcp"
    destination_port_start = "8080"
    destination_port_end   = "8080"
  }

  firewall_rule {
    comment                = "HTTPS out IPv4"
    action                 = "accept"
    direction              = "out"
    family                 = "IPv4"
    protocol               = "tcp"
    destination_port_start = "443"
    destination_port_end   = "443"
  }

  firewall_rule {
    comment                = "HTTP out IPv6"
    action                 = "accept"
    direction              = "out"
    family                 = "IPv6"
    protocol               = "tcp"
    destination_port_start = "8080"
    destination_port_end   = "8080"
  }

  firewall_rule {
    comment                = "HTTPS out IPv6"
    action                 = "accept"
    direction              = "out"
    family                 = "IPv6"
    protocol               = "tcp"
    destination_port_start = "443"
    destination_port_end   = "443"
  }

  firewall_rule {
    comment                = "DNS out IPv4"
    action                 = "accept"
    direction              = "out"
    family                 = "IPv4"
    protocol               = "udp"
    destination_port_start = "53"
    destination_port_end   = "53"
  }

  firewall_rule {
    comment                = "DNS out IPv6"
    action                 = "accept"
    direction              = "out"
    family                 = "IPv6"
    protocol               = "udp"
    destination_port_start = "53"
    destination_port_end   = "53"
  }

  # --- Default deny ---

  firewall_rule {
    action    = "drop"
    direction = "in"
  }

  firewall_rule {
    action    = "drop"
    direction = "out"
  }
}

# --- Outputs ---

output "instance_ipv4" {
  value       = upcloud_server.lavalink_node.network_interface[0].ip_address
  description = "Server IPv4 address"
}

output "instance_ipv6" {
  value       = upcloud_server.lavalink_node.network_interface[2].ip_address
  description = "Server IPv6 address"
}

output "ssh_tunnel_command" {
  value       = "ssh -L ${var.admin_port}:localhost:${var.admin_port} root@${upcloud_server.lavalink_node.network_interface[0].ip_address}"
  description = "SSH tunnel to access the admin panel"
}

output "lavalink_endpoint" {
  value       = "${upcloud_server.lavalink_node.network_interface[0].ip_address}:2333"
  description = "Lavalink WebSocket endpoint"
}