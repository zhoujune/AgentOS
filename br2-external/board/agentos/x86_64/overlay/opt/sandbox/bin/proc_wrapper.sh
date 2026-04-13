#!/bin/sh
#
# proc_wrapper.sh - AgentOS 进程管理包装器
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

do_list() {
    local opts="${1:-}"
    echo "=== Processes ==="
    if [ -n "$opts" ]; then
        ps aux $opts 2>/dev/null || ps -ef $opts 2>/dev/null
    else
        ps aux 2>/dev/null || ps -ef 2>/dev/null
    fi | head -50
}

do_top() {
    echo "=== Top Processes ==="
    top -bn1 2>/dev/null | head -20 || ps aux --sort=-%cpu | head -20
}

do_tree() {
    echo "=== Process Tree ==="
    pstree -ap 2>/dev/null || ps axf 2>/dev/null | head -50
}

do_grep() {
    local pattern="$1"
    if [ -z "$pattern" ]; then
        echo "Usage: proc_wrapper.sh grep <pattern>"
        return 1
    fi
    echo "=== Processes matching '$pattern' ==="
    ps aux 2>/dev/null | grep -i "$pattern" | grep -v grep || true
    pgrep -fl "$pattern" 2>/dev/null || true
}

do_pids() {
    local pattern="$1"
    if [ -z "$pattern" ]; then
        echo "Usage: proc_wrapper.sh pids <pattern>"
        return 1
    fi
    pgrep "$pattern" 2>/dev/null || echo "No processes found"
}

do_kill() {
    local pid="$1"
    local sig="${2:-15}"

    if [ -z "$pid" ]; then
        echo "Usage: proc_wrapper.sh kill <pid> [signal]"
        return 1
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
        echo "Process $pid not found"
        return 1
    fi

    echo "Sending signal $sig to $pid..."
    kill -$sig "$pid" 2>&1 && echo "Signal sent" || echo "Failed"
    log_jsonl "proc_kill" "pid=$pid" "signal=$sig"
}

do_killname() {
    local name="$1"
    local sig="${2:-15}"

    if [ -z "$name" ]; then
        echo "Usage: proc_wrapper.sh killname <name> [signal]"
        return 1
    fi

    pids=$(pgrep -f "$name" 2>/dev/null)
    if [ -z "$pids" ]; then
        echo "No processes matching '$name'"
        return 1
    fi

    echo "Killing processes: $pids"
    for pid in $pids; do
        kill -$sig "$pid" 2>&1 && echo "Killed $pid" || echo "Failed to kill $pid"
    done
    log_jsonl "proc_killname" "name=$name" "signal=$sig"
}

do_stat() {
    local pid="$1"

    if [ -z "$pid" ]; then
        echo "Usage: proc_wrapper.sh stat <pid>"
        return 1
    fi

    if [ ! -d "/proc/$pid" ]; then
        echo "Process $pid not found"
        return 1
    fi

    echo "=== Process $pid ==="
    cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' '
    echo ""
    echo "Status: $(cat /proc/$pid/status 2>/dev/null | grep "^State:" | cut -d: -f2 | xargs)"
    echo "CPU: $(cat /proc/$pid/stat 2>/dev/null | awk '{print $3}')"
    echo "Memory: $(cat /proc/$pid/status 2>/dev/null | grep "^VmRSS:" | cut -d: -f2 | xargs)"
    echo "Threads: $(cat /proc/$pid/status 2>/dev/null | grep "^Threads:" | cut -d: -f2 | xargs)"
    echo ""
    echo "=== Open Files ==="
    ls -la /proc/$pid/fd 2>/dev/null | head -20 || echo "Cannot access"
}

do_threads() {
    local pid="$1"

    if [ -z "$pid" ]; then
        echo "Usage: proc_wrapper.sh threads <pid>"
        return 1
    fi

    if [ ! -d "/proc/$pid" ]; then
        echo "Process $pid not found"
        return 1
    fi

    echo "=== Threads for PID $pid ==="
    ps -T -p "$pid" 2>/dev/null && return 0
    ls /proc/$pid/task/ 2>/dev/null | head -20 || echo "Cannot list threads"
}

do_limits() {
    local pid="$1"

    if [ -z "$pid" ]; then
        echo "Usage: proc_wrapper.sh limits <pid>"
        return 1
    fi

    if [ ! -d "/proc/$pid" ]; then
        echo "Process $pid not found"
        return 1
    fi

    echo "=== Limits for PID $pid ==="
    cat /proc/$pid/limits 2>/dev/null
}

usage() {
    echo "Usage: proc_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  list [opts]            - List processes (ps aux)"
    echo "  top                    - Top processes"
    echo "  tree                   - Process tree"
    echo "  grep <pattern>         - Find processes by name"
    echo "  pids <pattern>         - Get PIDs matching pattern"
    echo "  kill <pid> [signal]   - Kill process (default SIGTERM=15)"
    echo "  killname <name> [sig]  - Kill by name pattern"
    echo "  stat <pid>             - Process status"
    echo "  threads <pid>          - Show threads"
    echo "  limits <pid>           - Process limits"
    echo ""
    echo "Examples:"
    echo "  proc_wrapper.sh list"
    echo "  proc_wrapper.sh top"
    echo "  proc_wrapper.sh grep nginx"
    echo "  proc_wrapper.sh kill 1234"
    echo "  proc_wrapper.sh kill 1234 9"
    echo "  proc_wrapper.sh killname python"
}

main() {
    [ $# -eq 0 ] && { usage; exit 0; }

    local cmd="$1"
    shift

    log_jsonl "proc_request" "command=$cmd" "args=$*"

    case "$cmd" in
        list|ps) do_list "$@" ;;
        top) do_top ;;
        tree) do_tree ;;
        grep|search) do_grep "$@" ;;
        pids) do_pids "$@" ;;
        kill) do_kill "$@" ;;
        killname) do_killname "$@" ;;
        stat|status) do_stat "$@" ;;
        threads) do_threads "$@" ;;
        limits) do_limits "$@" ;;
        help|--help|-h) usage ;;
        *) echo "Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

main "$@"
