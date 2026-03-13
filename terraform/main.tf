terraform {
  required_providers {
    vultr = {
      source = "vultr/vultr"
      version = "2.21.0"
    }
  }
}

provider "vultr" {
  api_key = var.vultr_api_key
  rate_limit = 100
  retry_limit = 3
}

variable "vultr_api_key" {
  description = "Your Vultr API Key"
  type        = string
  sensitive   = true
}

resource "vultr_instance" "lavalink_node" {
  plan        = "vc2-2c-4gb" # 2 vCPUs, 4GB RAM (Recommended for Lavalink)
  region      = "ewr"        # New Jersey (Change to your preferred region)
  os_id       = 2136         # Debian 12 x64
  label       = "lavalink-ops-production"
  enable_ipv6 = true         # CRITICAL: This assigns the /64 block automatically via Vultr API
  
  # Cloud-init script to automatically prep the networking on first boot
  user_data = <<-EOF
    #!/bin/bash
    
    # 1. Enable non-local binding for Lavalink RoutePlanner
    echo "net.ipv6.ip_nonlocal_bind=1" >> /etc/sysctl.conf
    sysctl -p

    # 2. Install Docker
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh

    # 3. Pull down the Lavalink-Ops stack
    apt-get install -y git
    git clone https://github.com/cycle-five/lavalink-ops2.git /opt/lavalink-ops
    cd /opt/lavalink-ops/lavalink-stack
    
    # Run the stack
    docker compose up -d
  EOF
}

output "instance_ipv4" {
  value = vultr_instance.lavalink_node.main_ip
}

output "instance_ipv6_subnet" {
  value = vultr_instance.lavalink_node.v6_main_ip
  description = "Your /64 block! Example: If this is 2001:db8:1234:5678::100, your block is 2001:db8:1234:5678::/64 for application.yml"
}
