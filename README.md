# AgentOS

AgentOS 是一个沙箱化的 Agent 运行时，通过宿主机代理访问 LLM API，VM 内无网络访问能力。

## 架构

```
┌─────────────────┐                    ┌─────────────────┐
│   宿主机 (Host)  │                    │   VM (沙箱)      │
│                 │                    │                 │
│  llm_proxy.py   │◄── /mnt/agent_bridge ──►│  agent_runner  │
│  (LLM API 代理) │      (共享文件夹)      │                 │
│                 │                    │  wrapper scripts │
└─────────────────┘                    └─────────────────┘
```

- **VM**：Agent 运行时和沙箱，无网络访问，通过 wrapper 脚本操作受限资源
- **宿主机**：有网络访问，作为 LLM API 代理
- **通信**：通过共享文件夹的 JSON 文件协议

## 共享文件夹

```
/mnt/agent_bridge/
├── inbox/       # 宿主机写入响应
├── outbox/      # VM 写入请求
├── done/        # 已处理的请求（归档）
└── error/       # 失败的请求
```

## 协议

### 请求（VM → 宿主机）

写入 `/mnt/agent_bridge/outbox/<request_id>.json`：

```json
{
  "request_id": "llm-task001-001",
  "ts": "2026-04-09T05:00:00Z",
  "task_id": "task001",
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "任务描述"}
  ],
  "temperature": 0.2,
  "max_tokens": 300
}
```

### 响应（宿主机 → VM）

写入 `/mnt/agent_bridge/inbox/<request_id>.json`：

```json
{
  "request_id": "llm-task001-001",
  "ts": "2026-04-09T05:00:01Z",
  "ok": true,
  "assistant_text": "...",
  "raw_response": {"finish_reason": "stop"},
  "error": null
}
```

## 快速开始

### 1. 宿主机启动 LLM 代理

```bash
export OPENAI_API_KEY="sk-..."

python3 llm_proxy.py --model gpt-4
```

### 2. VM 内运行 Agent

```bash
python3 agent_runner.py --task-id task001 --task "你的任务描述"
```

## Wrapper 脚本

所有脚本位于 `/opt/sandbox/bin/`，提供沙箱内的受限操作能力。

### fs_wrapper.sh — 文件系统

| 命令 | 说明 |
|------|------|
| `fs_wrapper.sh read <path>` | 读取文件 |
| `fs_wrapper.sh write <path> <content>` | 写入文件 |
| `fs_wrapper.sh list <path>` | 列出目录 |

**路径策略：**

| 路径 | read | write | list |
|------|:----:|:------:|:----:|
| /workspace | ✓ | ✓ | ✓ |
| /protected | ✓ | ✗ | ✓ |
| 其他 | ✗ | ✗ | ✗ |

### shell_wrapper.sh — Shell 命令

```bash
shell_wrapper.sh "<command>"
```

### sys_wrapper.sh — 系统信息

```bash
sys_wrapper.sh cpu|memory|disk|uptime|load|info|summary
```

### proc_wrapper.sh — 进程管理

```bash
proc_wrapper.sh list|top|tree|grep <pattern>|pids <pattern>|stat <pid>|threads <pid>|limits <pid>
```

### network_wrapper.sh — 网络操作

```bash
network_wrapper.sh status|ping <host> [count]|dns <domain>|curl <url>|connect <host> <port>
```

### sqlite_wrapper.sh — SQLite 数据库

```bash
sqlite_wrapper.sh version|init <db>|exec <db> <sql>|query <db> <sql>|tables <db>|schema <db>|info <db>|vacuum <db>|backup <db> <backup>|export <db>|import <db> <file>
```

### log_wrapper.sh — 日志查看

```bash
log_wrapper.sh list|tail <file> [lines]|head <file> [lines]|errors <file>
```

### service_wrapper.sh — 服务管理

```bash
service_wrapper.sh list|status <name>|start <name>|stop <name>|restart <name>
```

### cron_wrapper.sh — Cron 任务

```bash
cron_wrapper.sh list|next|service start|service stop|service status|add "<cron_expr>" <command>|remove <id>
```

## 日志

| 类型 | 路径 |
|------|------|
| Agent Transcript | `/var/log/sandbox/agent/transcript.jsonl` |
| Sandbox Trace | `/var/log/sandbox/trace/trace.jsonl` |
| LLM Proxy | `/tmp/llm_proxy.log` |

## 测试

```bash
/opt/sandbox/bin/test_wrappers.sh
```
