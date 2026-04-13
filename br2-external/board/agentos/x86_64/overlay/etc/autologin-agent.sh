#!/bin/sh
#
# autologin-agent.sh — VM 启动入口（以 root 身份运行），设置好后切换到 agent
#
# 关键设计：
#   - autologin-agent.sh 以 root 身份运行，做完初始化后 exec 替换进程
#   - 替换后的进程是 agent 用户的 shell，这个 shell 在最后 exec 一个后台 agent
#   - ttyS0 保持一个可交互的登录 shell，用户随时可以 Ctrl-C 退到 shell
#   - 后台 agent 在 nohup 下持续监听 inbox
#
# agent_main_loop.sh — 由 agent 身份持续运行的任务监听循环
#

set -e

AGENT_USER="agent"
BRIDGE_DIR="/mnt/agent_bridge"
AGENT_HOME="/home/agent"

# ============================================================
# 前置条件：root 身份初始化
# ============================================================
setup_root() {
    echo "[agent-startup] Running as root, setting up environment..."

    # /workspace（本地，9P mount 失败时的 fallback）
    mkdir -p /workspace
    chmod 755 /workspace 2>/dev/null || true
    chown 1000:1000 /workspace 2>/dev/null || true

    # 本地日志目录
    mkdir -p /var/log/sandbox/tasks
    mkdir -p /var/log/sandbox/trace
    mkdir -p /var/log/sandbox/agent
    
    chmod 755 /var/log/sandbox/tasks 2>/dev/null || true
    chmod 755 /var/log/sandbox/trace 2>/dev/null || true
    chmod 755 /var/log/sandbox/agent 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/tasks 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/trace 2>/dev/null || true
    chown 1000:1000 /var/log/sandbox/agent 2>/dev/null || true

    # mount agent_bridge as root
    mkdir -p /mnt/agent_bridge
    mount -t 9p -o trans=virtio,cache=loose agent_bridge /mnt/agent_bridge
    # /mnt/agent_bridge（9P mount 点）
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

    # /home/agent 工作目录
    mkdir -p "$AGENT_HOME"
    chmod 755 "$AGENT_HOME" 2>/dev/null || true
    chown -R 1000:1000 "$AGENT_HOME" 2>/dev/null || true
}

# ============================================================
# 生成 agent 端主循环脚本（写到文件，供 agent 用户运行）
# ============================================================
write_agent_script() {
    cat > "$AGENT_HOME/agent_main_loop.sh" << 'SCRIPT_EOF'
#!/bin/sh
#
# agent_main_loop.sh — 由 agent 身份持续运行的任务监听循环
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

    # 提取 "task" JSON 字段
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
    result=$(python3 /home/agent/agent_runner.py --task-id "$task_id" --task "$task_desc" 2>&1)
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

    # 移到 done/
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
    # 等待 inbox 就绪
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

    # 创建 tasks 目录（log_run 需要）
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
    chmod +x "$AGENT_HOME/run_regression.sh"
    chmod +x "$AGENT_HOME/test_daemon_mode.sh"
    chown 1000:1000 "$AGENT_HOME/agent_main_loop.sh" 2>/dev/null || true
}

# ============================================================
# 生成 agent 用户的 .ashrc（ash 专用，每次登录执行一次）
# ============================================================
write_ashrc() {
    cat > "$AGENT_HOME/.ashrc" << 'ASHRC_EOF'
# AgentOS agent 环境初始化
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/home/agent"
export PYTHONUNBUFFERED=1

# 欢迎信息
echo ""
echo "=== AgentOS v1 ==="
echo "Agent watching: /mnt/agent_bridge/inbox"
echo "Bridge inbox:   $([ -d /mnt/agent_bridge/inbox ] && echo 'READY' || echo 'NOT FOUND')"
echo "Workspace:      $([ -d /workspace ] && echo 'READY' || echo 'NOT FOUND')"
echo ""
echo "Commands:"
echo "  ls /mnt/agent_bridge/inbox/   - 查看待处理任务"
echo "  cat /var/log/sandbox/tasks/   - 查看日志"
echo "  sh /home/agent/agent_main_loop.sh  - 手动运行任务监听"
echo ""
ASHRC_EOF
    chown 1000:1000 "$AGENT_HOME/.ashrc" 2>/dev/null || true
}

# ============================================================
# 主入口
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
