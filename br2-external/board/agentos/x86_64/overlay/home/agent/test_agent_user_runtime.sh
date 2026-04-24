#!/usr/bin/env bash
set -euo pipefail

AGENT_USER="${AGENT_USER:-agent}"
AGENT_DIR="${AGENT_DIR:-/home/agent}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TASK_ID="${TASK_ID:-agent-user-runtime-smoke}"
VTRM_LOG_DIR="${VTRM_LOG_DIR:-/var/log/sandbox/vtrm}"
VTRM_APPROVAL_DIR="${VTRM_APPROVAL_DIR:-/var/lib/agentos/approvals}"
VTRM_DB_PATH="${VTRM_DB_PATH:-/var/lib/agentos/agent.db}"
PROBE_FILE="${PROBE_FILE:-/workspace/agent_user_runtime_smoke.txt}"
APPROVAL_PROBE_TARGET="${APPROVAL_PROBE_TARGET:-/protected/agent_user_runtime_probe.txt}"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

pass() {
  echo "[PASS] $*"
}

print_section() {
  echo
  echo "==================== $* ===================="
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

if [ "$(id -u)" -eq 0 ] && [ "${1:-}" != "--as-agent" ]; then
  exec su - "$AGENT_USER" -c "bash $AGENT_DIR/test_agent_user_runtime.sh --as-agent"
fi

[ "$(id -un)" = "$AGENT_USER" ] || fail "must run as $AGENT_USER (or run as root and let the script re-exec)"

need_cmd "$PYTHON_BIN"
need_cmd sqlite3

cd "$AGENT_DIR"
export PYTHONPATH="$AGENT_DIR:${PYTHONPATH:-}"
export TASK_ID
export VTRM_LOG_DIR
export VTRM_APPROVAL_DIR
export VTRM_DB_PATH
export PROBE_FILE
export APPROVAL_PROBE_TARGET

print_section "Runtime identity"
echo "user=$(id -un)"
echo "uid=$(id -u)"
echo "gid=$(id -g)"
echo "AGENT_DIR=$AGENT_DIR"
echo "VTRM_LOG_DIR=$VTRM_LOG_DIR"
echo "VTRM_APPROVAL_DIR=$VTRM_APPROVAL_DIR"
echo "VTRM_DB_PATH=$VTRM_DB_PATH"

print_section "Writable path checks"
[ -d "$VTRM_LOG_DIR" ] || fail "missing VTRM log dir: $VTRM_LOG_DIR"
[ -d "$VTRM_APPROVAL_DIR" ] || fail "missing approval dir: $VTRM_APPROVAL_DIR"
[ -w "$VTRM_LOG_DIR" ] || fail "agent cannot write VTRM log dir: $VTRM_LOG_DIR"
[ -w "$VTRM_APPROVAL_DIR/pending" ] || fail "agent cannot write approval pending dir"
[ -w "$(dirname "$VTRM_DB_PATH")" ] || fail "agent cannot write DB parent dir: $(dirname "$VTRM_DB_PATH")"
[ -w /workspace ] || fail "agent cannot write /workspace"
pass "runtime directories are writable"

print_section "Reset probe artifacts"
rm -f "$PROBE_FILE"
rm -f "$VTRM_LOG_DIR"/vtrm_audit.jsonl "$VTRM_LOG_DIR"/vtrm_deny.jsonl "$VTRM_LOG_DIR"/vtrm_approval.jsonl
rm -f "$VTRM_APPROVAL_DIR"/pending/*.json "$VTRM_APPROVAL_DIR"/approved/*.json "$VTRM_APPROVAL_DIR"/used/*.json "$VTRM_APPROVAL_DIR"/tokens/*.json 2>/dev/null || true

RESULT_JSON="$("$PYTHON_BIN" - <<'PY'
import json
import os

from vtrm import VTRMCore

task_id = os.environ["TASK_ID"]
probe_file = os.environ["PROBE_FILE"]
approval_target = os.environ["APPROVAL_PROBE_TARGET"]

capabilities = {
    "fs.read.workspace",
    "fs.read.readonly",
    "fs.read.secret",
    "fs.read.protected",
    "fs.write.workspace",
    "network.send.trusted_internal",
    "network.send.external",
    "db.read.readonly",
    "db.read.secret",
    "db.insert.mutable",
    "db.update.mutable",
}

vtrm = VTRMCore(
    agent_capabilities=capabilities,
    allowed_external_sinks=set(),
    audit_log_dir=os.environ["VTRM_LOG_DIR"],
    approval_store_dir=os.environ["VTRM_APPROVAL_DIR"],
)

allow_req = {
    "schema_version": "0.1",
    "task_id": "ignored-by-runtime",
    "request_id": "agent-user-allow-001",
    "subject": "agent-runtime-smoke",
    "tool": "fs.write",
    "args": {"path": probe_file, "content": "agent user runtime ok"},
    "content_label": "public",
    "capability_required": "fs.write.workspace",
}
allow_ok, allow_result = vtrm.execute(allow_req, runtime_task_id=task_id, step_index=1)

approval_req = {
    "schema_version": "0.1",
    "task_id": "ignored-by-runtime",
    "request_id": "agent-user-approval-001",
    "subject": "agent-runtime-smoke",
    "tool": "fs.write",
    "args": {"path": approval_target, "content": "should require approval"},
    "content_label": "public",
    "capability_required": "fs.write.protected",
}
approval_ok, approval_result = vtrm.execute(approval_req, runtime_task_id=task_id, step_index=2)

payload = {
    "allow_ok": allow_ok,
    "allow_result": str(allow_result),
    "approval_ok": approval_ok,
    "approval_result": str(approval_result),
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"
export RESULT_JSON

print_section "Probe results"
echo "$RESULT_JSON"

ALLOW_OK="$("$PYTHON_BIN" - <<'PY'
import json, os
print("1" if json.loads(os.environ["RESULT_JSON"])["allow_ok"] else "0")
PY
)"
APPROVAL_RESULT="$("$PYTHON_BIN" - <<'PY'
import json, os
print(json.loads(os.environ["RESULT_JSON"])["approval_result"])
PY
)"
[ "$ALLOW_OK" = "1" ] || fail "fs.write under /workspace did not succeed as agent"
[ -f "$PROBE_FILE" ] || fail "probe file was not created: $PROBE_FILE"
grep -q "agent user runtime ok" "$PROBE_FILE" || fail "probe file content mismatch"
pass "agent can execute allowed fs.write through VTRM"

[ -f "$VTRM_LOG_DIR/vtrm_audit.jsonl" ] || fail "audit log was not created"
grep -q "\"task_id\":\"$TASK_ID\"" "$VTRM_LOG_DIR"/vtrm_audit.jsonl || fail "audit log missing runtime task id"
pass "agent can write VTRM audit logs"

case "$APPROVAL_RESULT" in
  *PENDING_APPROVAL* ) ;;
  * ) fail "protected write did not produce approval-required result: $APPROVAL_RESULT" ;;
esac

PENDING_COUNT="$(find "$VTRM_APPROVAL_DIR/pending" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
[ "${PENDING_COUNT:-0}" -ge 1 ] || fail "approval store did not record a pending approval"
pass "agent can write approval requests"

mkdir -p "$(dirname "$VTRM_DB_PATH")"
sqlite3 "$VTRM_DB_PATH" "CREATE TABLE IF NOT EXISTS __agent_user_runtime_probe (id INTEGER PRIMARY KEY, note TEXT);"
sqlite3 "$VTRM_DB_PATH" "DELETE FROM __agent_user_runtime_probe;"
sqlite3 "$VTRM_DB_PATH" "INSERT INTO __agent_user_runtime_probe(note) VALUES ('ok');"
DB_NOTE="$(sqlite3 "$VTRM_DB_PATH" "SELECT note FROM __agent_user_runtime_probe LIMIT 1;")"
sqlite3 "$VTRM_DB_PATH" "DROP TABLE __agent_user_runtime_probe;"
[ "$DB_NOTE" = "ok" ] || fail "agent could not read/write the VTRM DB path via sqlite3 CLI"
pass "agent can write the VTRM DB path"

print_section "Summary"
echo "[PASS] agent user runtime smoke test succeeded"
