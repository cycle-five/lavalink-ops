terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Credentials: prefer the standard chain (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
# env vars, or ~/.aws/credentials). Populating aws_access_key/aws_secret_key in
# tfvars is supported but those values end up in state — use env vars in CI.
provider "aws" {
  region     = var.region
  access_key = var.aws_access_key != "" ? var.aws_access_key : null
  secret_key = var.aws_secret_key != "" ? var.aws_secret_key : null
}

# --- Variables ---

variable "aws_access_key" {
  description = "AWS access key. Leave empty to use env vars / ~/.aws/credentials."
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_secret_key" {
  description = "AWS secret key. Leave empty to use env vars / ~/.aws/credentials."
  type        = string
  sensitive   = true
  default     = ""
}

variable "region" {
  description = "AWS region (e.g. us-east-1, eu-west-1)"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type (2 vCPU / 4 GB is the target)"
  type        = string
  default     = "t3.medium"
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
  description = "SSH public key for the admin user"
  type        = string
  sensitive   = true
}

variable "ssh_allowed_ipv4" {
  description = "IPv4 CIDR allowed to SSH in (0.0.0.0/0 for all)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "ssh_allowed_ipv6" {
  description = "IPv6 CIDR allowed to SSH in (::/0 for all)"
  type        = string
  default     = "::/0"
}

# --- Latest Debian 12 AMI ---

data "aws_ami" "debian" {
  most_recent = true
  owners      = ["136693071363"] # Debian official

  filter {
    name   = "name"
    values = ["debian-12-amd64-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --- Networking (dedicated VPC with IPv6) ---

resource "aws_vpc" "main" {
  cidr_block                       = "10.0.0.0/16"
  assign_generated_ipv6_cidr_block = true
  enable_dns_hostnames             = true

  tags = { Name = "lavalink-ops" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "lavalink-ops" }
}

resource "aws_subnet" "public" {
  vpc_id                          = aws_vpc.main.id
  cidr_block                      = "10.0.1.0/24"
  ipv6_cidr_block                 = cidrsubnet(aws_vpc.main.ipv6_cidr_block, 8, 1)
  map_public_ip_on_launch         = true
  assign_ipv6_address_on_creation = true

  tags = { Name = "lavalink-ops-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  route {
    ipv6_cidr_block = "::/0"
    gateway_id      = aws_internet_gateway.main.id
  }

  tags = { Name = "lavalink-ops" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# --- Security Group ---
# SSH (restrictable), Lavalink WS (public), ICMP. Admin (8080), yt-cipher
# (8001), bgutil-pot (4416) are NOT exposed — reach admin via SSH tunnel:
#   ssh -L 8080:localhost:8080 admin@<ip>

resource "aws_security_group" "lavalink" {
  name        = "lavalink-ops"
  description = "lavalink-ops firewall"
  vpc_id      = aws_vpc.main.id

  ingress {
    description      = "SSH"
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    cidr_blocks      = [var.ssh_allowed_ipv4]
    ipv6_cidr_blocks = [var.ssh_allowed_ipv6]
  }

  ingress {
    description      = "Lavalink WebSocket"
    from_port        = 2333
    to_port          = 2333
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    description = "ICMP"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description      = "ICMPv6"
    from_port        = -1
    to_port          = -1
    protocol         = "icmpv6"
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description      = "All outbound"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = { Name = "lavalink-ops" }
}

# --- Key Pair ---

resource "aws_key_pair" "lavalink" {
  key_name   = "lavalink-ops"
  public_key = var.ssh_public_key
}

# --- EC2 Instance ---

resource "aws_instance" "lavalink" {
  ami                    = data.aws_ami.debian.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.lavalink.id]
  key_name               = aws_key_pair.lavalink.key_name
  ipv6_address_count     = 1

  root_block_device {
    volume_size = 60
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # 1. Enable non-local IPv6 binding for Lavalink RoutePlanner
    echo "net.ipv6.ip_nonlocal_bind=1" >> /etc/sysctl.conf
    sysctl -p

    # 2. Install Docker via the official APT repository.
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

  tags = { Name = "lavalink-ops" }
}

# --- Outputs ---

output "instance_ipv4" {
  value       = aws_instance.lavalink.public_ip
  description = "Server IPv4 address"
}

output "instance_ipv6" {
  value       = try(aws_instance.lavalink.ipv6_addresses[0], "")
  description = "Server IPv6 address"
}

output "ssh_tunnel_command" {
  value       = "ssh -L ${var.admin_port}:localhost:${var.admin_port} admin@${aws_instance.lavalink.public_ip}"
  description = "SSH tunnel to access the admin panel. Debian AMIs use the 'admin' user, not root."
}

output "lavalink_endpoint" {
  value       = "${aws_instance.lavalink.public_ip}:2333"
  description = "Lavalink WebSocket endpoint for your bot"
}
