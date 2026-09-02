#!/bin/bash
# First-boot setup for the Oracle VM: Docker + compose, the repo, and host firewall for the
# substrate's public ports. Secrets (.env) are copied in later over SSH, not baked here.
set -x
export DEBIAN_FRONTEND=noninteractive
# 2GB swap: lets the litellm gateway's ~627MB import spike survive on a 1GB micro (settles to ~434MB)
fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
chmod 600 /swapfile; mkswap /swapfile; swapon /swapfile
grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
apt-get update
apt-get install -y ca-certificates curl git iptables-persistent
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu
# OCI Ubuntu images ship a restrictive iptables INPUT chain — open the substrate's public ports
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 4000 -j ACCEPT
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8501 -j ACCEPT
netfilter-persistent save || true
# the public repo (secrets arrive separately via scp of .env)
git clone https://github.com/shlapolosa/local-agent-lab.git /home/ubuntu/local-agent-lab || true
chown -R ubuntu:ubuntu /home/ubuntu/local-agent-lab
touch /home/ubuntu/CLOUDINIT_DONE
