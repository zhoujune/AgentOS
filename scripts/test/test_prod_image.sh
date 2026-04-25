#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-$ROOT_DIR/artifacts/images/rootfs.prod.ext2}"
KERNEL="${KERNEL:-$ROOT_DIR/artifacts/images/bzImage}"
BRIDGE_DIR="${BRIDGE_DIR:-$ROOT_DIR/runtime/agent_bridge}"
QEMU_BIN="${QEMU_BIN:-qemu-system-x86_64}"
MEMORY_MB="${MEMORY_MB:-512}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-90}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/runtime/prod_smoketest}"

mkdir -p "$LOG_DIR" "$BRIDGE_DIR"/{inbox,outbox,done,error,tasks}
QEMU_LOG="$LOG_DIR/qemu.log"
rm -f "$QEMU_LOG"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "missing required file: $path" >&2
    exit 1
  fi
}

check_present() {
  local image="$1"
  local path="$2"
  local output
  output="$(debugfs -R "stat $path" "$image" 2>&1 || true)"
  if grep -Fq "File not found" <<<"$output"; then
    echo "missing in prod image: $path" >&2
    exit 1
  fi
}

check_absent() {
  local image="$1"
  local path="$2"
  local output
  output="$(debugfs -R "stat $path" "$image" 2>&1 || true)"
  if ! grep -Fq "File not found" <<<"$output"; then
    echo "unexpected eval-only path still present in prod image: $path" >&2
    exit 1
  fi
}

wait_for_log_phrase() {
  local phrase="$1"
  local timeout="$2"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if [[ -f "$QEMU_LOG" ]] && grep -Fq "$phrase" "$QEMU_LOG"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stop_qemu() {
  if [[ -n "${QEMU_PID:-}" ]]; then
    kill "$QEMU_PID" 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
  fi
}
trap stop_qemu EXIT

require_file "$IMAGE"
require_file "$KERNEL"

echo "[1/3] checking prod image structure"
check_present "$IMAGE" /home/agent/agent_runner.py
check_present "$IMAGE" /home/agent/agent_main_loop.sh
check_present "$IMAGE" /home/agent/tool_request_schema.json
check_present "$IMAGE" /home/agent/vtrm/vtrm_core.py
check_present "$IMAGE" /opt/sandbox/bin/fs_wrapper.sh
check_present "$IMAGE" /usr/bin/autologin
check_present "$IMAGE" /usr/bin/task-run

check_absent "$IMAGE" /home/agent/test_pipeline.py
check_absent "$IMAGE" /home/agent/test_vtrm.sh
check_absent "$IMAGE" /home/agent/run_regression.sh
check_absent "$IMAGE" /home/agent/vtrm/test_vtrm_remaining.py
check_absent "$IMAGE" /opt/sandbox/bin/test_wrappers.sh
check_absent "$IMAGE" /workspace/failcases
check_absent "$IMAGE" /workspace/passcases
check_absent "$IMAGE" /workspace/todo.txt
check_absent "$IMAGE" /protected/DO_NOT_DELETE.txt
check_absent "$IMAGE" /secrets/api_key.txt

echo "[2/3] booting prod image"
"$QEMU_BIN" \
  -m "$MEMORY_MB" \
  -kernel "$KERNEL" \
  -drive "file=$IMAGE,format=raw" \
  -append "root=/dev/sda console=ttyS0" \
  -fsdev "local,id=bridge_dev,path=$BRIDGE_DIR,security_model=mapped,multidevs=remap" \
  -device virtio-9p-pci,fsdev=bridge_dev,mount_tag=agent_bridge \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -nographic \
  >"$QEMU_LOG" 2>&1 &
QEMU_PID=$!

if ! wait_for_log_phrase "[agent-startup] Switching to agent user..." "$BOOT_TIMEOUT"; then
  echo "prod image failed to reach agent startup within ${BOOT_TIMEOUT}s" >&2
  tail -n 80 "$QEMU_LOG" >&2 || true
  exit 1
fi

echo "[3/3] prod image booted successfully"
echo "log: $QEMU_LOG"
