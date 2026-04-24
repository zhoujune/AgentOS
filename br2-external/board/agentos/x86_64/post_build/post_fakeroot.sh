#!/bin/sh
set -eu

TARGET_DIR="$1"


chown 1000:1000 "$TARGET_DIR/workspace"
chown 1000:1000 "$TARGET_DIR/var/log/sandbox/tasks"
chown 1000:1000 "$TARGET_DIR/var/log/sandbox/trace"
chown 1000:1000 "$TARGET_DIR/home/agent"


chmod 555 "$TARGET_DIR/protected"
chmod 700 "$TARGET_DIR/secrets"
chmod 755 "$TARGET_DIR/workspace"
chmod 755 "$TARGET_DIR/var/log/sandbox"
chmod 755 "$TARGET_DIR/var/log/sandbox/trace"
chmod 1775 "$TARGET_DIR/var/log/sandbox/tasks"

chmod 644 "$TARGET_DIR/protected/DO_NOT_DELETE.txt"
chmod 600 "$TARGET_DIR/secrets/api_key.txt"