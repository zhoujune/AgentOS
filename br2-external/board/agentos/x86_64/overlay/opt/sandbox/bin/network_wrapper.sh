#!/bin/sh
#
# network_wrapper.sh — AgentOS 网络操作包装器
#
# 功能：
#   1. 统一入口：所有网络操作通过此包装器执行
#   2. 提供常用的网络诊断工具
#   3. 记录 trace 日志
#
# 用法：
#   network_wrapper.sh "status"                          - 查看网络状态
#   network_wrapper.sh "ping <host>" [count]           - ping 测试
#   network_wrapper.sh "dns <domain>"                  - DNS 查询
#   network_wrapper.sh "curl <url>"                    - HTTP 请求
#   network_wrapper.sh "wget <url> [output]"           - 下载文件
#   network_wrapper.sh "ports <host>"                   - 扫描端口
#   network_wrapper.sh "connect <host> <port>"         - TCP 连接测试
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
    printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"$*\"}" >> "$TRACE_JSONL" 2>/dev/null || true
}

log_error() {
    echo "ERROR: $*" >&2
    log_jsonl "network_error" "reason=$*"
}

# 网络状态
do_version() {
    echo "network_wrapper.sh v1.0.0"
    command -v curl >/dev/null 2>&1 && echo "curl: available" || echo "curl: not available"
    command -v ping >/dev/null 2>&1 && echo "ping: available" || echo "ping: not available"
    command -v nc >/dev/null 2>&1 && echo "nc: available" || echo "nc: not available"
}

do_status() {
    echo "=== Network Status ==="
    echo ""
    echo "--- Interfaces ---"
    ip addr show 2>/dev/null || ifconfig -a 2>/dev/null || echo "No network tools available"
    echo ""
    echo "--- Routes ---"
    ip route show 2>/dev/null || route -n 2>/dev/null || echo "No routes available"
    echo ""
    echo "--- DNS ---"
    cat /etc/resolv.conf 2>/dev/null || echo "No resolv.conf"
    echo ""
    echo "--- Connections ---"
    ss -tunap 2>/dev/null || netstat -tunap 2>/dev/null || echo "No connection info available"
}

# Ping 测试
do_ping() {
    local host="$1"
    local count="${2:-4}"

    if [ -z "$host" ]; then
        echo "Usage: network_wrapper.sh ping <host> [count]"
        return 1
    fi

    if command -v ping >/dev/null 2>&1; then
        ping -c "$count" "$host"
    elif command -v ping6 >/dev/null 2>&1; then
        ping6 -c "$count" "$host"
    else
        log_error "ping_command_not_found"
        echo "ERROR: ping command not found"
        return 1
    fi
}

# DNS 查询
do_dns() {
    local domain="$1"

    if [ -z "$domain" ]; then
        echo "Usage: network_wrapper.sh dns <domain>"
        return 1
    fi

    if command -v nslookup >/dev/null 2>&1; then
        nslookup "$domain"
    elif command -v host >/dev/null 2>&1; then
        host "$domain"
    elif command -v getent >/dev/null 2>&1; then
        getent ahosts "$domain"
    else
        # 使用 ping 作为 fallback（会解析域名）
        echo "No DNS tools available, trying ping..."
        ping -c 1 "$domain" 2>&1 || true
    fi
}

# HTTP 请求 (curl)
do_curl() {
    local url="$1"

    if [ -z "$url" ]; then
        echo "Usage: network_wrapper.sh curl <url> [options]"
        return 1
    fi

    # 剩余参数作为 curl 选项
    shift
    local extra_opts="$*"

    if command -v curl >/dev/null 2>&1; then
        curl -sSL $extra_opts "$url"
    else
        log_error "curl_not_found"
        echo "ERROR: curl command not found"
        return 1
    fi
}

# 下载 (wget)
do_wget() {
    local url="$1"
    local output="${2:--}"

    if [ -z "$url" ]; then
        echo "Usage: network_wrapper.sh wget <url> [output_file]"
        return 1
    fi

    if command -v wget >/dev/null 2>&1; then
        if [ "$output" = "-" ]; then
            wget -qO- "$url"
        else
            wget -qO "$output" "$url"
            echo "Downloaded to: $output"
        fi
    else
        log_error "wget_not_found"
        echo "ERROR: wget command not found"
        return 1
    fi
}

# TCP 连接测试
do_connect() {
    local host="$1"
    local port="$2"

    if [ -z "$host" ] || [ -z "$port" ]; then
        echo "Usage: network_wrapper.sh connect <host> <port>"
        return 1
    fi

    if command -v nc >/dev/null 2>&1; then
        nc -zv -w 5 "$host" "$port" 2>&1
    elif command -v telnet >/dev/null 2>&1; then
        timeout 5 telnet "$host" "$port" 2>&1 || true
    else
        # 使用 /dev/tcp (bash 内置)
        (echo >/dev/tcp/"$host"/"$port") 2>/dev/null && echo "Connection to $host:$port succeeded" || echo "Connection to $host:$port failed"
    fi
}

# 端口扫描 (简易版)
do_ports() {
    local host="$1"
    local ports="${2:-80,443,22,23,21,25,53,110,143,3306,5432,6379,8080}"

    if [ -z "$host" ]; then
        echo "Usage: network_wrapper.sh ports <host> [ports]"
        return 1
    fi

    echo "Scanning common ports on $host..."
    echo "Ports: $ports"
    echo ""

    for port in $(echo "$ports" | tr ',' ' '); do
        if command -v nc >/dev/null 2>&1; then
            if nc -zv -w 2 "$host" "$port" 2>&1 | grep -q succeeded; then
                echo "  $port/tcp OPEN"
            fi
        else
            if (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
                echo "  $port/tcp OPEN"
            fi
        fi
    done
}

# 带宽测试
do_speedtest() {
    if command -v curl >/dev/null 2>&1; then
        echo "Running speed test..."
        echo ""

        # 测试下载速度
        echo "Download test..."
        speed=$(curl -o /dev/null -s -w '%{speed_download}' "http://speedtest.tele2.net/1MB.zip" 2>/dev/null || echo "0")
        echo "Download speed: $speed bytes/s"

        # 测试上传速度（需要服务器支持）
        echo "Upload test..."
        echo "test" | curl -o /dev/null -s -w '%{speed_upload}' -X POST -d @- "http://speedtest.tele2.net/upload" 2>/dev/null || echo "Upload test not supported"
    else
        echo "ERROR: curl required for speed test"
        return 1
    fi
}

# 跟踪路由
do_traceroute() {
    local host="$1"

    if [ -z "$host" ]; then
        echo "Usage: network_wrapper.sh traceroute <host>"
        return 1
    fi

    if command -v traceroute >/dev/null 2>&1; then
        traceroute -m 15 "$host"
    elif command -v tracepath >/dev/null 2>&1; then
        tracepath "$host"
    else
        echo "No traceroute tool available"
        return 1
    fi
}

# 用法帮助
usage() {
    echo "Usage: network_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  status                     - Show network status"
    echo "  ping <host> [count]        - Ping test (default count: 4)"
    echo "  dns <domain>               - DNS lookup"
    echo "  curl <url> [opts]          - HTTP request (use - for stdout)"
    echo "  wget <url> [output]        - Download file"
    echo "  connect <host> <port>      - TCP connection test"
    echo "  ports <host> [ports]       - Scan common ports"
    echo "  traceroute <host>          - Trace route to host"
    echo "  speedtest                  - Run speed test"
    echo ""
    echo "Examples:"
    echo "  network_wrapper.sh status"
    echo "  network_wrapper.sh ping google.com 5"
    echo "  network_wrapper.sh curl https://api.github.com"
    echo "  network_wrapper.sh wget http://example.com/file.zip /workspace/file.zip"
}

# 主入口
main() {
    if [ $# -eq 0 ] || [ -z "$1" ]; then
        usage
        exit 0
    fi

    local cmd="$1"
    shift

    log_jsonl "network_request" "command=$cmd" "args=$*"

    local result
    case "$cmd" in
        status|version|--version|-v)
            do_status "$@"
            ;;
        version)
            do_version
            ;;
        ping)
            do_ping "$@"
            ;;
        dns)
            do_dns "$@"
            ;;
        curl)
            do_curl "$@"
            ;;
        wget)
            do_wget "$@"
            ;;
        connect)
            do_connect "$@"
            ;;
        ports)
            do_ports "$@"
            ;;
        traceroute|trace)
            do_traceroute "$@"
            ;;
        speedtest)
            do_speedtest "$@"
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            echo "ERROR: Unknown command: $cmd"
            usage
            exit 1
            ;;
    esac
}

main "$@"
