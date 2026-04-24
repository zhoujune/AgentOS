#!/bin/sh
#
# fs_wrapper.sh — AgentOS filesystem access control wrapper (B-line version)
#
#   - Remove standalone policy decision logic
#   - Only serve as pure execution backend
#   - Policy decisions are handled by VTRM
#   - Wrapper only executes VTRM-approved operations
#
# Usage (B-line):
#   fs_wrapper.sh execute <action> <path> [content]
#   Only accepts VTRM-approved operations
#
# Events (trace.jsonl):
#   fs_execute — Execute operation (VTRM-approved)
#   fs_result  — Execute result
#

set -e

TRACE_DIR="${TRACE_DIR:-/var/log/sandbox/trace}"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"

log_jsonl() {
    local event="$1"
    shift
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    mkdir -p "$TRACE_DIR" 2>/dev/null || true

    case "$event" in
        fs_execute)
            printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"actor\":\"$(id -nu)\",\"action\":\"$1\",\"path\":\"$2\",\"status\":\"$3\"}" >> "$TRACE_JSONL"
            ;;
        fs_result)
            printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"actor\":\"$(id -nu)\",\"action\":\"$1\",\"path\":\"$2\",\"exit\":\"$3\",\"reason\":\"$4\"}" >> "$TRACE_JSONL"
            ;;
    esac
}

do_execute() {
    local action="$1"
    local path="$2"
    local content="$3"

    # Normalize path
    case "$path" in
        /*) _path="$path" ;;
        *)  _path="/$path" ;;
    esac

    # Log execution start
    log_jsonl fs_execute "$action" "$_path" "started"

    # Execute operation (VTRM has verified permissions)
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
            mkdir -p "$(dirname "$_path")" 2>/dev/null || true
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
        *)
            echo "ERROR: unknown action: $action" >&2
            log_jsonl fs_result "$action" "$_path" "1" "unknown action"
            return 1
            ;;
    esac
}

do_version() {
    echo "fs_wrapper.sh v2.0.0-b (B-line: pure execution backend)"
}

do_help() {
    echo "Usage: fs_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands (B-line mode):"
    echo "  execute <action> <path> [content]  - Execute VTRM-approved operation"
    echo "  version                              - Show version"
    echo "  help                                 - Show this help"
    echo ""
    echo "Note: Policy decisions are now handled by VTRM."
    echo "      This wrapper only executes VTRM-approved operations."
}

usage() {
    echo "Usage: fs_wrapper.sh execute <action> <path> [content]" >&2
    echo "Actions: read, write, list" >&2
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
        execute)
            # B-line: execute subcommand
            # Format: fs_wrapper.sh execute <action> <path> [content]
            shift
            local action="${1:-}"
            local path="${2:-}"
            if [ -z "$action" ] || [ -z "$path" ]; then
                usage
                exit 1
            fi
            shift 2
            local content="${*:-}"
            do_execute "$action" "$path" "$content"
            ;;
        # Keep legacy format for compatibility (deprecated in B-line)
        read|write|list)
            # Direct execution (legacy compatibility)
            # B-line should use execute subcommand
            local action="$cmd"
            shift
            local path="${1:-}"
            if [ -z "$path" ]; then
                usage
                exit 1
            fi
            shift
            local content="${*:-}"
            do_execute "$action" "$path" "$content"
            ;;
        *)
            echo "ERROR: unknown command: $cmd" >&2
            do_help
            exit 1
            ;;
    esac
}

main "$@"
