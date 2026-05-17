#!/usr/bin/env bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  cloud-init \
  curl \
  git \
  gnupg \
  jq \
  openssh-server \
  qemu-guest-agent \
  ufw

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt-get update
sudo apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin

sudo install -d -m 0755 /etc/docker
sudo install -m 0644 /tmp/docker-daemon.json /etc/docker/daemon.json
sudo systemctl enable docker
sudo systemctl enable ssh
sudo systemctl enable qemu-guest-agent

sudo mkdir -p /opt/feature-jobs
sudo chmod 0755 /opt/feature-jobs

sudo useradd --system --create-home --home-dir /var/lib/feature-jobs --shell /usr/sbin/nologin feature-jobs || true
sudo usermod -aG docker feature-jobs

sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw --force enable

sudo tee /etc/default/grub.d/99-yandex-serial.cfg >/dev/null <<'EOF'
GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0"
GRUB_CMDLINE_LINUX="console=tty1 console=ttyS0"
EOF
sudo update-grub

sudo cloud-init clean --logs
sudo rm -f /etc/ssh/ssh_host_*
sudo truncate -s 0 /etc/machine-id
sudo rm -f /var/lib/dbus/machine-id
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*
