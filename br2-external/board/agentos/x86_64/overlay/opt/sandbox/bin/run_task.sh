#!/bin/sh
#
# run_task.sh — AgentOS 任务执行统一入口
#
# 功能：
#   1. 统一的任务执行入口
#   2. 生成 task_id（格式: YYYYMMDDTHHMMSSZ-NNNN）
#   3. 在 tasks/YYYYMMDD/ 下创建 .log 文件
#   4. 向 tasks/index.jsonl 追加元数据
#   5. 执行命令，stdout/stderr 重定向到 .log 文件
#
# 用法：
#   run_task.sh <command> [args...]
#
# 依赖（纯 POSIX）：date, mkdir, sh, awk, sed, cat, mv, printf
# 不依赖：jq, python, flock（BusyBox ash 内置不支持 flock）
#

set -e

# 默认工作目录
DEFAULT_CWD="/workspace"

# 日志根目录
LOG_ROOT="${LOG_ROOT:-/var/log/sandbox/tasks}"
INDEX="$LOG_ROOT/index.jsonl"

# ------------------------------------------------------------
# 0. 参数校验
# ------------------------------------------------------------
if [ $# -eq 0 ]; then
    echo "Usage: run_task.sh <command> [args...]" >&2
    echo "Example: run_task.sh echo hello" >&2
    exit 1
fi

# 将 command 整体转为可打印字符串（用于 JSON 字段）
_cmd_str=""
for _arg in "$@"; do
    _quoted=$(printf '%s' "$_arg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    _cmd_str="$_cmd_str\"$_quoted\","
done
_command_json="[${_cmd_str%,}]"

# ------------------------------------------------------------
# 1. 生成 task_id（原子递增序号）
# ------------------------------------------------------------
_date=$(date -u '+%Y%m%d')
_ts=$(date -u '+%Y%m%dT%H%M%SZ')
_seq_file="$LOG_ROOT/.seq.${_date}"

# 序号原子递增：先写临时文件，再 mv（同文件系统原子操作）
_seq=$(cat "$_seq_file" 2>/dev/null || echo 0)
_seq=$((_seq + 1))
printf '%s' "$_seq" > "$LOG_ROOT/.seq.${_date}.tmp"
mv -f "$LOG_ROOT/.seq.${_date}.tmp" "$_seq_file"

_task_id="${_ts}-$(printf '%04d' "$_seq")"

# ------------------------------------------------------------
# 2. 创建当日目录
# ------------------------------------------------------------
_log_dir="$LOG_ROOT/$_date"
mkdir -p "$_log_dir"

_log_path="$_log_dir/${_task_id}.log"
_log_path_relative="tasks/$_date/${_task_id}.log"

# ------------------------------------------------------------
# 3. 写 index.jsonl（running 状态）
# ------------------------------------------------------------
_start_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
_user=$(id -nu 2>/dev/null || echo "unknown")
_cwd=$(pwd)

# 构造 JSON 行（纯 shell，无 jq）
_index_line=$(printf '{"task_id":"%s","ts":"%s","user":"%s","cwd":"%s","command":%s,"log_path":"%s","status":"running","exit_code":null}' \
    "$_task_id" "$_start_ts" "$_user" "$_cwd" "$_command_json" "$_log_path_relative")

mkdir -p "$LOG_ROOT"
printf '%s\n' "$_index_line" >> "$INDEX"

# ------------------------------------------------------------
# 4. 执行命令并记录 stdout/stderr
# ------------------------------------------------------------
# 日志文件头部：任务元数据注释
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

# 执行命令：追加到日志文件，同时透传到终端
set +e
"$@" 2>&1 | tee -a "$_log_path"; _exit=$?
set -e

# ------------------------------------------------------------
# 5. 更新 index.jsonl（追加新行，保留原 running 行）
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
# 6. 输出结果摘要
# ------------------------------------------------------------
echo "[task-run] task_id=$_task_id exit=$_exit log=$_log_path_relative"

exit $_exit
