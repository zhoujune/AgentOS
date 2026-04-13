#!/bin/sh
#
# fs_wrapper.sh — AgentOS 文件系统访问控制包装器
#
# 功能：
#   1. 统一的文件系统操作入口
#   2. 路径策略控制
#   3. 记录清晰的 fs_request + fs_result trace
#
# 用法：
#   fs_wrapper.sh "<action> <path> [content]"
#   例: fs_wrapper.sh "read /workspace/config.json"
#       fs_wrapper.sh "write /workspace/out.txt hello"
#       fs_wrapper.sh "list /workspace"
#
# 事件（trace.jsonl）：
#   fs_request — 文件操作请求
#   fs_result  — 文件操作结果
#
# 路径策略：
#   /workspace : read ✓ write ✓ list ✓
#   /protected : read ✓ write ✗ list ✓
#   /secrets   : read ✗ write ✗ list ✗
#   其他路径    : 默认拒绝
#

set -e

TRACE_DIR="${TRACE_DIR:-/var/log/sandbox/trace}"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"

log_jsonl() {
    local event="$1"
    shift
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    mkdir -p "$TRACE_DIR"

    case "$event" in
        fs_request)
            # event, ts, actor, action, path, decision
            printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"actor\":\"$(id -nu)\",\"action\":\"$1\",\"path\":\"$2\",\"decision\":\"$3\"}" >> "$TRACE_JSONL"
            ;;
        fs_result)
            # event, ts, actor, action, path, exit, reason
            printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"actor\":\"$(id -nu)\",\"action\":\"$1\",\"path\":\"$2\",\"exit\":\"$3\",\"reason\":\"$4\"}" >> "$TRACE_JSONL"
            ;;
    esac
}

deny() {
    local action="$1"
    local path="$2"
    local reason="$3"
    echo "ERROR: $reason" >&2
    log_jsonl fs_result "$action" "$path" "1" "$reason"
    return 1
}

policy_check() {
    local action="$1"
    local path="$2"

    # 标准化路径
    case "$path" in
        /*) _path="$path" ;;
        *)  _path="/$path" ;;
    esac

    case "$_path" in
        /workspace|/workspace/*)
            return 0
            ;;
        /protected|/protected/*)
            case "$action" in
                read|list) return 0 ;;
                write)
                    _deny_reason="write to /protected is denied"
                    return 1
                    ;;
            esac
            ;;
        *)
            _deny_reason="path '$_path' is not allowed"
            return 1
            ;;
    esac
}

do_fs() {
    local action="$1"
    local path="$2"
    local content="$3"

    # 标准化路径
    case "$path" in
        /*) _path="$path" ;;
        *)  _path="/$path" ;;
    esac

    # 策略检查
    if policy_check "$action" "$_path"; then
        log_jsonl fs_request "$action" "$_path" "allow"
    else
        log_jsonl fs_request "$action" "$_path" "deny"
        deny "$action" "$_path" "${_deny_reason:-path policy denied}"
        return 1
    fi

    # 执行操作
    case "$action" in
        read)
            if [ -f "$_path" ]; then
                cat "$_path"
                log_jsonl fs_result "$action" "$_path" "0" ""
            else
                echo "ERROR: file not found: $_path" >&2
                log_jsonl fs_result "$action" "$_path" "1" "file not found"
                return 1
            fi
            ;;
        write)
            mkdir -p "$(dirname "$_path")"
            printf '%s' "$content" > "$_path"
            log_jsonl fs_result "$action" "$_path" "0" ""
            ;;
        list)
            if [ -d "$_path" ]; then
                ls -la "$_path"
                log_jsonl fs_result "$action" "$_path" "0" ""
            else
                echo "ERROR: not a directory: $_path" >&2
                log_jsonl fs_result "$action" "$_path" "1" "not a directory"
                return 1
            fi
            ;;
    esac
}

do_version() {
    echo "fs_wrapper.sh v1.0.0"
    echo "Allowed paths: /workspace (read/write/list), /protected (read/list)"
}

do_help() {
    echo "Usage: fs_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  read <path>              - Read file"
    echo "  write <path> <content>   - Write file"
    echo "  list <path>              - List directory"
    echo "  version                  - Show version"
    echo ""
    echo "Path Policy:"
    echo "  /workspace : full access"
    echo "  /protected : read and list only"
}

usage() {
    echo "Usage: fs_wrapper.sh \"<action> <path> [content]\"" >&2
    echo "Actions: read, write, list, version, help" >&2
    echo "Examples:" >&2
    echo "  fs_wrapper.sh \"read /workspace/config.json\"" >&2
    echo "  fs_wrapper.sh \"write /workspace/out.txt hello\"" >&2
    echo "  fs_wrapper.sh \"list /workspace\"" >&2
}

main() {
    [ $# -eq 0 ] && { usage; exit 1; }

    local cmd="$1"

    case "$cmd" in
        version|--version|-v)
            do_version
            ;;
        help|--help|-h)
            do_help
            ;;
        read|write|list)
            shift
            local path="${1:-}"
            local content="${2:-}"
            if [ -z "$path" ]; then
                usage
                exit 1
            fi
            do_fs "$cmd" "$path" "$content"
            ;;
        *)
            echo "ERROR: unknown action: $cmd" >&2
            do_help
            exit 1
            ;;
    esac
}

main "$@"
