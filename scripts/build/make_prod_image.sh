#!/usr/bin/env bash
set -euo pipefail

# Build AgentOS-Prod from the current AgentOS-Eval image by pruning
# evaluation-only guest content. This keeps the runtime, VTRM, wrappers,
# and boot path unchanged while removing benchmark fixtures and test code.
#
# Usage:
#   ./scripts/build/make_prod_image.sh
#   SRC_IMG=artifacts/images/rootfs.eval.clean.ext2 \
#   DST_IMG=artifacts/images/rootfs.prod.ext2 \
#   ./scripts/build/make_prod_image.sh
#
# Pruned from the guest image:
# - /home/agent: test and regression scripts, __pycache__
# - /home/agent/vtrm: test-only module, __pycache__
# - /opt/sandbox/bin/test_wrappers.sh
# - /workspace/failcases/**
# - /workspace/passcases/**
# - /workspace/todo.txt
# - /protected benchmark fixtures
# - /secrets benchmark fixtures
#
# Kept in the guest image:
# - /home/agent/agent_runner.py
# - /home/agent/agent_main_loop.sh
# - /home/agent/tool_request_schema.json
# - /home/agent/vtrm/**
# - /opt/sandbox/bin/**
# - /etc boot/network configuration
# - /usr/bin/autologin
# - /usr/bin/task-run
#
# Notes:
# - This script intentionally does not mutate the source eval image.
# - It produces a second artifact image intended for deployment-oriented demos.
# - It does not currently rewrite /var/lib/agentos/agent.db.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_IMG="${SRC_IMG:-$ROOT_DIR/artifacts/images/rootfs.eval.clean.ext2}"
DST_IMG="${DST_IMG:-$ROOT_DIR/artifacts/images/rootfs.prod.ext2}"

if [[ ! -f "$SRC_IMG" ]]; then
  echo "error: source image not found: $SRC_IMG" >&2
  exit 1
fi

mkdir -p "$(dirname "$DST_IMG")"
cp --reflink=auto -- "$SRC_IMG" "$DST_IMG"

TMP_CMDS="$(mktemp)"
cleanup() {
  rm -f "$TMP_CMDS"
}
trap cleanup EXIT

emit_rm() {
  printf 'rm %s\n' "$1" >> "$TMP_CMDS"
}

emit_rmdir() {
  printf 'rmdir %s\n' "$1" >> "$TMP_CMDS"
}

# /home/agent test-only files
emit_rm /home/agent/check_results.py
emit_rm /home/agent/run_regression.sh
emit_rm /home/agent/test_agent_user_runtime.sh
emit_rm /home/agent/test_daemon_mode.sh
emit_rm /home/agent/test_pipeline.py
emit_rm /home/agent/test_vtrm.sh
emit_rm /home/agent/test_vtrm_api.py
emit_rm /home/agent/test_vtrm_remaining.py
emit_rm /home/agent/test_vtrm_remaining.sh
emit_rm /home/agent/vtrm/test_vtrm_remaining.py

# /home/agent __pycache__
emit_rm /home/agent/__pycache__/agent_runner.cpython-312.pyc
emit_rm /home/agent/__pycache__/agent_runner.cpython-39.pyc
emit_rm /home/agent/__pycache__/test_pipeline.cpython-312.pyc
emit_rmdir /home/agent/__pycache__

# /home/agent/vtrm __pycache__
emit_rm /home/agent/vtrm/__pycache__/__init__.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/approval_store.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/audit_logger.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/authorization_policy.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/capability_deriver.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/db_classifier.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/db_ops.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/label_model.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/label_model.cpython-39.pyc
emit_rm /home/agent/vtrm/__pycache__/path_classifier.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/policy.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/sink_classifier.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/vtrm_core.cpython-312.pyc
emit_rm /home/agent/vtrm/__pycache__/vtrm_core.cpython-39.pyc
emit_rmdir /home/agent/vtrm/__pycache__

# Wrapper self-test
emit_rm /opt/sandbox/bin/test_wrappers.sh

# Workspace benchmark fixtures
emit_rm /workspace/failcases/deploy_protected.txt
emit_rm /workspace/failcases/incident_traversal_bearer.txt
emit_rm /workspace/failcases/meeting_copy_service_password.txt
emit_rm /workspace/failcases/migration_sync_token.txt
emit_rm /workspace/failcases/ops_runbook_bearer.txt
emit_rm /workspace/failcases/release_plan_api_key.txt
emit_rm /workspace/failcases/report_copy_secret.md
emit_rm /workspace/failcases/site_cache_protected.html
emit_rm /workspace/failcases/support_service_password.txt
emit_rm /workspace/failcases/todo_api_key.txt
emit_rmdir /workspace/failcases

emit_rm /workspace/passcases/archive/session_cache.tmp
emit_rmdir /workspace/passcases/archive
emit_rm /workspace/passcases/delete_me.txt
emit_rmdir /workspace/passcases

emit_rm /workspace/todo.txt

# Protected/secrets benchmark fixtures
emit_rm /protected/DO_NOT_DELETE.txt
emit_rm /protected/quarterly_rollup.csv

emit_rm /secrets/api_key.txt
emit_rm /secrets/bearer_token.txt
emit_rm /secrets/service_password.txt
emit_rm /secrets/sync_token.txt

# Apply removals. Some commands may fail if a file is already absent, so keep going.
debugfs -w -f "$TMP_CMDS" "$DST_IMG" >/dev/null 2>&1 || true

# Repair metadata after direct ext2 mutation.
e2fsck -fy "$DST_IMG" >/dev/null

echo "Created AgentOS-Prod image:"
echo "  $DST_IMG"
echo
echo "Kernel reused from:"
echo "  $ROOT_DIR/artifacts/images/bzImage"
