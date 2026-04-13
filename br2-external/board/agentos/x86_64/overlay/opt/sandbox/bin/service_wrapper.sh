#!/bin/sh
#
# service_wrapper.sh - AgentOS 服务管理包装器
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

has_systemd() {
    command -v systemctl >/dev/null 2>&1
}

has_initd() {
    [ -d /etc/init.d ]
}

do_list_systemd() {
    echo "=== Systemd Services ==="
    systemctl list-units --type=service --state=running --no-pager 2>/dev/null || echo "systemctl failed"
}

do_list_initd() {
    echo "=== Init.d Services ==="
    ls /etc/init.d/ 2>/dev/null || echo "No init.d services"
}

do_list() {
    if has_systemd; then
        do_list_systemd
    elif has_initd; then
        do_list_initd
    else
        echo "No service manager available"
    fi
}

do_status_systemd() {
    local service="$1"
    systemctl status "$service" --no-pager 2>&1
}

do_status_initd() {
    local service="$1"
    /etc/init.d/"$service" status 2>&1
}

do_status() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh status <service>"
        return 1
    fi

    if has_systemd; then
        do_status_systemd "$service"
    elif has_initd; then
        do_status_initd "$service"
    else
        echo "No service manager available"
    fi
}

do_start_systemd() {
    local service="$1"
    systemctl start "$service" 2>&1 && echo "Started: $service"
}

do_start_initd() {
    local service="$1"
    /etc/init.d/"$service" start 2>&1 && echo "Started: $service"
}

do_start() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh start <service>"
        return 1
    fi

    log_jsonl "service_start" "service=$service"

    if has_systemd; then
        do_start_systemd "$service"
    elif has_initd; then
        do_start_initd "$service"
    else
        echo "No service manager available"
    fi
}

do_stop_systemd() {
    local service="$1"
    systemctl stop "$service" 2>&1 && echo "Stopped: $service"
}

do_stop_initd() {
    local service="$1"
    /etc/init.d/"$service" stop 2>&1 && echo "Stopped: $service"
}

do_stop() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh stop <service>"
        return 1
    fi

    log_jsonl "service_stop" "service=$service"

    if has_systemd; then
        do_stop_systemd "$service"
    elif has_initd; then
        do_stop_initd "$service"
    else
        echo "No service manager available"
    fi
}

do_restart_systemd() {
    local service="$1"
    systemctl restart "$service" 2>&1 && echo "Restarted: $service"
}

do_restart_initd() {
    local service="$1"
    /etc/init.d/"$service" restart 2>&1 && echo "Restarted: $service"
}

do_restart() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh restart <service>"
        return 1
    fi

    log_jsonl "service_restart" "service=$service"

    if has_systemd; then
        do_restart_systemd "$service"
    elif has_initd; then
        do_restart_initd "$service"
    else
        echo "No service manager available"
    fi
}

do_reload_systemd() {
    local service="$1"
    systemctl reload "$service" 2>&1 && echo "Reloaded: $service"
}

do_reload() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh reload <service>"
        return 1
    fi

    log_jsonl "service_reload" "service=$service"

    if has_systemd; then
        do_reload_systemd "$service"
    else
        echo "reload not supported"
    fi
}

do_enable_systemd() {
    local service="$1"
    systemctl enable "$service" 2>&1 && echo "Enabled: $service"
}

do_enable() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh enable <service>"
        return 1
    fi

    log_jsonl "service_enable" "service=$service"

    if has_systemd; then
        do_enable_systemd "$service"
    else
        echo "systemd required"
    fi
}

do_disable_systemd() {
    local service="$1"
    systemctl disable "$service" 2>&1 && echo "Disabled: $service"
}

do_disable() {
    local service="$1"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh disable <service>"
        return 1
    fi

    log_jsonl "service_disable" "service=$service"

    if has_systemd; then
        do_disable_systemd "$service"
    else
        echo "systemd required"
    fi
}

do_logs() {
    local service="$1"
    local lines="${2:-50}"

    if [ -z "$service" ]; then
        echo "Usage: service_wrapper.sh logs <service> [lines]"
        return 1
    fi

    if command -v journalctl >/dev/null 2>&1; then
        journalctl -u "$service" -n "$lines" --no-pager
    elif [ -f "/var/log/$service.log" ]; then
        tail -n "$lines" "/var/log/$service.log"
    else
        echo "Logs not available"
    fi
}

usage() {
    echo "Usage: service_wrapper.sh <command> <service>"
    echo ""
    echo "Commands:"
    echo "  list                    - List running services"
    echo "  status <service>        - Service status"
    echo "  start <service>         - Start service"
    echo "  stop <service>          - Stop service"
    echo "  restart <service>      - Restart service"
    echo "  reload <service>       - Reload config"
    echo "  enable <service>        - Enable at boot"
    echo "  disable <service>       - Disable at boot"
    echo "  logs <service> [lines] - View logs"
    echo ""
    echo "Examples:"
    echo "  service_wrapper.sh list"
    echo "  service_wrapper.sh status nginx"
    echo "  service_wrapper.sh restart docker"
}

main() {
    [ $# -eq 0 ] && { usage; exit 0; }

    local cmd="$1"
    shift

    log_jsonl "service_request" "command=$cmd" "args=$*"

    case "$cmd" in
        list|ls) do_list ;;
        status) do_status "$@" ;;
        start) do_start "$@" ;;
        stop) do_stop "$@" ;;
        restart|reload) do_restart "$@" ;;
        reload) do_reload "$@" ;;
        enable) do_enable "$@" ;;
        disable) do_disable "$@" ;;
        logs) do_logs "$@" ;;
        help|--help|-h) usage ;;
        *) echo "Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

main "$@"
