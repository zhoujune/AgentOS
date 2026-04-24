#!/bin/sh
#
# run_task.sh — AgentOS task execution unified entry
#
# Functions:
#   1. Unified task execution entry
#   2. Generate task_id (format: YYYYMMDDTHHMMSSZ-NNNN)
#   3. Create .log file under tasks/YYYYMMDD/
#   4. Append metadata to tasks/index.jsonl
#   5. Execute command, redirect stdout/stderr to .log file
#
# Usage:
#   run_task.sh <command> [args...]
#
# Dependencies (pure POSIX): date, mkdir, sh, awk, sed, cat, mv, printf
# Not dependent on: jq, python, flock (BusyBox ash doesn't have built-in flock support)
#

set -e

# Default working directory
DEFAULT_CWD="/workspace"

# Log root directory
LOG_ROOT="${LOG_ROOT:-/var/log/sandbox/tasks}"
INDEX="$LOG_ROOT/index.jsonl"

# ------------------------------------------------------------
# 0. Argument validation
# ------------------------------------------------------------
if [ $# -eq 0 ]; then
    echo "Usage: run_task.sh <command> [args...]" >&2
    echo "Example: run_task.sh echo hello" >&2
    exit 1
fi

# Convert command to printable string (for JSON field)
_cmd_str=""
for _arg in "$@"; do
    _quoted=$(printf '%s' "$_arg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    _cmd_str="$_cmd_str\"$_quoted\","
done
_command_json="[${_cmd_str%,}]"

# ------------------------------------------------------------
# 1. Generate task_id (atomic incrementing sequence)
# ------------------------------------------------------------
_date=$(date -u '+%Y%m%d')
_ts=$(date -u '+%Y%m%dT%H%M%SZ')
_seq_file="$LOG_ROOT/.seq.${_date}"

# Atomic sequence increment: write temp file first, then mv (same filesystem atomic operation)
_seq=$(cat "$_seq_file" 2>/dev/null || echo 0)
_seq=$((_seq + 1))
printf '%s' "$_seq" > "$LOG_ROOT/.seq.${_date}.tmp"
mv -f "$LOG_ROOT/.seq.${_date}.tmp" "$_seq_file"

_task_id="${_ts}-$(printf '%04d' "$_seq")"

# ------------------------------------------------------------
# 2. Create today's directory
# ------------------------------------------------------------
_log_dir="$LOG_ROOT/$_date"
mkdir -p "$_log_dir"

_log_path="$_log_dir/${_task_id}.log"
_log_path_relative="tasks/$_date/${_task_id}.log"

# ------------------------------------------------------------
# 3. Write index.jsonl (running status)
# ------------------------------------------------------------
_start_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
_user=$(id -nu 2>/dev/null || echo "unknown")
_cwd=$(pwd)

# Construct JSON line (pure shell, no jq)
_index_line=$(printf '{"task_id":"%s","ts":"%s","user":"%s","cwd":"%s","command":%s,"log_path":"%s","status":"running","exit_code":null}' \
    "$_task_id" "$_start_ts" "$_user" "$_cwd" "$_command_json" "$_log_path_relative")

mkdir -p "$LOG_ROOT"
printf '%s\n' "$_index_line" >> "$INDEX"

# ------------------------------------------------------------
# 4. Execute command and record stdout/stderr
# ------------------------------------------------------------
# Log file header: task metadata comments
{
    printf '# task_id: %s\n' "$_task_id"
    printf '# ts: %s\n' "$_start_ts"
    printf '# cwd: %s\n' "$_cwd"
    printf '# command: '
    printf '%s ' "$@"
    printf '\n'
    printf '+ '
    printf '%s ' "$@"
    printf '\n'
} > "$_log_path"

# Execute command: append to log file, also pass through to terminal
set +e
"$@" 2>&1 | tee -a "$_log_path"; _exit=$?
set -e

# ------------------------------------------------------------
# 5. Update index.jsonl (append new line, keep original running line)
# ------------------------------------------------------------
_end_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

if [ $_exit -eq 0 ]; then
    _status="done"
else
    if [ $_exit -ge 128 ]; then
        _status="signal"
    else
        _status="failed"
    fi
fi

_new_line=$(printf '{"task_id":"%s","ts":"%s","user":"%s","cwd":"%s","command":%s,"log_path":"%s","status":"%s","exit_code":%s}' \
    "$_task_id" "$_end_ts" "$_user" "$_cwd" "$_command_json" "$_log_path_relative" "$_status" "$_exit")

printf '%s\n' "$_new_line" >> "$INDEX"

# ------------------------------------------------------------
# 6. Output result summary
# ------------------------------------------------------------
echo "[task-run] task_id=$_task_id exit=$_exit log=$_log_path_relative"

exit $_exit
