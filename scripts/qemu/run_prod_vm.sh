#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KERNEL="${KERNEL:-$ROOT_DIR/artifacts/images/bzImage}"
IMAGE="${IMAGE:-$ROOT_DIR/artifacts/images/rootfs.prod.ext2}"
BRIDGE_DIR="${BRIDGE_DIR:-$ROOT_DIR/runtime/agent_bridge}"
QEMU_BIN="${QEMU_BIN:-qemu-system-x86_64}"
MEMORY_MB="${MEMORY_MB:-512}"

if [[ ! -f "$KERNEL" ]]; then
  echo "missing kernel image: $KERNEL" >&2
  exit 1
fi

if [[ ! -f "$IMAGE" ]]; then
  echo "missing prod rootfs image: $IMAGE" >&2
  exit 1
fi

mkdir -p "$BRIDGE_DIR"/{inbox,outbox,done,error,tasks}

exec "$QEMU_BIN" \
  -m "$MEMORY_MB" \
  -kernel "$KERNEL" \
  -drive "file=$IMAGE,format=raw" \
  -append "root=/dev/sda console=ttyS0" \
  -fsdev "local,id=bridge_dev,path=$BRIDGE_DIR,security_model=mapped,multidevs=remap" \
  -device virtio-9p-pci,fsdev=bridge_dev,mount_tag=agent_bridge \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
