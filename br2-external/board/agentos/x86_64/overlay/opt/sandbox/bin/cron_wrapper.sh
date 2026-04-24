#!/bin/sh
#
# cron_wrapper.sh - AgentOS cron job wrapper
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
    echo "=== User Crontabs ==="
    if command -v crontab >/dev/null 2>&1; then
        crontab -l 2>/dev/null || echo "No crontab for current user"
    else
        echo "crontab not available"
    fi

    echo ""
    echo "=== System Crontabs ==="
    for f in /etc/crontab /etc/cron.d/* /etc/cron.hourly/* /etc/cron.daily/* /etc/cron.weekly/* /etc/cron.monthly/*; do
        if [ -f "$f" ]; then
            echo "--- $f ---"
            cat "$f"
            echo ""
        fi
    done 2>/dev/null
}

do_user_list() {
    local user="$1"

    if [ -z "$user" ]; then
        echo "Usage: cron_wrapper.sh userlist <username>"
        return 1
    fi

    if command -v crontab >/dev/null 2>&1; then
        crontab -u "$user" -l 2>/dev/null || echo "No crontab for $user"
    else
        echo "crontab not available"
    fi
}

do_edit() {
    echo "=== Edit Crontab ==="
    if command -v crontab >/dev/null 2>&1; then
        crontab -e 2>&1 && echo "Crontab updated"
    else
        echo "crontab not available"
    fi
}

do_add() {
    local user="$1"
    local entry="$2"

    if [ -z "$entry" ]; then
        echo "Usage: cron_wrapper.sh add <entry>"
        echo ""
        echo "Format: <minute> <hour> <day> <month> <weekday> <command>"
        echo "Examples:"
        echo "  * * * * * /usr/bin/backup.sh"
        echo "  0 2 * * * /usr/bin/cleanup.sh"
        echo "  */15 * * * * /usr/bin/monitor.sh"
        return 1
    fi

    log_jsonl "cron_add" "entry=$entry"

    if command -v crontab >/dev/null 2>&1; then
        (crontab -l 2>/dev/null; echo "$entry") | crontab - && echo "Added: $entry"
    else
        echo "crontab not available"
    fi
}

do_remove() {
    local pattern="$1"

    if [ -z "$pattern" ]; then
        echo "Usage: cron_wrapper.sh remove <pattern>"
        return 1
    fi

    log_jsonl "cron_remove" "pattern=$pattern"

    if command -v crontab >/dev/null 2>&1; then
        crontab -l 2>/dev/null | grep -v "$pattern" | crontab - && echo "Removed lines matching: $pattern"
    else
        echo "crontab not available"
    fi
}

do_clear() {
    echo "=== Clear Crontab ==="
    if command -v crontab >/dev/null 2>&1; then
        crontab -r 2>/dev/null && echo "Crontab cleared" || echo "No crontab to clear"
    else
        echo "crontab not available"
    fi
}

do_next() {
    echo "=== Next Scheduled Jobs ==="
    if command -v crontab >/dev/null 2>&1; then
        crontab -l 2>/dev/null | grep -v "^#" | grep -v "^$"
    else
        echo "crontab not available"
    fi

    if command -v atq >/dev/null 2>&1; then
        echo ""
        echo "=== AT Queue ==="
        atq 2>/dev/null || echo "atq not available"
    fi
}

do_service() {
    echo "=== Cron Service Status ==="
    if command -v service >/dev/null 2>&1; then
        service cron status 2>/dev/null || service crond status 2>/dev/null || echo "Status unknown"
    elif [ -f /proc/$(pgrep -f cron)/stat ]; then
        echo "Cron is running (PID: $(pgrep -f cron))"
    else
        echo "Cron service status unknown"
    fi
}

usage() {
    echo "Usage: cron_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  list                    - List all crontabs"
    echo "  userlist <user>         - List user's crontab"
    echo "  edit                    - Edit crontab (interactive)"
    echo "  add <entry>             - Add cron entry"
    echo "  remove <pattern>        - Remove matching entries"
    echo "  clear                   - Clear all crontab"
    echo "  next                    - Show scheduled jobs"
    echo "  service                 - Cron service status"
    echo ""
    echo "Crontab Format:"
    echo "  * * * * * command"
    echo "  | | | | |"
    echo "  | | | | +--- Day of week (0-7, 0=Sun)"
    echo "  | | | +----- Month (1-12)"
    echo "  | | +------- Day of month (1-31)"
    echo "  | +--------- Hour (0-23)"
    echo "  +----------- Minute (0-59)"
    echo ""
    echo "Examples:"
    echo "  cron_wrapper.sh add '0 3 * * * /backup.sh'"
    echo "  cron_wrapper.sh add '*/15 * * * * /monitor.sh'"
    echo "  cron_wrapper.sh remove '/tmp/cleanup'"
}

main() {
    [ $# -eq 0 ] && { usage; exit 0; }

    local cmd="$1"
    shift

    log_jsonl "cron_request" "command=$cmd" "args=$*"

    case "$cmd" in
        list|ls) do_list ;;
        userlist) do_user_list "$@" ;;
        edit|e) do_edit ;;
        add) do_add "$@" ;;
        remove|rm) do_remove "$@" ;;
        clear) do_clear ;;
        next|scheduled) do_next ;;
        service|status) do_service ;;
        help|--help|-h) usage ;;
        *) echo "Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

main "$@"
