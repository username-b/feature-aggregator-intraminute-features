packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = ">= 1.1.4"
    }
  }
}

variable "ubuntu_image_url" {
  type        = string
  description = "URL of the Ubuntu cloud image to use as the base disk."
  default     = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
}

variable "ubuntu_image_checksum" {
  type        = string
  description = "Checksum for the Ubuntu cloud image, for example sha256:<digest>."
}

variable "ssh_username" {
  type    = string
  default = "packer"
}

variable "ssh_password" {
  type      = string
  sensitive = true
  default   = "packer"
}

variable "output_directory" {
  type    = string
  default = "output/container-runner-ubuntu2404"
}

variable "accelerator" {
  type        = string
  description = "QEMU accelerator. Use kvm on Linux hosts with virtualization support, or tcg as a slower fallback."
  default     = "kvm"
}

source "qemu" "container_runner" {
  accelerator      = var.accelerator
  disk_image       = true
  disk_interface   = "virtio"
  format           = "qcow2"
  headless         = true
  iso_checksum     = var.ubuntu_image_checksum
  iso_url          = var.ubuntu_image_url
  net_device       = "virtio-net"
  output_directory = var.output_directory
  shutdown_command = "echo '${var.ssh_password}' | sudo -S shutdown -P now"
  ssh_password     = var.ssh_password
  ssh_timeout      = "20m"
  ssh_username     = var.ssh_username
  vm_name          = "container-runner-ubuntu2404.qcow2"

  cd_label = "cidata"
  cd_files = [
    "seed/meta-data",
    "seed/user-data",
  ]
}

build {
  name    = "container-runner-ubuntu2404"
  sources = ["source.qemu.container_runner"]

  provisioner "file" {
    source      = "files/docker-daemon.json"
    destination = "/tmp/docker-daemon.json"
  }

  provisioner "shell" {
    script = "scripts/provision.sh"
  }
}
