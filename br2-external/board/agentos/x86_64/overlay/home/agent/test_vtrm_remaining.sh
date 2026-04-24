#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Second round tests for VTRM:
# Approval + Absolute Deny + Schema Invalid + Fail-Closed
#
# This script follows the same bridge contract as agent_runner / LLM Proxy.
# Deterministic coverage strategy:
# - B1/C1/F1/F2/F3/G use agent_runner + bridge inbox/outbox
# - E and F4 use direct VTRM checks because the current runner path cannot
#   deterministically express those cases end-to-end
# ============================================================

# ===== Config =====
AGENT_DIR="${AGENT_DIR:-/home/agent}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"

ARTIFACT_ROOT="${ARTIFACT_ROOT:-/workspace/vtrm_remaining_llm/${RUN_ID}}"
BRIDGE_DIR="${AGENT_BRIDGE_DIR:-${ARTIFACT_ROOT}/agent_bridge}"
TRANSCRIPT_LOG="${AGENT_TRANSCRIPT_LOG:-${ARTIFACT_ROOT}/transcript.jsonl}"
RUNNER_DEBUG_LOG="${RUNNER_DEBUG_LOG:-${ARTIFACT_ROOT}/runner.log}"

VTRM_LOG_DIR="${VTRM_LOG_DIR:-/var/log/sandbox/vtrm}"
VTRM_APPROVAL_DIR="${VTRM_APPROVAL_DIR:-/var/lib/agentos/approvals}"
VTRM_DB_PATH="${VTRM_DB_PATH:-/var/lib/agentos/agent.db}"

# Use a path that can never behave like a writable directory. This is much
# more reliable than chmod-based tricks in privileged VM environments.
FAIL_CLOSED_AUDIT_DIR="${FAIL_CLOSED_AUDIT_DIR:-/dev/full}"

B1_TASK_ID="test-vtrm-remaining-b1-${RUN_ID}"
C1_TASK_ID="test-vtrm-remaining-c1-${RUN_ID}"
F1_TASK_ID="test-vtrm-remaining-f1-${RUN_ID}"
F2_TASK_ID="test-vtrm-remaining-f2-${RUN_ID}"
F3_TASK_ID="test-vtrm-remaining-f3-${RUN_ID}"
G_TASK_ID="test-vtrm-remaining-g-${RUN_ID}"

B1_SECRET_FILE="/secrets/secret_approval_${RUN_ID}.txt"
G_TARGET_FILE="/workspace/fail_closed_${RUN_ID}.txt"


fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

pass() {
  echo "[PASS] $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

print_section() {
  echo
  echo "==================== $* ===================="
}

wait_for_file() {
  local path="$1"
  local timeout="${2:-30}"
  local i=0
  while [ "$i" -lt "$timeout" ]; do
    [ -e "$path" ] && return 0
    sleep 1
    i=$((i + 1))
  done
  return 1
}

write_llm_response() {
  local task_id="$1"
  local step="$2"
  local assistant_text="$3"
  local request_id
  local outbox_path
  local inbox_path

  request_id="$(printf 'llm-%s-%03d' "$task_id" "$step")"
  outbox_path="${BRIDGE_DIR}/outbox/${request_id}.json"
  inbox_path="${BRIDGE_DIR}/inbox/${request_id}.json"

  wait_for_file "$outbox_path" 60 || fail "timeout waiting for outbox: $outbox_path"

  REQUEST_ID="$request_id" INBOX_PATH="$inbox_path" ASSISTANT_TEXT="$assistant_text" "$PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime, timezone

payload = {
    "request_id": os.environ["REQUEST_ID"],
    "ts": datetime.now(timezone.utc).isoformat(),
    "ok": True,
    "assistant_text": os.environ["ASSISTANT_TEXT"],
    "raw_response": {"finish_reason": "stop"},
    "error": None,
}

with open(os.environ["INBOX_PATH"], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
PY
}

start_agent() {
  local task_id="$1"
  local task_text="$2"
  local result_file="$3"
  local audit_dir="${4:-$VTRM_LOG_DIR}"

  (
    export PYTHONPATH="$AGENT_DIR:${PYTHONPATH:-}"
    export AGENT_BRIDGE_DIR="$BRIDGE_DIR"
    export AGENT_TRANSCRIPT_LOG="$TRANSCRIPT_LOG"
    export VTRM_LOG_DIR="$audit_dir"
    export VTRM_APPROVAL_DIR="$VTRM_APPROVAL_DIR"
    export VTRM_DB_PATH="$VTRM_DB_PATH"
    cd "$AGENT_DIR"
    "$PYTHON_BIN" agent_runner.py --task-id "$task_id" --task "$task_text"
  ) >"$result_file" 2>>"$RUNNER_DEBUG_LOG" &

  LAST_AGENT_PID="$!"
}

wait_agent() {
  local pid="$1"
  wait "$pid" || fail "agent_runner exited non-zero (pid=$pid)"
}

dump_task_debug() {
  local task_id="$1"

  print_section "Debug for $task_id"

  echo "[DEBUG] transcript entries"
  if [ -f "$TRANSCRIPT_LOG" ]; then
    grep '"task_id":"'"$task_id"'"' "$TRANSCRIPT_LOG" || echo "[DEBUG] no transcript entries found"
  else
    echo "[DEBUG] transcript log not found: $TRANSCRIPT_LOG"
  fi

  echo
  echo "[DEBUG] bridge response files"
  local found=0
  local f
  for f in "$BRIDGE_DIR"/done/llm-"$task_id"-*.json "$BRIDGE_DIR"/inbox/llm-"$task_id"-*.json "$BRIDGE_DIR"/error/llm-"$task_id"-*.json; do
    [ -e "$f" ] || continue
    found=1
    echo "--- $f ---"
    cat "$f"
    echo
  done
  [ "$found" -eq 1 ] || echo "[DEBUG] no bridge response files found"

  echo
  echo "[DEBUG] VTRM audit entries"
  found=0
  for f in "$VTRM_LOG_DIR"/*.jsonl; do
    [ -f "$f" ] || continue
    if grep -q '"task_id":"'"$task_id"'"' "$f"; then
      found=1
      echo "--- $f ---"
      grep '"task_id":"'"$task_id"'"' "$f"
    fi
  done
  [ "$found" -eq 1 ] || echo "[DEBUG] no VTRM audit entries found"

  echo
  echo "[DEBUG] recent runner log tail"
  if [ -f "$RUNNER_DEBUG_LOG" ]; then
    tail -n 100 "$RUNNER_DEBUG_LOG"
  else
    echo "[DEBUG] runner debug log not found: $RUNNER_DEBUG_LOG"
  fi
}

require_transcript_task() {
  local task_id="$1"
  grep -q '"task_id":"'"$task_id"'"' "$TRANSCRIPT_LOG" || {
    dump_task_debug "$task_id"
    fail "transcript missing task_id: $task_id"
  }
}

require_audit_match() {
  local task_id="$1"
  local description="$2"
  shift 2

  local found=0
  local f
  for f in "$VTRM_LOG_DIR"/*.jsonl; do
    [ -f "$f" ] || continue
    if grep -q '"task_id":"'"$task_id"'"' "$f"; then
      local ok=1
      local pattern
      for pattern in "$@"; do
        if ! grep -q "$pattern" "$f"; then
          ok=0
          break
        fi
      done
      if [ "$ok" -eq 1 ]; then
        found=1
        break
      fi
    fi
  done

  [ "$found" -eq 1 ] || {
    dump_task_debug "$task_id"
    fail "$description"
  }
}

require_approval_file_for_task() {
  local task_id="$1"
  local found=0
  local f
  for f in "$VTRM_APPROVAL_DIR"/pending/*.json; do
    [ -f "$f" ] || continue
    if grep -q "$task_id" "$f"; then
      found=1
      break
    fi
  done
  [ "$found" -eq 1 ] || {
    dump_task_debug "$task_id"
    fail "approval file not found for task_id=$task_id"
  }
}

run_two_step_agent() {
  local task_id="$1"
  local task_text="$2"
  local step1="$3"
  local step2="$4"
  local result_file="$5"
  local audit_dir="${6:-$VTRM_LOG_DIR}"

  start_agent "$task_id" "$task_text" "$result_file" "$audit_dir"
  write_llm_response "$task_id" 1 "$step1"
  write_llm_response "$task_id" 2 "$step2"
  wait_agent "$LAST_AGENT_PID"
}

# ===== Preflight =====
need_cmd "$PYTHON_BIN"
need_cmd grep
need_cmd tail
need_cmd chmod
need_cmd mkdir

mkdir -p "$ARTIFACT_ROOT" "$BRIDGE_DIR"/inbox "$BRIDGE_DIR"/outbox "$BRIDGE_DIR"/done "$BRIDGE_DIR"/error
mkdir -p /var/log/sandbox/agent "$VTRM_LOG_DIR" "$VTRM_APPROVAL_DIR"/pending "$VTRM_APPROVAL_DIR"/approved "$VTRM_APPROVAL_DIR"/used "$VTRM_APPROVAL_DIR"/tokens /var/lib/agentos /workspace /secrets /protected
chmod 777 /var/log/sandbox/agent /workspace || true
chmod 755 /secrets /protected || true

print_section "Artifacts"
echo "RUN_ID=$RUN_ID"
echo "ARTIFACT_ROOT=$ARTIFACT_ROOT"
echo "BRIDGE_DIR=$BRIDGE_DIR"
echo "TRANSCRIPT_LOG=$TRANSCRIPT_LOG"
echo "RUNNER_DEBUG_LOG=$RUNNER_DEBUG_LOG"
echo "VTRM_LOG_DIR=$VTRM_LOG_DIR"
echo "VTRM_APPROVAL_DIR=$VTRM_APPROVAL_DIR"
echo "VTRM_DB_PATH=$VTRM_DB_PATH"

# ============================================================
# B1: Secret file read triggers approval_required
# ============================================================
print_section "B1: Secret file read triggers approval_required"
echo "secret data that needs approval" > "$B1_SECRET_FILE"
chmod 600 "$B1_SECRET_FILE" || true

B1_STEP1='{"schema_version":"0.1","task_id":"task-b1","request_id":"req-b1-001","subject":"agent-default","tool":"fs.read","args":{"path":"'"$B1_SECRET_FILE"'"},"content_label":"public","capability_required":"fs.read.secret"}'
B1_STEP2='{"tool":"final","answer":"Task finished: secret file read requires approval."}'
B1_RESULT="${ARTIFACT_ROOT}/${B1_TASK_ID}.json"

run_two_step_agent \
  "$B1_TASK_ID" \
  "Read ${B1_SECRET_FILE} and then finish the task." \
  "$B1_STEP1" \
  "$B1_STEP2" \
  "$B1_RESULT"

require_transcript_task "$B1_TASK_ID"
require_audit_match \
  "$B1_TASK_ID" \
  "B1 should log approval_required with secret/high for fs.read" \
  '"decision":"approval_required"' \
  '"tool":"fs.read"' \
  '"inferred_label":"secret/high"'
require_approval_file_for_task "$B1_TASK_ID"
pass "B1 secret file read correctly triggers approval_required"

# ============================================================
# C1: db.read on secrets table triggers approval_required
# ============================================================
print_section "C1: db.read on secrets table triggers approval_required"

C1_STEP1='{"schema_version":"0.1","task_id":"task-c1","request_id":"req-c1-001","subject":"agent-default","tool":"db.read","args":{"table":"secrets","key":"remaining-secret-key"},"content_label":"public","capability_required":"db.read.secret"}'
C1_STEP2='{"tool":"final","answer":"Task finished: db.read on secrets requires approval."}'
C1_RESULT="${ARTIFACT_ROOT}/${C1_TASK_ID}.json"

run_two_step_agent \
  "$C1_TASK_ID" \
  "Read key remaining-secret-key from table secrets and then finish the task." \
  "$C1_STEP1" \
  "$C1_STEP2" \
  "$C1_RESULT"

require_transcript_task "$C1_TASK_ID"
require_audit_match \
  "$C1_TASK_ID" \
  "C1 should log approval_required with secret/high for db.read" \
  '"decision":"approval_required"' \
  '"tool":"db.read"' \
  '"inferred_label":"secret/high"'
require_approval_file_for_task "$C1_TASK_ID"
pass "C1 db.read on secrets correctly triggers approval_required"

# ============================================================
# E: Absolute Deny — secret/high -> external_untrusted
# Note: checked directly against NetworkPolicy because the current runner path
# does not propagate secret/high into network.send labels.
# ============================================================
print_section "E: Absolute Deny - secret/high -> external_untrusted"
E_OUTPUT="$("$PYTHON_BIN" - <<'PY'
import sys

sys.path.insert(0, "/home/agent")
from vtrm import Label, NetworkPolicy

result = NetworkPolicy().check("https://evil.example/collect", Label.SECRET_HIGH)
if result.decision.value != "deny":
    print(f"FAIL: expected deny, got {result.decision.value} ({result.reason})")
    sys.exit(1)
if result.rule != "secret_to_external":
    print(f"FAIL: expected rule secret_to_external, got {result.rule}")
    sys.exit(1)
print(result.reason)
PY
)" || fail "E absolute deny check failed"
pass "E secret/high -> external_untrusted absolute deny - ${E_OUTPUT}"

# ============================================================
# F: Schema Invalid Tests
# F1/F2/F3 use agent_runner + bridge.
# F4 uses direct VTRM evaluate because agent_runner rejects unknown tools
# before they enter the typed-request path.
# ============================================================
print_section "F1: Schema invalid missing args"
F1_STEP1='{"task_id":"model-f1","request_id":"req-f1-001","subject":"agent-default","tool":"fs.read"}'
F1_STEP2='{"tool":"final","answer":"Schema invalid test finished."}'
F1_RESULT="${ARTIFACT_ROOT}/${F1_TASK_ID}.json"
run_two_step_agent \
  "$F1_TASK_ID" \
  "Issue a file read request and then finish the task." \
  "$F1_STEP1" \
  "$F1_STEP2" \
  "$F1_RESULT"
require_transcript_task "$F1_TASK_ID"
require_audit_match \
  "$F1_TASK_ID" \
  "F1 should log deny/skipped for missing args" \
  '"decision":"deny"' \
  '"status":"skipped"' \
  '"tool":"fs.read"'
pass "F1 schema invalid missing args correctly denied"

print_section "F2: Schema invalid missing path"
F2_STEP1='{"schema_version":"0.1","task_id":"model-f2","request_id":"req-f2-001","subject":"agent-default","tool":"fs.read","args":{}}'
F2_STEP2='{"tool":"final","answer":"Schema invalid test finished."}'
F2_RESULT="${ARTIFACT_ROOT}/${F2_TASK_ID}.json"
run_two_step_agent \
  "$F2_TASK_ID" \
  "Issue a file read request and then finish the task." \
  "$F2_STEP1" \
  "$F2_STEP2" \
  "$F2_RESULT"
require_transcript_task "$F2_TASK_ID"
require_audit_match \
  "$F2_TASK_ID" \
  "F2 should log deny/skipped for missing path" \
  '"decision":"deny"' \
  '"status":"skipped"' \
  '"tool":"fs.read"'
pass "F2 schema invalid missing path correctly denied"

print_section "F3: Schema invalid wrong args type"
F3_STEP1='{"schema_version":"0.1","task_id":"model-f3","request_id":"req-f3-001","subject":"agent-default","tool":"fs.read","args":"not-a-dict"}'
F3_STEP2='{"tool":"final","answer":"Schema invalid test finished."}'
F3_RESULT="${ARTIFACT_ROOT}/${F3_TASK_ID}.json"
run_two_step_agent \
  "$F3_TASK_ID" \
  "Issue a file read request and then finish the task." \
  "$F3_STEP1" \
  "$F3_STEP2" \
  "$F3_RESULT"
require_transcript_task "$F3_TASK_ID"
require_audit_match \
  "$F3_TASK_ID" \
  "F3 should log deny/skipped for wrong args type" \
  '"decision":"deny"' \
  '"status":"skipped"' \
  '"tool":"fs.read"'
pass "F3 schema invalid wrong args type correctly denied"

print_section "F4: Schema invalid unknown tool"
F4_OUTPUT="$("$PYTHON_BIN" - <<'PY'
import sys

sys.path.insert(0, "/home/agent")
from vtrm import VTRMCore

vtrm = VTRMCore(
    agent_capabilities={
        "fs.read.workspace",
        "fs.read.readonly",
        "fs.read.secret",
        "fs.read.protected",
        "fs.write.workspace",
        "network.send.trusted_internal",
        "network.send.external",
        "db.read.readonly",
        "db.read.secret",
        "db.read.audit",
        "db.insert.mutable",
        "db.update.mutable",
    },
    allowed_external_sinks=set(),
    audit_log_dir="/var/log/sandbox/vtrm",
    approval_store_dir="/var/lib/agentos/approvals",
)

request = {
    "task_id": "test-vtrm-remaining-f4",
    "request_id": "req-f4-001",
    "subject": "agent.default",
    "tool": "unknown.tool",
    "args": {},
}
decision = vtrm.evaluate(request, runtime_task_id="test-vtrm-remaining-f4", step_index=1)
if decision.decision != "deny":
    print(f"FAIL: expected deny, got {decision.decision} ({decision.reason})")
    sys.exit(1)
print(decision.reason)
PY
)" || fail "F4 unknown tool check failed"
pass "F4 schema invalid unknown tool correctly denied - ${F4_OUTPUT}"

# ============================================================
# G: Audit Fail-Closed Tests (simplified)
# Uses agent_runner + bridge with a read-only audit directory to force
# mutation fail-closed without deleting any existing files.
# ============================================================
print_section "G: Audit Fail-Closed Tests"

G_STEP1='{"schema_version":"0.1","task_id":"task-g","request_id":"req-g-001","subject":"agent-default","tool":"fs.write","args":{"path":"'"$G_TARGET_FILE"'","content":"should not be written"},"content_label":"public","capability_required":"fs.write.workspace"}'
G_STEP2='{"tool":"final","answer":"Task finished: fail-closed blocked the write."}'
G_RESULT="${ARTIFACT_ROOT}/${G_TASK_ID}.json"

run_two_step_agent \
  "$G_TASK_ID" \
  "Write should not be written to ${G_TARGET_FILE} and then finish the task." \
  "$G_STEP1" \
  "$G_STEP2" \
  "$G_RESULT" \
  "$FAIL_CLOSED_AUDIT_DIR"

require_transcript_task "$G_TASK_ID"
grep -q 'fail-closed' "$TRANSCRIPT_LOG" || {
  dump_task_debug "$G_TASK_ID"
  fail "G transcript should mention fail-closed"
}
[ ! -e "$G_TARGET_FILE" ] || {
  dump_task_debug "$G_TASK_ID"
  fail "G fail-closed test unexpectedly created ${G_TARGET_FILE}"
}
pass "G audit fail-closed correctly blocked mutation"

print_section "Summary"
pass "B1/C1/F1/F2/F3/G completed through agent_runner + bridge"
pass "E/F4 completed through direct VTRM checks where runner path is not expressive enough"
