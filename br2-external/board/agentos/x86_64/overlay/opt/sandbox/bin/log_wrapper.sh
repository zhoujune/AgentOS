#!/bin/sh
#
# log_wrapper.sh - AgentOS log viewer wrapper
#

TRACE_DIR="${TRACE_DIR:-/var/log/sandbox/trace}"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"

log_jsonl() {
    local event="$1"
    shift
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    mkdir -p "$TRACE_DIR" 2>/dev/null || true
    printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"$*\"}" >> "$TRACE_JSONL" 2>/dev/null || true
}

do_tail() {
    local file="$1"
    local lines="${2:-50}"

    if [ -z "$file" ]; then
        echo "Usage: log_wrapper.sh tail <file> [lines]"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    tail -n "$lines" "$file"
}

do_head() {
    local file="$1"
    local lines="${2:-50}"

    if [ -z "$file" ]; then
        echo "Usage: log_wrapper.sh head <file> [lines]"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    head -n "$lines" "$file"
}

do_grep() {
    local pattern="$1"
    local file="$2"
    local opts="${3:--i}"

    if [ -z "$pattern" ]; then
        echo "Usage: log_wrapper.sh grep <pattern> [file] [opts]"
        return 1
    fi

    if [ -z "$file" ]; then
        echo "ERROR: file required for grep"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    grep $opts "$pattern" "$file"
}

do_watch() {
    local file="$1"
    local pattern="$2"

    if [ -z "$file" ]; then
        echo "Usage: log_wrapper.sh watch <file> [pattern]"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    if command -v tail >/dev/null 2>&1; then
        if [ -n "$pattern" ]; then
            tail -f "$file" | grep --line-buffered "$pattern"
        else
            tail -f "$file"
        fi
    else
        echo "tail command not available"
        return 1
    fi
}

do_journal() {
    local service="$1"
    local lines="${2:-50}"

    if [ -z "$service" ]; then
        echo "Usage: log_wrapper.sh journal <service> [lines]"
        return 1
    fi

    if command -v journalctl >/dev/null 2>&1; then
        journalctl -u "$service" -n "$lines" --no-pager
    else
        echo "journalctl not available"
        return 1
    fi
}

do_errors() {
    local file="$1"

    if [ -z "$file" ]; then
        echo "Usage: log_wrapper.sh errors <file>"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    echo "=== Errors and Warnings in $file ==="
    grep -i -E "error|warn|fail|exception|fatal" "$file" | tail -30
}

do_timestamps() {
    local file="$1"
    local pattern="${2:-}"

    if [ -z "$file" ]; then
        echo "Usage: log_wrapper.sh timestamps <file> [pattern]"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    if [ -n "$pattern" ]; then
        grep -E "^\[?[0-9]{4}-[0-9]{2}-[0-9]{2}" "$file" | grep "$pattern" | tail -50
    else
        grep -E "^\[?[0-9]{4}-[0-9]{2}-[0-9]{2}" "$file" | tail -50
    fi
}

do_list() {
    echo "=== Log Files ==="
    find /var/log -type f 2>/dev/null | head -30 || echo "Cannot access /var/log"
    echo ""
    echo "=== Common Logs ==="
    for f in /var/log/syslog /var/log/messages /var/log/dmesg /var/log/kern.log; do
        if [ -f "$f" ]; then
            echo "$f ($(wc -l < "$f") lines)"
        fi
    done
}

do_follow() {
    local file="$1"

    if [ -z "$file" ]; then
        echo "Usage: log_wrapper.sh follow <file>"
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "File not found: $file"
        return 1
    fi

    tail -n 100 -f "$file"
}

usage() {
    echo "Usage: log_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  tail <file> [lines]      - Show last lines"
    echo "  head <file> [lines]     - Show first lines"
    echo "  grep <pat> <file>       - Search pattern"
    echo "  errors <file>            - Show errors/warnings"
    echo "  timestamps <file> [pat] - Show log entries by time"
    echo "  journal <svc> [lines]   - Systemd journal"
    echo "  watch <file> [pattern]  - Watch file live"
    echo "  follow <file>          - Follow file (tail -f)"
    echo "  list                    - List available logs"
    echo ""
    echo "Examples:"
    echo "  log_wrapper.sh tail /var/log/syslog 100"
    echo "  log_wrapper.sh errors /var/log/syslog"
    echo "  log_wrapper.sh journal nginx 50"
}

main() {
    [ $# -eq 0 ] && { usage; exit 0; }

    local cmd="$1"
    shift

    log_jsonl "log_request" "command=$cmd" "args=$*"

    case "$cmd" in
        tail) do_tail "$@" ;;
        head) do_head "$@" ;;
        grep|search) do_grep "$@" ;;
        errors) do_errors "$@" ;;
        timestamps) do_timestamps "$@" ;;
        journal) do_journal "$@" ;;
        watch) do_watch "$@" ;;
        follow) do_follow "$@" ;;
        list|ls) do_list ;;
        help|--help|-h) usage ;;
        *) echo "Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

main "$@"
