#!/bin/sh
#
# shell_wrapper.sh — AgentOS 命令执行包装器
#
# 功能：
#   1. 统一入口：所有命令都通过此包装器执行
#   2. 基础策略检查：拒绝明显危险的命令模式
#   3. 调用 task-run.sh 执行实际任务
#   4. 记录清晰的执行 trace
#
# 用法：
#   shell_wrapper.sh "<command>"
#   例: shell_wrapper.sh "rm -rf /workspace/temp"
#
# 事件（trace.jsonl）：
#   shell_request — 命令请求（带 decision: allow/deny）
#   shell_result  — 命令结果（带 exit 退出码和 reason）
#

set -e

TRACE_DIR="${TRACE_DIR:-/var/log/sandbox/trace}"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"
RUN_TASK="${RUN_TASK:-/opt/sandbox/bin/run_task.sh}"

# 黑名单命令
DENY_LIST="
reboot poweroff halt shutdown init telinit
systemctl service mount umount fdisk mkfs dd
"

log_jsonl() {
    local event="$1"
    shift
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    mkdir -p "$TRACE_DIR"

    case "$event" in
        shell_request)
            # event, ts, actor, command, decision
            printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"actor\":\"$(id -nu)\",\"command\":\"$1\",\"decision\":\"$2\"}" >> "$TRACE_JSONL"
            ;;
        shell_result)
            # event, ts, actor, command, exit, reason
            printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"actor\":\"$(id -nu)\",\"command\":\"$1\",\"exit\":\"$2\",\"reason\":\"$3\"}" >> "$TRACE_JSONL"
            ;;
    esac
}

deny() {
    local reason="$*"
    echo "ERROR: $reason" >&2
    # 返回非 0 表示拒绝，让调用者记录 result
    return 1
}

policy_check() {
    local cmd="$1"
    local args="$2"

    # 黑名单检查
    for _deny in $DENY_LIST; do
        case "$cmd" in
            "$_deny"|*"$_deny"*)
                deny "Command '$cmd' is denied by policy" || return 1
                ;;
        esac
    done

    # 检查危险参数模式
    case "$args" in
        *"--no-preserve-root"*)
            deny "Argument '--no-preserve-root' is denied" || return 1
            ;;
        *"/dev/"*)
            deny "Direct /dev access is denied" || return 1
            ;;
        *"/proc/sys/"*|*/proc/sysrq-trigger*)
            deny "Modifying /proc/sys is denied" || return 1
            ;;
        *"/sys/"*)
            deny "Direct /sys access is denied" || return 1
            ;;
        *"| su "*|*"| sudo "*)
            deny "Pipe to su/sudo is denied" || return 1
            ;;
    esac

    # 检查写操作命令访问 /protected 和 /secrets
    case "$cmd" in
        rm|mv|dd|cp|ln|chmod|chown|chgrp)
            case "$args" in
                *"/protected"*)
                    deny "Write access to /protected is denied" || return 1
                    ;;
                *"/secrets"*)
                    deny "Write access to /secrets is denied" || return 1
                    ;;
            esac
            ;;
    esac

    return 0
}

main() {
    if [ $# -eq 0 ] || [ -z "$1" ]; then
        echo "Usage: shell_wrapper.sh \"<command>\"" >&2
        echo "Example: shell_wrapper.sh \"ls -la /workspace\"" >&2
        exit 1
    fi

    _full_cmd="$1"

    # 解析命令：第一个 token 是命令，其余是参数
    set -- $_full_cmd
    _cmd="$1"
    shift
    _args="$*"

    # 策略检查（同时记录请求）
    if policy_check "$_cmd" "$_args"; then
        log_jsonl shell_request "$_full_cmd" "allow"
    else
        log_jsonl shell_request "$_full_cmd" "deny"
        log_jsonl shell_result "$_full_cmd" "1" "policy denied"
        return 1
    fi

    # 执行
    if [ -x "$RUN_TASK" ]; then
        $RUN_TASK "$_cmd" $_args
    else
        echo "[WARN] run_task.sh not found, executing directly" >&2
        $_cmd $_args
    fi
    _exit=$?

    # 记录结果
    log_jsonl shell_result "$_full_cmd" "$_exit" ""
    return $_exit
}

main "$@"
