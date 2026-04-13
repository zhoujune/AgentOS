#!/bin/sh
#
# sqlite_wrapper.sh - AgentOS SQLite 操作包装器
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

log_error() {
    echo "ERROR: $*" >&2
    log_jsonl "sqlite_error" "reason=$*"
}

check_sqlite3() {
    if ! command -v sqlite3 >/dev/null 2>&1; then
        log_error "sqlite3_not_found"
        echo "ERROR: sqlite3 not found"
        return 1
    fi
    return 0
}

do_version() {
    sqlite3 --version
}

do_query() {
    local db="$1"
    local sql="$2"

    if [ -z "$db" ] || [ -z "$sql" ]; then
        echo "Usage: sqlite_wrapper.sh query <db> <sql>"
        return 1
    fi

    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    sqlite3 -header -column "$db" "$sql" 2>&1
}

do_exec() {
    local db="$1"
    local sql="$2"

    if [ -z "$db" ] || [ -z "$sql" ]; then
        echo "Usage: sqlite_wrapper.sh exec <db> <sql>"
        return 1
    fi

    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    sqlite3 "$db" "$sql" 2>&1
}

do_init() {
    local db="$1"

    if [ -z "$db" ]; then
        echo "Usage: sqlite_wrapper.sh init <db>"
        return 1
    fi

    check_sqlite3 || return 1
    [ -f "$db" ] && { echo "Database exists: $db"; return 0; }
    sqlite3 "$db" "SELECT 1;" && echo "Created: $db"
}

do_tables() {
    local db="$1"

    if [ -z "$db" ]; then
        echo "Usage: sqlite_wrapper.sh tables <db>"
        return 1
    fi

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

do_import() {
    local db="$1"
    local sqlfile="$2"

    if [ -z "$db" ] || [ -z "$sqlfile" ]; then
        echo "Usage: sqlite_wrapper.sh import <db> <sqlfile>"
        return 1
    fi

    [ -f "$sqlfile" ] || { echo "ERROR: SQL file not found: $sqlfile"; return 1; }
    check_sqlite3 || return 1

    echo "Importing $sqlfile into $db..."
    sqlite3 "$db" < "$sqlfile" && echo "Import complete"
}

do_export() {
    local db="$1"
    local table="${2:-}"

    [ -z "$db" ] && { echo "Usage: sqlite_wrapper.sh export <db> [table]"; return 1; }
    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    if [ -z "$table" ]; then
        sqlite3 "$db" ".dump"
    else
        sqlite3 "$db" ".dump '$table'"
    fi
}

do_backup() {
    local db="$1"
    local backup="$2"

    if [ -z "$db" ] || [ -z "$backup" ]; then
        echo "Usage: sqlite_wrapper.sh backup <db> <backupfile>"
        return 1
    fi

    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    echo "Backing up $db to $backup..."
    sqlite3 "$db" ".backup '$backup'" && echo "Backup complete: $backup"
    log_jsonl "sqlite_backup" "source=$db" "dest=$backup"
}

do_vacuum() {
    local db="$1"

    [ -z "$db" ] && { echo "Usage: sqlite_wrapper.sh vacuum <db>"; return 1; }
    [ -f "$db" ] || { echo "ERROR: Database not found: $db"; return 1; }
    check_sqlite3 || return 1

    sqlite3 "$db" "VACUUM;" && echo "Vacuum complete"
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
    echo "Usage: sqlite_wrapper.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  version                   - SQLite version"
    echo "  query <db> <sql>         - Execute query (with headers)"
    echo "  exec <db> <sql>         - Execute SQL (DDL/DML)"
    echo "  init <db>                - Create database"
    echo "  tables <db>              - List tables"
    echo "  schema <db> [table]      - Show schema"
    echo "  import <db> <file>      - Import SQL file"
    echo "  export <db> [table]     - Export dump"
    echo "  backup <db> <file>      - Backup database"
    echo "  vacuum <db>              - Vacuum database"
    echo "  info <db>                - Database info"
    echo ""
    echo "Examples:"
    echo "  sqlite_wrapper.sh init /data/test.db"
    echo "  sqlite_wrapper.sh query /data/test.db 'SELECT * FROM users LIMIT 5;'"
    echo "  sqlite_wrapper.sh backup /data/test.db /data/test.bak"
}

main() {
    [ $# -eq 0 ] || [ -z "$1" ] && { usage; exit 0; }

    local cmd="$1"
    shift

    log_jsonl "sqlite_request" "command=$cmd" "args=$*"

    case "$cmd" in
        version|-v|--version) do_version "$@" ;;
        query) do_query "$@" ;;
        exec) do_exec "$@" ;;
        init) do_init "$@" ;;
        tables) do_tables "$@" ;;
        schema) do_schema "$@" ;;
        import) do_import "$@" ;;
        export|dump) do_export "$@" ;;
        backup) do_backup "$@" ;;
        vacuum) do_vacuum "$@" ;;
        info|status) do_info "$@" ;;
        help|--help|-h) usage ;;
        *) echo "ERROR: Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

main "$@"
