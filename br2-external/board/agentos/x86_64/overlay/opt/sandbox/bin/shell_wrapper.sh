#!/bin/sh
#
# shell_wrapper.sh — AgentOS command execution wrapper
#
# Functions:
#   1. Unified entry: all commands go through this wrapper
#   2. Basic policy check: reject obviously dangerous command patterns
#   3. Call task-run.sh to execute actual tasks
#   4. Record clear execution trace
#
# Usage:
#   shell_wrapper.sh "<command>"
#   Example: shell_wrapper.sh "rm -rf /workspace/temp"
#
# Events (trace.jsonl):
#   shell_request — Command request (with decision: allow/deny)
#   shell_result  — Command result (with exit code and reason)
#

set -e

TRACE_DIR="${TRACE_DIR:-/var/log/sandbox/trace}"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"
RUN_TASK="${RUN_TASK:-/opt/sandbox/bin/run_task.sh}"

# Blacklisted commands
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
    # Return non-0 to indicate denial, let caller log result
    return 1
}

policy_check() {
    local cmd="$1"
    local args="$2"

    # Blacklist check
    for _deny in $DENY_LIST; do
        case "$cmd" in
            "$_deny"|*"$_deny"*)
                deny "Command '$cmd' is denied by policy" || return 1
                ;;
        esac
    done

    # Check dangerous argument patterns
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

    # Check write operation commands accessing /protected and /secrets
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

    # Parse command: first token is command, rest are arguments
    set -- $_full_cmd
    _cmd="$1"
    shift
    _args="$*"

    # Policy check (also log request)
    if policy_check "$_cmd" "$_args"; then
        log_jsonl shell_request "$_full_cmd" "allow"
    else
        log_jsonl shell_request "$_full_cmd" "deny"
        log_jsonl shell_result "$_full_cmd" "1" "policy denied"
        return 1
    fi

    # Execute
    if [ -x "$RUN_TASK" ]; then
        $RUN_TASK "$_cmd" $_args
    else
        echo "[WARN] run_task.sh not found, executing directly" >&2
        $_cmd $_args
    fi
    _exit=$?

    # Log result
    log_jsonl shell_result "$_full_cmd" "$_exit" ""
    return $_exit
}

main "$@"
