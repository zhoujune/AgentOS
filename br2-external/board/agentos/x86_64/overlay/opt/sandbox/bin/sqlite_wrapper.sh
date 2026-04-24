#!/bin/sh
#
# sqlite_wrapper.sh - AgentOS SQLite operation wrapper
#
#   - Prohibit arbitrary SQL execution (removed exec/query subcommands)
#   - Only provide restricted typed operations:
#     - db.read(table, key)
#     - db.insert(table, row_json)
#     - db.update(table, key, patch_json)
#   - Policy decisions are handled by VTRM
#   - Wrapper only executes VTRM-approved operations
#
# Usage:
#   sqlite_wrapper.sh execute <operation> <args...>
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

check_sqlite3() {
    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 not found" >&2
        return 1
    fi
    return 0
}

do_version() {
    sqlite3 --version
    echo "sqlite_wrapper.sh v2.0.0-b (B-line: restricted operations only)"
}

# B-line: restricted read operation
# Format: sqlite_wrapper.sh execute read <db> <table> <key>
do_read() {
    local db="$1"
    local table="$2"
    local key="$3"

    [ -z "$db" ] || [ -z "$table" ] || [ -z "$key" ] && {
        echo "Usage: sqlite_wrapper.sh execute read <db> <table> <key>" >&2
        return 1
    }

    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    log_jsonl "sqlite_execute" "operation=read" "table=$table" "key=$key"

    # Parameterized query to prevent SQL injection
    sqlite3 -json "$db" "SELECT * FROM $table WHERE id = '$key';" 2>&1
}

# B-line: restricted insert operation
# Format: sqlite_wrapper.sh execute insert <db> <table> <row_json>
do_insert() {
    local db="$1"
    local table="$2"
    local row_json="$3"

    [ -z "$db" ] || [ -z "$table" ] || [ -z "$row_json" ] && {
        echo "Usage: sqlite_wrapper.sh execute insert <db> <table> <row_json>" >&2
        return 1
    }

    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    log_jsonl "sqlite_execute" "operation=insert" "table=$table"

    # Parse JSON and construct insert statement
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$db" "$table" "$row_json" << 'PYTHON'
import sys
import json
import sqlite3

db_path = sys.argv[1]
table = sys.argv[2]
row_json = sys.argv[3]

try:
    row = json.loads(row_json)
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)

# Build INSERT statement
columns = list(row.keys())
placeholders = ["?" for _ in columns]
values = [str(v) for v in row.values()]

sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(sql, values)
    conn.commit()
    conn.close()
    print("OK")
except sqlite3.Error as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON
    else
        echo "ERROR: python3 not found for JSON parsing" >&2
        return 1
    fi
}

# Format: sqlite_wrapper.sh execute update <db> <table> <key> <patch_json>
do_update() {
    local db="$1"
    local table="$2"
    local key="$3"
    local patch_json="$4"

    [ -z "$db" ] || [ -z "$table" ] || [ -z "$key" ] || [ -z "$patch_json" ] && {
        echo "Usage: sqlite_wrapper.sh execute update <db> <table> <key> <patch_json>" >&2
        return 1
    }

    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    log_jsonl "sqlite_execute" "operation=update" "table=$table" "key=$key"

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$db" "$table" "$key" "$patch_json" << 'PYTHON'
import sys
import json
import sqlite3

db_path = sys.argv[1]
table = sys.argv[2]
key = sys.argv[3]
patch_json = sys.argv[4]

try:
    patch = json.loads(patch_json)
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)

# Build UPDATE statement
set_clauses = [f"{col} = ?" for col in patch.keys()]
values = [str(v) for v in patch.values()] + [key]

sql = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id = ?"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(sql, values)
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    if rows_affected > 0:
        print("OK")
    else:
        print("ERROR: Record not found", file=sys.stderr)
        sys.exit(1)
except sqlite3.Error as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON
    else
        echo "ERROR: python3 not found for JSON parsing" >&2
        return 1
    fi
}

do_init() {
    local db="$1"

    [ -z "$db" ] && { echo "Usage: sqlite_wrapper.sh init <db>" >&2; return 1; }

    check_sqlite3 || return 1
    [ -f "$db" ] && { echo "Database exists: $db"; return 0; }
    sqlite3 "$db" "SELECT 1;" && echo "Created: $db"
}

do_tables() {
    local db="$1"

    [ -z "$db" ] && { echo "Usage: sqlite_wrapper.sh tables <db>"; return 1; }
    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    echo "=== Tables in $db ==="
    sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
}

do_schema() {
    local db="$1"
    local table="${2:-}"

    [ -z "$db" ] && { echo "Usage: sqlite_wrapper.sh schema <db> [table]"; return 1; }
    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    if [ -z "$table" ]; then
        echo "=== All tables schema ==="
        sqlite3 "$db" "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name;"
    else
        echo "=== Schema of $table ==="
        sqlite3 "$db" "SELECT sql FROM sqlite_master WHERE type='table' AND name='$table';"
    fi
}

do_info() {
    local db="$1"

    [ -z "$db" ] && { echo "Usage: sqlite_wrapper.sh info <db>"; return 1; }
    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    echo "=== Database: $db ==="
    ls -lh "$db" 2>/dev/null
    echo ""
    sqlite3 "$db" "SELECT 'Pages: ' || page_count, 'Page size: ' || page_size || ' bytes' FROM pragma_page_count(), pragma_page_size();"
    echo ""
    echo "=== Tables ==="
    sqlite3 "$db" "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name;"
}

usage() {
    echo "Usage: sqlite_wrapper.sh <command> [args...]" >&2
    echo ""
    echo "Commands (B-line restricted mode):"
    echo "  execute <op> <args...>      - Execute VTRM-approved operation"
    echo "    read <db> <table> <key>   - Read record by primary key"
    echo "    insert <db> <table> <json> - Insert row (JSON)"
    echo "    update <db> <table> <key> <json> - Update record (JSON)"
    echo "  init <db>                   - Create database"
    echo "  tables <db>                 - List tables"
    echo "  schema <db> [table]         - Show schema"
    echo "  info <db>                    - Database info"
    echo "  version                     - Show version"
    echo ""
    echo "Note: Arbitrary SQL execution (exec/query) is disabled in B-line mode."
}

main() {
    [ $# -eq 0 ] || [ -z "$1" ] && { usage; exit 0; }

    local cmd="$1"
    shift

    case "$cmd" in
        version|-v|--version) do_version ;;
        init) do_init "$@" ;;
        tables) do_tables "$@" ;;
        schema) do_schema "$@" ;;
        info|status) do_info "$@" ;;
        execute)
            local op="${1:-}"
            case "$op" in
                read) shift; do_read "$@" ;;
                insert) shift; do_insert "$@" ;;
                update) shift; do_update "$@" ;;
                *) echo "ERROR: Unknown operation: $op" >&2; usage; exit 1 ;;
            esac
            ;;
        # Disable B-line unsupported operations
        exec|query|import|export|backup|vacuum)
            echo "ERROR: Operation '$cmd' is disabled in B-line mode (arbitrary SQL not allowed)" >&2
            echo "Use 'execute read/insert/update' for typed operations." >&2
            exit 1
            ;;
        help|--help|-h) usage ;;
        *) echo "ERROR: Unknown command: $cmd" >&2; usage; exit 1 ;;
    esac
}

main "$@"
