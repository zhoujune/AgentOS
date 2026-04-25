#!/bin/sh
#
# autologin-agent.sh — VM boot entry (runs as root), setup then switch to agent
#
# Key design:
#   - autologin-agent.sh runs as root, after initialization exec replaces process
#   - Replaced process is agent user's shell, this shell finally execs a background agent
#   - ttyS0 keeps an interactive login shell, user can Ctrl-C to shell at any time
#   - Background agent runs continuously listening to inbox under nohup
#
# agent_main_loop.sh — Task listening loop continuously run by agent identity
#

set -e

AGENT_USER="agent"
BRIDGE_DIR="/mnt/agent_bridge"
AGENT_HOME="/home/agent"

has_default_route() {
    ip route 2>/dev/null | grep -q '^default '
}

has_ipv4_address() {
    local dev="$1"
    ip -4 addr show "$dev" 2>/dev/null | grep -q 'inet '
}

ensure_guest_network() {
    local dev=""
    local candidate=""

    echo "[agent-startup] Checking guest network state..."
    for candidate in eth0 ens3 enp0s3; do
        if ip link show "$candidate" >/dev/null 2>&1; then
            dev="$candidate"
            break
        fi
    done

    if [ -z "$dev" ] && command -v ip >/dev/null 2>&1; then
        dev=$(ip -o link show 2>/dev/null | awk -F': ' '$2 != "lo" {print $2; exit}')
    fi

    if [ -z "$dev" ]; then
        echo "[agent-startup] No guest network device found"
        return 0
    fi

    if has_default_route && has_ipv4_address "$dev"; then
        echo "[agent-startup] Guest network already ready on $dev"
        return 0
    fi

    echo "[agent-startup] Bringing up $dev..."
    ip link set "$dev" up 2>/dev/null || true
    sleep 1

    if ! has_default_route || ! has_ipv4_address "$dev"; then
        if command -v udhcpc >/dev/null 2>&1; then
            echo "[agent-startup] Requesting DHCP lease on $dev..."
            udhcpc -i "$dev" -q -n -t 5 -T 3 2>&1 || true
        fi
    fi

    if ! has_default_route || ! has_ipv4_address "$dev"; then
        echo "[agent-startup] DHCP not ready, applying QEMU user-net fallback on $dev..."
        ip addr add 10.0.2.15/24 dev "$dev" 2>/dev/null || true
        ip route add default via 10.0.2.2 2>/dev/null || true
        mkdir -p /run 2>/dev/null || true
        {
            echo "nameserver 10.0.2.3"
            echo "nameserver 8.8.8.8"
        } > /run/resolv.conf
    fi

    echo "[agent-startup] Guest network status:"
    ip addr show "$dev" 2>/dev/null || true
    ip route 2>/dev/null || true
}

# ============================================================
# Precondition: root identity initialization
# ============================================================
setup_root() {
    echo "[agent-startup] Running as root, setting up environment..."

    ensure_guest_network

    # /workspace (local, fallback when 9P mount fails)
    mkdir -p /workspace
    chmod 755 /workspace 2>/dev/null || true
    chown 1000:1000 /workspace 2>/dev/null || true

    # Local log directories
    mkdir -p /var/log/sandbox/tasks
    mkdir -p /var/log/sandbox/trace
    mkdir -p /var/log/sandbox/agent
    mkdir -p /var/log/sandbox/vtrm
    mkdir -p /var/lib/agentos/approvals/pending
    mkdir -p /var/lib/agentos/approvals/approved
    mkdir -p /var/lib/agentos/approvals/used
    mkdir -p /var/lib/agentos/approvals/tokens
    mkdir -p /var/lib/agentos
    
    chmod 755 /var/log/sandbox/tasks 2>/dev/null || true
    chmod 755 /var/log/sandbox/trace 2>/dev/null || true
    chmod 755 /var/log/sandbox/agent 2>/dev/null || true
    chmod 755 /var/log/sandbox/vtrm 2>/dev/null || true
    chmod 755 /var/lib/agentos 2>/dev/null || true
    chmod 755 /var/lib/agentos/approvals 2>/dev/null || true
    chmod 755 /var/lib/agentos/approvals/pending 2>/dev/null || true
    chmod 755 /var/lib/agentos/approvals/approved 2>/dev/null || true
    chmod 755 /var/lib/agentos/approvals/used 2>/dev/null || true
    chmod 755 /var/lib/agentos/approvals/tokens 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/tasks 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/trace 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/agent 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/vtrm 2>/dev/null || true
    chown 1000:1000 /var/lib/agentos 2>/dev/null || true
    chown -R 1000:1000 /var/lib/agentos/approvals 2>/dev/null || true
    if [ -e /var/lib/agentos/agent.db ]; then
        chown 1000:1000 /var/lib/agentos/agent.db 2>/dev/null || true
        chmod 600 /var/lib/agentos/agent.db 2>/dev/null || true
    fi

    # mount agent_bridge as root if it is not already mounted by init
    mkdir -p /mnt/agent_bridge
    if ! mountpoint -q /mnt/agent_bridge 2>/dev/null; then
        mount -t 9p -o trans=virtio,cache=loose agent_bridge /mnt/agent_bridge || true
    fi
    # /mnt/agent_bridge (9P mount point)
    if [ ! -d "$BRIDGE_DIR" ]; then
        echo "[agent-startup] Bridge not mounted, creating fallback..."
        mkdir -p "$BRIDGE_DIR"
        mkdir -p "$BRIDGE_DIR/inbox"
        mkdir -p "$BRIDGE_DIR/outbox"
        mkdir -p "$BRIDGE_DIR/done"
        mkdir -p "$BRIDGE_DIR/error"
        mkdir -p "$BRIDGE_DIR/tasks"
        chmod -R 755 "$BRIDGE_DIR" 2>/dev/null || true
        chown -R 1000:1000 "$BRIDGE_DIR" 2>/dev/null || true
    fi

    # /home/agent working directory
    mkdir -p "$AGENT_HOME"
    chmod 755 "$AGENT_HOME" 2>/dev/null || true
    chown -R 1000:1000 "$AGENT_HOME" 2>/dev/null || true

    # Final fallback again, avoid agent tasks starting without route
    ensure_guest_network
}

# ============================================================
# Generate agent main loop script (write to file, run by agent user)
# ============================================================
write_agent_script() {
    # Keep the overlay-provided /home/agent/agent_main_loop.sh as the source of truth.
    # Do not regenerate it at boot, because that can drift from the checked-in copy.
    chmod +x "$AGENT_HOME/agent_main_loop.sh" 2>/dev/null || true
    chmod +x "$AGENT_HOME/agent_runner.py" 2>/dev/null || true
    chown 1000:1000 "$AGENT_HOME/agent_main_loop.sh" 2>/dev/null || true
    chown 1000:1000 "$AGENT_HOME/agent_runner.py" 2>/dev/null || true
    return 0

    cat > "$AGENT_HOME/agent_main_loop.sh" << 'SCRIPT_EOF'
#!/bin/sh
#
# agent_main_loop.sh — Task listening loop continuously run by agent identity
#

set -e

AGENT_USER="agent"
BRIDGE_DIR="/mnt/agent_bridge"
INBOX_DIR="$BRIDGE_DIR/inbox"
DONE_DIR="$BRIDGE_DIR/done"
RUNS_LOG="$BRIDGE_DIR/tasks/agent_runs.jsonl"
TRACE_JSONL="/var/log/sandbox/trace/trace.jsonl"

get_next_seq() {
    local seq_file="$BRIDGE_DIR/.agent_seq"
    local seq
    seq=$(cat "$seq_file" 2>/dev/null || echo 0)
    seq=$((seq + 1))
    printf '%s' "$seq" > "$seq_file"
    printf '%s' "$seq"
}

log_run() {
    local task_id="$1"
    local status="$2"
    local answer="$3"
    local steps="$4"
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    printf '%s\n' "{\"task_id\":\"$task_id\",\"ts\":\"$ts\",\"status\":\"$status\",\"answer\":\"$answer\",\"steps\":$steps}" >> "$RUNS_LOG" 2>/dev/null || true
}

run_task() {
    local task_file="$1"
    local task_id
    local task_desc

    task_id=$(basename "$task_file" | sed 's/task_//' | sed 's/\..*$//')
    [ -z "$task_id" ] && task_id="task-$(date -u '+%Y%m%dT%H%M%S')"

    # Extract "task" JSON field
    task_desc=$(cat "$task_file" 2>/dev/null | grep -o '"task"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*":"\([^"]*\)"$/\1/')
    [ -z "$task_desc" ] && task_desc="$(cat "$task_file" 2>/dev/null | head -c 200)"

    echo "[agent] ======================================="
    echo "[agent] Starting task: $task_id"
    echo "[agent] $task_desc"
    echo "[agent] ======================================="

    local ts_start
    ts_start=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    printf '%s\n' "{\"event\":\"task_start\",\"ts\":\"$ts_start\",\"task_id\":\"$task_id\"}" >> "$TRACE_JSONL" 2>/dev/null || true

    local result
    result=$(python3 /home/agent/agent_runner.py --taskId "$task_id" --task "$task_desc" 2>&1)
    local exit_code=$?

    echo "[agent] Output:"
    echo "$result"
    echo "[agent] ======================================="

    if [ $exit_code -eq 0 ]; then
        local answer steps
        answer=$(printf '%s' "$result" | grep -o '"answer"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*":"\([^"]*\)"$/\1/' || echo "")
        steps=$(printf '%s' "$result" | grep -o '"steps"[[:space:]]*:[[:space:]]*[0-9]*' | head -1 | sed 's/[^0-9]//g' || echo "0")
        log_run "$task_id" "success" "$answer" "$steps"
    else
        log_run "$task_id" "failed" "$(printf '%s' "$result" | head -c 500)" "0"
    fi

    # Move to done/
    if [ -d "$DONE_DIR" ]; then
        mv "$task_file" "$DONE_DIR/" 2>/dev/null || rm -f "$task_file" || true
    fi
}

process_inbox() {
    local found=0
    for task_file in "$INBOX_DIR"/task_*; do
        [ -e "$task_file" ] || continue
        found=1
        echo "[agent] Found task: $(basename "$task_file")"
        run_task "$task_file" || echo "[agent] Task failed: $(basename "$task_file")"
    done
    return $found
}

main() {
    # Wait for inbox to be ready
    local count=0
    while [ ! -d "$INBOX_DIR" ] && [ $count -lt 15 ]; do
        echo "[agent] Waiting for inbox... ($count/15)"
        sleep 2
        count=$((count + 1))
    done

    [ -d "$INBOX_DIR" ] && echo "[agent] Inbox ready: $INBOX_DIR" \
        || echo "[agent] WARNING: inbox not found"

    echo "[agent] AgentOS watching: $INBOX_DIR"
    echo "[agent] Place task_*.txt/json files to trigger"

    # Create tasks directory (needed by log_run)
    mkdir -p "$BRIDGE_DIR/tasks" 2>/dev/null || true
    chmod 755 "$BRIDGE_DIR/tasks" 2>/dev/null || true

    process_inbox || true

    while true; do
        sleep 5
        process_inbox || true
    done
}

main
SCRIPT_EOF
    chmod +x "$AGENT_HOME/agent_main_loop.sh"
    chmod +x "$AGENT_HOME/test_agent_user_runtime.sh"
    chmod +x "$AGENT_HOME/run_regression.sh"
    chmod +x "$AGENT_HOME/test_daemon_mode.sh"
    chown 1000:1000 "$AGENT_HOME/agent_main_loop.sh" 2>/dev/null || true
    chown 1000:1000 "$AGENT_HOME/test_agent_user_runtime.sh" 2>/dev/null || true
}

# ============================================================
# Generate agent user's .ashrc (ash-specific, executed on each login)
# ============================================================
write_ashrc() {
    cat > "$AGENT_HOME/.ashrc" << 'ASHRC_EOF'
# AgentOS agent environment initialization
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/home/agent"
export PYTHONUNBUFFERED=1

# Welcome message
echo ""
echo "=== AgentOS v1 ==="
echo "Agent watching: /mnt/agent_bridge/inbox"
echo "Bridge inbox:   $([ -d /mnt/agent_bridge/inbox ] && echo 'READY' || echo 'NOT FOUND')"
echo "Workspace:      $([ -d /workspace ] && echo 'READY' || echo 'NOT FOUND')"
echo ""
echo "Commands:"
echo "  ls /mnt/agent_bridge/inbox/   - View pending tasks"
echo "  cat /var/log/sandbox/tasks/   - View logs"
echo "  sh /home/agent/agent_main_loop.sh  - Manually run task listener"
echo ""
ASHRC_EOF
    chown 1000:1000 "$AGENT_HOME/.ashrc" 2>/dev/null || true
}

# ============================================================
# Main entry
# ============================================================
if [ "$(id -un)" = "root" ]; then
    setup_root
    write_agent_script
    write_ashrc
    echo "[agent-startup] Switching to agent user..."
    exec su - "$AGENT_USER"
else
    echo "[agent-startup] ERROR: must run as root first" >&2
    exit 1
fi
