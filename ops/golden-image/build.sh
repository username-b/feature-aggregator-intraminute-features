#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if ! command -v packer >/dev/null 2>&1; then
  echo "packer is required" >&2
  exit 1
fi

if ! command -v qemu-img >/dev/null 2>&1; then
  echo "qemu-img is required" >&2
  exit 1
fi

if [[ ! -f variables.pkrvars.hcl ]]; then
  echo "variables.pkrvars.hcl is missing. Copy variables.pkrvars.hcl.example and set ubuntu_image_checksum." >&2
  exit 1
fi

packer init .
packer validate -var-file=variables.pkrvars.hcl .
packer build -var-file=variables.pkrvars.hcl .

IMAGE_PATH="output/container-runner-ubuntu2404/container-runner-ubuntu2404.qcow2"
OPTIMIZED_PATH="output/container-runner-ubuntu2404/container-runner-ubuntu2404-optimized.qcow2"

qemu-img convert -p -O qcow2 -o cluster_size=2M "${IMAGE_PATH}" "${OPTIMIZED_PATH}"
qemu-img info "${OPTIMIZED_PATH}"

echo
echo "Ready image:"
echo "${OPTIMIZED_PATH}"
