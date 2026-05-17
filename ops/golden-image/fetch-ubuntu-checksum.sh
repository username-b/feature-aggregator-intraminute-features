#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://cloud-images.ubuntu.com/noble/current"
IMAGE_NAME="noble-server-cloudimg-amd64.img"

CHECKSUM="$(
  curl -fsSL "${BASE_URL}/SHA256SUMS" \
    | awk -v image="${IMAGE_NAME}" '$2 == "*" image || $2 == image { print $1 }'
)"

if [[ -z "${CHECKSUM}" ]]; then
  echo "Could not find checksum for ${IMAGE_NAME}" >&2
  exit 1
fi

cat > variables.pkrvars.hcl <<EOF
ubuntu_image_checksum = "sha256:${CHECKSUM}"
EOF

echo "Wrote variables.pkrvars.hcl"
