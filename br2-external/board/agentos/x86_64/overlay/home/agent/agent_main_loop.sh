#!/bin/sh
#
# agent_main_loop.sh — VM 启动后持续监听 inbox 的守护进程
# 由 inittab ::sysinit 以 root 身份在后台启动
#

set -e

BRIDGE_DIR="/mnt/agent_bridge"
INBOX_DIR="$BRIDGE_DIR/inbox"
DONE_DIR="$BRIDGE_DIR/done"
RUNS_LOG="/var/log/sandbox/tasks/agent_runs.jsonl"
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
    mkdir -p "$(dirname "$RUNS_LOG")" 2>/dev/null || true
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
    echo "[agent-daemon] AgentOS daemon started, watching: $INBOX_DIR"

    # 等待 inbox 就绪（最多等 60 秒，等 9P mount 完成）
    local count=0
    while [ ! -d "$INBOX_DIR" ] && [ $count -lt 30 ]; do
        sleep 2
        count=$((count + 1))
    done

    if [ -d "$INBOX_DIR" ]; then
        echo "[agent-daemon] Inbox ready: $INBOX_DIR"
    else
        echo "[agent-daemon] WARNING: inbox not found at $INBOX_DIR after 60s"
    fi

    # 立即处理已有任务
    process_inbox || true

    # 持续监听
    while true; do
        sleep 5
        process_inbox || true
    done
}

main
