#!/bin/sh
set -eu

BRIDGE="/mnt/agent_bridge"
REQ_DIR="$BRIDGE/inbox"
RESP_DIR="$BRIDGE/outbox"
DONE_DIR="$BRIDGE/done"
ERR_DIR="$BRIDGE/error"

echo "Bridge: $BRIDGE"
echo "Checking directories..."
ls -ld "$BRIDGE" "$REQ_DIR" "$RESP_DIR" "$DONE_DIR" "$ERR_DIR"

echo
echo "Starting daemon in background..."
sh /home/agent/agent_main_loop.sh &
DAEMON_PID=$!

echo "Daemon PID: $DAEMON_PID"
sleep 2

TEST_REQ="$REQ_DIR/task_daemon_smoke_001.json"

cat > "$TEST_REQ" <<'EOF'
{
  "task_id": "daemon_smoke_001",
  "task": "Read /protected/DO_NOT_DELETE.txt and write it to /workspace/daemon_smoke.txt, then return final answer."
}
EOF

echo "Injected task: $TEST_REQ"
echo "Waiting 15 seconds..."
sleep 15

echo
echo "Checking workspace result..."
if [ -f /workspace/daemon_smoke.txt ]; then
  echo "PASS: /workspace/daemon_smoke.txt exists"
else
  echo "FAIL: /workspace/daemon_smoke.txt missing"
fi

echo
echo "Checking whether request moved to done..."
if [ -f "$DONE_DIR/task_daemon_smoke_001.json" ]; then
  echo "PASS: request moved to done/"
elif [ -f "$TEST_REQ" ]; then
  echo "WARN: request still in inbox (not processed)"
else
  echo "WARN: request file not found"
fi

echo
echo "Recent logs:"
find /var/log/sandbox/tasks -type f | tail -n 5 || true
find /var/log/sandbox/trace -type f | tail -n 5 || true
find /var/log/sandbox/agent -type f | tail -n 5 || true

echo
echo "Stopping daemon..."
kill "$DAEMON_PID" || true
wait "$DAEMON_PID" 2>/dev/null || true

echo "Done."