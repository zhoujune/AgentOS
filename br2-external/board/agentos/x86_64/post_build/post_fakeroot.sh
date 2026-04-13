#!/bin/sh
set -eu

TARGET_DIR="$1"

# ============================================================
# post-fakeroot：在 rootfs 树生成之后、ext2 镜像打包之前执行
# 此阶段在 fakeroot 上下文中运行，可以执行真正的 chown/chmod
# manul.md §9.5: fakeroot scripts 用于需要 root 权限的操作
# ============================================================

# ---- agent 需要的写权限目录 ----
# agent(UID 1000) 需要写 /workspace 和日志目录
# 注意：chown 需要在 chmod 之前，否则可能影响权限
chown 1000:1000 "$TARGET_DIR/workspace"
chown 1000:1000 "$TARGET_DIR/var/log/sandbox/tasks"
chown 1000:1000 "$TARGET_DIR/var/log/sandbox/trace"
chown 1000:1000 "$TARGET_DIR/home/agent"

# ---- 运行时生成的日志文件权限约定 ----
# index.jsonl: root:root 644，agent 只能追加（>>），无法截断
# *.log:       agent:agent 644，由 task-run 脚本自动创建
# .seq.YYYYMMDD: agent:agent 600，序号计数器
# .lock.seq:   agent:agent 600，flock 锁文件

# ---- 最终语义权限（固化到 ext2 镜像）----
chmod 555 "$TARGET_DIR/protected"
chmod 700 "$TARGET_DIR/secrets"
chmod 755 "$TARGET_DIR/workspace"
chmod 755 "$TARGET_DIR/var/log/sandbox"
chmod 755 "$TARGET_DIR/var/log/sandbox/trace"
chmod 1775 "$TARGET_DIR/var/log/sandbox/tasks"

chmod 644 "$TARGET_DIR/protected/DO_NOT_DELETE.txt"
chmod 600 "$TARGET_DIR/secrets/api_key.txt"