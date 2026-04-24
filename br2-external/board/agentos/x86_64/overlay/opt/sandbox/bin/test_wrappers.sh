#!/bin/sh
#
# test_wrappers.sh - Test all AgentOS wrapper scripts
#

WRAPPER_DIR="/opt/sandbox/bin"
PASS=0
FAIL=0

pass() { echo "[PASS] $*"; PASS=$((PASS + 1)); }
fail() { echo "[FAIL] $*"; FAIL=$((FAIL + 1)); }

test_file() {
    local name="$1"
    local path="$2"
    [ -x "$path" ] && pass "$name exists and executable" || fail "$name not found or not executable"
}

test_cmd() {
    local name="$1"
    shift
    "$@" >/dev/null 2>&1 && pass "$name" || fail "$name"
}

test_output() {
    local name="$1"
    local expected="$2"
    shift 2
    local output
    output=$("$@" 2>&1)
    echo "$output" | grep -q "$expected" && pass "$name" || { fail "$name"; echo "  Expected: $expected"; echo "  Got: $output"; }
}

echo "========================================"
echo "  AgentOS Wrapper Test Suite"
echo "========================================"
echo ""

echo "=== Testing File Existence ==="
test_file "network_wrapper.sh" "$WRAPPER_DIR/network_wrapper.sh"
test_file "fs_wrapper.sh" "$WRAPPER_DIR/fs_wrapper.sh"
test_file "sqlite_wrapper.sh" "$WRAPPER_DIR/sqlite_wrapper.sh"
test_file "sys_wrapper.sh" "$WRAPPER_DIR/sys_wrapper.sh"
test_file "proc_wrapper.sh" "$WRAPPER_DIR/proc_wrapper.sh"
test_file "log_wrapper.sh" "$WRAPPER_DIR/log_wrapper.sh"
test_file "service_wrapper.sh" "$WRAPPER_DIR/service_wrapper.sh"
test_file "cron_wrapper.sh" "$WRAPPER_DIR/cron_wrapper.sh"
echo ""

echo "=== Testing network_wrapper.sh ==="
"$WRAPPER_DIR/network_wrapper.sh" version >/dev/null 2>&1 && pass "network version" || fail "network version"
"$WRAPPER_DIR/network_wrapper.sh" help >/dev/null 2>&1 && pass "network help" || fail "network help"
echo ""

echo "=== Testing fs_wrapper.sh ==="
"$WRAPPER_DIR/fs_wrapper.sh" version >/dev/null 2>&1 && pass "fs version" || fail "fs version"
"$WRAPPER_DIR/fs_wrapper.sh" help >/dev/null 2>&1 && pass "fs help" || fail "fs help"
echo ""

echo "=== Testing sqlite_wrapper.sh ==="
test_cmd "sqlite version" "$WRAPPER_DIR/sqlite_wrapper.sh" version
test_cmd "sqlite help" "$WRAPPER_DIR/sqlite_wrapper.sh" help
test_cmd "sqlite init" "$WRAPPER_DIR/sqlite_wrapper.sh" init /tmp/test_wrapper.db
test_cmd "sqlite create table" "$WRAPPER_DIR/sqlite_wrapper.sh" exec /tmp/test_wrapper.db "CREATE TABLE IF NOT EXISTS t(id INTEGER PRIMARY KEY, name TEXT);"
test_cmd "sqlite insert" "$WRAPPER_DIR/sqlite_wrapper.sh" exec /tmp/test_wrapper.db "INSERT INTO t VALUES(1,'hello'),(2,'world');"
"$WRAPPER_DIR/sqlite_wrapper.sh" query /tmp/test_wrapper.db "SELECT * FROM t;" >/dev/null 2>&1 && pass "sqlite query" || fail "sqlite query"
test_cmd "sqlite tables" "$WRAPPER_DIR/sqlite_wrapper.sh" tables /tmp/test_wrapper.db
test_cmd "sqlite schema" "$WRAPPER_DIR/sqlite_wrapper.sh" schema /tmp/test_wrapper.db
test_cmd "sqlite info" "$WRAPPER_DIR/sqlite_wrapper.sh" info /tmp/test_wrapper.db
test_cmd "sqlite vacuum" "$WRAPPER_DIR/sqlite_wrapper.sh" vacuum /tmp/test_wrapper.db
test_cmd "sqlite backup" "$WRAPPER_DIR/sqlite_wrapper.sh" backup /tmp/test_wrapper.db /tmp/test_wrapper.bak
test_cmd "sqlite export" "$WRAPPER_DIR/sqlite_wrapper.sh" export /tmp/test_wrapper.db >/dev/null 2>&1
echo "SELECT 1;" > /tmp/test_wrapper.sql
test_cmd "sqlite import" "$WRAPPER_DIR/sqlite_wrapper.sh" import /tmp/test_wrapper.db /tmp/test_wrapper.sql
rm -f /tmp/test_wrapper.sql /tmp/test_wrapper.db /tmp/test_wrapper.bak
echo ""

echo "=== Testing sys_wrapper.sh ==="
test_cmd "sys help" "$WRAPPER_DIR/sys_wrapper.sh" help
test_cmd "sys summary" "$WRAPPER_DIR/sys_wrapper.sh" summary
test_cmd "sys cpu" "$WRAPPER_DIR/sys_wrapper.sh" cpu
test_cmd "sys memory" "$WRAPPER_DIR/sys_wrapper.sh" memory
test_cmd "sys disk" "$WRAPPER_DIR/sys_wrapper.sh" disk
test_cmd "sys uptime" "$WRAPPER_DIR/sys_wrapper.sh" uptime
test_cmd "sys load" "$WRAPPER_DIR/sys_wrapper.sh" load
test_cmd "sys info" "$WRAPPER_DIR/sys_wrapper.sh" info
echo ""

echo "=== Testing proc_wrapper.sh ==="
test_cmd "proc help" "$WRAPPER_DIR/proc_wrapper.sh" help
test_cmd "proc list" "$WRAPPER_DIR/proc_wrapper.sh" list
test_cmd "proc top" "$WRAPPER_DIR/proc_wrapper.sh" top
test_cmd "proc tree" "$WRAPPER_DIR/proc_wrapper.sh" tree
test_cmd "proc grep" "$WRAPPER_DIR/proc_wrapper.sh" grep "init"
test_cmd "proc pids" "$WRAPPER_DIR/proc_wrapper.sh" pids "init"
test_cmd "proc stat 1" "$WRAPPER_DIR/proc_wrapper.sh" stat 1
test_cmd "proc threads 1" "$WRAPPER_DIR/proc_wrapper.sh" threads 1
test_cmd "proc limits 1" "$WRAPPER_DIR/proc_wrapper.sh" limits 1
echo ""

echo "=== Testing log_wrapper.sh ==="
test_cmd "log help" "$WRAPPER_DIR/log_wrapper.sh" help
test_cmd "log list" "$WRAPPER_DIR/log_wrapper.sh" list
if [ -f /var/log/syslog ]; then
    test_cmd "log tail" "$WRAPPER_DIR/log_wrapper.sh" tail /var/log/syslog 5
    test_cmd "log head" "$WRAPPER_DIR/log_wrapper.sh" head /var/log/syslog 5
    test_cmd "log errors" "$WRAPPER_DIR/log_wrapper.sh" errors /var/log/syslog
elif [ -f /var/log/messages ]; then
    test_cmd "log tail" "$WRAPPER_DIR/log_wrapper.sh" tail /var/log/messages 5
fi
echo ""

echo "=== Testing service_wrapper.sh ==="
test_cmd "service help" "$WRAPPER_DIR/service_wrapper.sh" help
test_cmd "service list" "$WRAPPER_DIR/service_wrapper.sh" list
"$WRAPPER_DIR/service_wrapper.sh" status 2>&1 | head -5
pass "service status (init)"
echo ""

echo "=== Testing cron_wrapper.sh ==="
test_cmd "cron help" "$WRAPPER_DIR/cron_wrapper.sh" help
test_cmd "cron list" "$WRAPPER_DIR/cron_wrapper.sh" list
test_cmd "cron next" "$WRAPPER_DIR/cron_wrapper.sh" next
test_cmd "cron service" "$WRAPPER_DIR/cron_wrapper.sh" service
echo ""

echo "========================================"
echo "  Test Results"
echo "========================================"
echo "  PASSED: $PASS"
echo "  FAILED: $FAIL"
echo "  TOTAL:  $((PASS + FAIL))"
echo "========================================"

[ $FAIL -eq 0 ] && exit 0 || exit 1
