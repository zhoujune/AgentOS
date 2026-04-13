#!/bin/sh
#
# sys_wrapper.sh - AgentOS 系统信息包装器
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

do_cpu() {
    echo "=== CPU Info ==="
    if [ -f /proc/cpuinfo ]; then
        grep "model name" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs || true
        echo "Cores: $(nproc 2>/dev/null || grep -c "^processor" /proc/cpuinfo 2>/dev/null || echo 1)"
    fi
    if [ -f /proc/loadavg ]; then
        read -r load1 load5 load15 _ < /proc/loadavg
        echo "Load: $load1 (1m) $load5 (5m) $load15 (15m)"
    fi
    echo ""
    top -bn1 2>/dev/null | head -5 || echo "top not available"
    return 0
}

do_memory() {
    echo "=== Memory ==="
    if [ -f /proc/meminfo ]; then
        total=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        available=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
        free=$(grep MemFree /proc/meminfo | awk '{print $2}')

        total_mb=$((total / 1024))
        avail_mb=$((available / 1024))
        free_mb=$((free / 1024))

        echo "Total: ${total_mb} MB"
        echo "Available: ${avail_mb} MB"
        echo "Free: ${free_mb} MB"
        echo "Usage: $(( (total - available) * 100 / total ))%"
    else
        free -h 2>/dev/null || echo "Memory info not available"
    fi
    return 0
}

do_disk() {
    echo "=== Disk Usage ==="
    df -h 2>/dev/null | grep -v "tmpfs\|devtmpfs\|overlay" || df -h 2>/dev/null || echo "df not available"
    echo ""
    echo "=== Mount Points ==="
    mount 2>/dev/null | grep -v "proc\|sys\|dev\|tmp" | column -t 2>/dev/null || echo "mount not available"
    return 0
}

do_uptime() {
    echo "=== Uptime ==="
    if [ -f /proc/uptime ]; then
        read -r uptime _ < /proc/uptime
        uptime_int=$(echo "$uptime" | cut -d. -f1)
        days=$((uptime_int / 86400))
        hours=$(( (uptime_int % 86400) / 3600 ))
        mins=$(( (uptime_int % 3600) / 60 ))
        echo "System up: ${days}d ${hours}h ${mins}m"
    fi
    if command -v uptime >/dev/null 2>&1; then
        uptime -s 2>/dev/null && echo "Boot: $(uptime -s)" || echo "Boot time not available"
    fi
    return 0
}

do_info() {
    echo "=== System Info ==="
    uname -a
    echo ""
    echo "Hostname: $(cat /etc/hostname 2>/dev/null || hostname)"
    echo "OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"')"
    return 0
}

do_load() {
    echo "=== Load Average ==="
    if [ -f /proc/loadavg ]; then
        read -r load1 load5 load15 rest < /proc/loadavg
        echo "1m: $load1  5m: $load5  15m: $load15"

        cores=$(nproc 2>/dev/null || echo 1)
        echo "Load per core: $(echo "scale=2; $load1 / $cores" | bc 2>/dev/null || echo "N/A")"
    fi
}

do_processes() {
    echo "=== Top Processes ==="
    ps aux --sort=-%cpu | head -11
}

do_network_stats() {
    echo "=== Network Stats ==="
    cat /proc/net/dev
    echo ""
    if [ -f /proc/net/snmp ]; then
        echo "=== TCP Stats ==="
        grep Tcp: /proc/net/snmp
    fi
}

do_summary() {
    do_info 2>&1 || true
    echo ""
    do_uptime 2>&1 || true
    echo ""
    do_cpu 2>&1 || true
    echo ""
    do_memory 2>&1 || true
    echo ""
    do_disk 2>&1 || true
    return 0
}

usage() {
    echo "Usage: sys_wrapper.sh <command>"
    echo ""
    echo "Commands:"
    echo "  cpu                   - CPU info and load"
    echo "  memory                - Memory usage"
    echo "  disk                  - Disk usage and mounts"
    echo "  uptime                - System uptime"
    echo "  load                  - Load average"
    echo "  processes             - Top processes by CPU"
    echo "  network               - Network statistics"
    echo "  info                  - Basic system info"
    echo "  summary                - All info (default)"
}

main() {
    local cmd="${1:-summary}"

    log_jsonl "sys_request" "command=$cmd"

    case "$cmd" in
        cpu) do_cpu ;;
        memory|mem) do_memory ;;
        disk|df) do_disk ;;
        uptime) do_uptime ;;
        load) do_load ;;
        processes|top) do_processes ;;
        network|net) do_network_stats ;;
        info|system) do_info ;;
        summary|all) do_summary ;;
        help|--help|-h) usage ;;
        *) usage ;;
    esac
}

main "$@"
