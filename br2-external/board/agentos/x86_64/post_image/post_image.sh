#!/bin/sh
set -e

# AgentOS post-image hook — runs after rootfs.tar is created
# At this point the tar is already sealed, so we can safely lock down
# permissions without breaking the build.
#
# $BINARIES_DIR — directory where final images are placed
# $TARGET_DIR  — the fakeroot directory (still present after post-build)

# ============================================================
# 1. 设置 protected 文件为只读
# ============================================================
find "$TARGET_DIR/protected" -type f -exec chmod 444 {} \;

# ============================================================
# 2. 限制 /secrets 目录
# ============================================================
chmod 700 "$TARGET_DIR/secrets"

# ============================================================
# 3. 预创建运行时文件（占位，空文件由 task-run 首次运行时替换）
#
# index.jsonl: append-only 日志索引，chmod 644 root:root，agent 只能 >>
# .seq.placeholder: 序号计数器模板，由 task-run 替换为 .seq.YYYYMMDD
# ============================================================
: >> "$TARGET_DIR/var/log/sandbox/tasks/index.jsonl"
chmod 644 "$TARGET_DIR/var/log/sandbox/tasks/index.jsonl"

: >> "$TARGET_DIR/var/log/sandbox/tasks/.seq.placeholder"
chmod 600 "$TARGET_DIR/var/log/sandbox/tasks/.seq.placeholder"

# ============================================================
# 4. 设置目录 sticky-bit（在 tar 打包时记录元数据）
#
# 权限已在 post_fakeroot.sh 中设置为 755 + agent:agent，
# 这里只补充 sticky-bit（o+t）。
# sticky-bit (o+t) 防止非文件所有者删除他人的文件。
#
# 注意：chown root:root 在 fakeroot 中会报错（fakeroot 无法伪造 UID），因此省略。
# 运行时 rcS.local 会重新 chown+chmod 一遍确保生效。
# ============================================================
mkdir -p "$TARGET_DIR/var/log/sandbox/tasks"
chmod 1755 "$TARGET_DIR/var/log/sandbox/tasks" 2>/dev/null || true

# ============================================================
# 5. 尝试为日志文件设置不可篡改追加位（append-only）
#
# chattr +a = ext2/3/4 文件系统属性：文件只能追加，不能截断或覆盖
#
# 构建时在 host Linux 上设置（在镜像打包之前）：
#   - index.jsonl — 必须追加锁定
#   - .seq.placeholder — 锁定占位文件，防止计数器被篡改
#
# 注意：
#   - AgentOS 使用 ext2 镜像 ✓
#   - 构建 host 必须是 Linux（WSL/GNU/Linux）才能执行 chattr
#   - macOS/其他系统静默跳过，仅依赖 chmod 提供软保护
#   - 运行时 rcS.local 会再次设置（兜底）
# ============================================================
if command -v chattr >/dev/null 2>&1; then
    # 只对 index.jsonl 设 append-only
    # 不对 .seq.placeholder 设 chattr +a：task-run 会 mv rename，+a 禁止 rename
    chattr +a "$TARGET_DIR/var/log/sandbox/tasks/index.jsonl"  2>/dev/null || true
fi