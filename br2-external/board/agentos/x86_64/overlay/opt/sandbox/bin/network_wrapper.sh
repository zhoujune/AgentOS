#!/bin/sh
#
# network_wrapper.sh — AgentOS network operation wrapper (B-line version)
#
# B-line changes:
#   - Accept VTRM-verified network requests
#   - Verify content_label and perform label checking
#   - Pure execution backend, policy decisions handled by VTRM
#
# Usage (B-line):
#   network_wrapper.sh execute <url> <method> [body] <content_label>
#   Only accepts VTRM-approved operations
#
# Events (trace.jsonl):
#   network_execute — Execute operation (VTRM-verified)
#   network_result  — Execute result
#

set -e

TRACE_DIR="${TRACE_DIR:-/var/log/sandbox/trace}"
TRACE_JSONL="$TRACE_DIR/trace.jsonl"

# Authorized secret sinks (read from environment variable)
AUTHORIZED_SECRETSINKS="${AUTHORIZED_SECRETSINKS:-}"

log_jsonl() {
    local event="$1"
    shift
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    mkdir -p "$TRACE_DIR" 2>/dev/null || true
    printf '%s\n' "{\"event\":\"$event\",\"ts\":\"$ts\",\"$*\"}" >> "$TRACE_JSONL" 2>/dev/null || true
}

check_label() {
    local url="$1"
    local label="$2"
    
    # public label always allowed
    [ "$label" = "public" ] && return 0
    
    # secret/high needs sink check
    if [ "$label" = "secret/high" ]; then
        # If no authorized sinks configured, deny all secret exfiltration
        [ -z "$AUTHORIZED_SECRETSINKS" ] && return 1
        
        # Check if URL is in authorized list
        for sink in $AUTHORIZED_SECRETSINKS; do
            case "$url" in
                "$sink"|"$sink"/*)
                    return 0
                    ;;
            esac
        done
        return 1
    fi
    
    return 1
}

do_execute() {
    local url="$1"
    local method="${2:-GET}"
    local body="${3:-}"
    local label="${4:-public}"
    
    # Label check (VTRM should have verified, double-check here)
    if ! check_label "$url" "$label"; then
        echo "ERROR: Label check failed: $label data cannot be sent to $url" >&2
        log_jsonl "network_result" "command=execute" "url=$url" "exit=1" "reason=label_check_failed"
        return 1
    fi
    
    log_jsonl "network_execute" "command=execute" "url=$url" "method=$method" "label=$label"
    
    # Execute HTTP request
    case "$method" in
        GET)
            curl -sSL "$url"
            ;;
        POST)
            curl -sSL -X POST -d "$body" "$url"
            ;;
        PUT)
            curl -sSL -X PUT -d "$body" "$url"
            ;;
        DELETE)
            curl -sSL -X DELETE "$url"
            ;;
        *)
            echo "ERROR: Unsupported method: $method" >&2
            log_jsonl "network_result" "command=execute" "url=$url" "exit=1" "reason=unsupported_method"
            return 1
            ;;
    esac
    
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        log_jsonl "network_result" "command=execute" "url=$url" "exit=0" "reason="
    else
        log_jsonl "network_result" "command=execute" "url=$url" "exit=$exit_code" "reason=curl_failed"
    fi
    
    return $exit_code
}

do_version() {
    echo "network_wrapper.sh v2.0.0-b (B-line: pure execution backend)"
    command -v curl >/dev/null 2>&1 && echo "curl: available" || echo "curl: not available"
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
        echo "ERROR: ping command not found" >&2
        return 1
    fi
}

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
        echo "No DNS tools available" >&2
        return 1
    fi
}

do_curl() {
    local url="$1"
    shift
    local extra_opts="$*"

    if [ -z "$url" ]; then
        echo "Usage: network_wrapper.sh curl <url> [options]"
        return 1
    fi

    if command -v curl >/dev/null 2>&1; then
        curl -sSL $extra_opts "$url"
    else
        echo "ERROR: curl command not found" >&2
        return 1
    fi
}

usage() {
    echo "Usage: network_wrapper.sh <command> [args...]" >&2
    echo ""
    echo "Commands (B-line mode):"
    echo "  execute <url> <method> [body] <label>  - Execute VTRM-approved HTTP request"
    echo "  version                               - Show version"
    echo "  status                                - Show network status"
    echo "  ping <host> [count]                   - Ping test"
    echo "  dns <domain>                          - DNS lookup"
    echo "  curl <url> [opts]                     - HTTP request"
    echo ""
    echo "Note: Policy decisions are now handled by VTRM."
}

main() {
    if [ $# -eq 0 ] || [ -z "$1" ]; then
        usage
        exit 0
    fi

    local cmd="$1"
    shift

    case "$cmd" in
        version|--version|-v)
            do_version
            ;;
        status)
            do_status "$@"
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
        execute)
            # B-line: execute subcommand
            # Format: network_wrapper.sh execute <url> <method> [body] <label>
            local url="${1:-}"
            local method="${2:-GET}"
            local body="${3:-}"
            local label="${4:-public}"
            
            if [ -z "$url" ]; then
                usage
                exit 1
            fi
            
            do_execute "$url" "$method" "$body" "$label"
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            echo "ERROR: Unknown command: $cmd" >&2
            usage
            exit 1
            ;;
    esac
}

main "$@"
