#!/usr/bin/env python3
"""
agent_runner.py — AgentOS 运行时（VM 内运行）

功能：
  - 读取任务描述，构建 system prompt
  - 通过共享文件夹与宿主机通信获取 LLM 回复
  - 解析并执行 JSON 格式的工具调用
  - 记录 transcript 日志

用法：
  python3 agent_runner.py --task-id <task_id> --task "<task description>"
  python3 agent_runner.py --task-file <file>
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# 配置路径
BRIDGE_DIR = Path(os.environ.get("AGENT_BRIDGE_DIR", "/mnt/agent_bridge"))
INBOX_DIR = BRIDGE_DIR / "inbox"
OUTBOX_DIR = BRIDGE_DIR / "outbox"
DONE_DIR = BRIDGE_DIR / "done"
ERROR_DIR = BRIDGE_DIR / "error"
TRANSCRIPT_LOG = Path(os.environ.get("AGENT_TRANSCRIPT_LOG", "/var/log/sandbox/agent/transcript.jsonl"))

# 常量
MAX_STEPS = 8
REQUEST_TIMEOUT = 60
POLL_INTERVAL = 1


class AgentRunner:
    """Agent 运行器"""

    def __init__(self, task_id: str, task: str):
        self.task_id = task_id
        self.task = task
        self.messages: list[dict[str, str]] = []
        self.step = 0
        self.conversation_history: list[dict[str, Any]] = []

        # 确保目录存在
        for d in [INBOX_DIR, OUTBOX_DIR, DONE_DIR, ERROR_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        self._setup_logging()

    def _setup_logging(self) -> None:
        """配置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.StreamHandler(sys.stderr)]
        )
        self.logger = logging.getLogger("agent_runner")

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        """原子写入 JSON 文件"""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        tmp.rename(path)

    def _log_transcript(self, event: str, data: dict[str, Any]) -> None:
        """记录 transcript 日志"""
        TRANSCRIPT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "step": self.step,
            "event": event,
            **data
        }
        with TRANSCRIPT_LOG.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return """你是一个谨慎的文件操作助手。

可用工具：
1. fs list <路径>    - 列出目录内容
2. fs read <路径>    - 读取文件内容
3. fs write <路径> <内容> - 写入文件（仅 /workspace）
4. shell <命令>      - 执行 shell 命令
5. network <操作> [参数] - 网络操作
   - network status           : 查看网络状态（网卡、路由、DNS）
   - network ping <host> [count] : ping 测试（默认4次）
   - network dns <domain>    : DNS 查询
   - network curl <url>      : HTTP 请求
   - network wget <url> [output] : 下载文件
   - network connect <host> <port> : TCP 连接测试
   - network ports <host> [ports] : 端口扫描

规则：
- 每次只能输出一个 JSON 对象
- 文件路径必须用绝对路径
- 只在必要时使用 shell，大部分操作用 fs 工具
- network 工具用于网络诊断和 HTTP 请求
- 完成后输出 final 工具

输出格式示例：
{"tool":"fs","action":"list","path":"/workspace"}
{"tool":"fs","action":"read","path":"/workspace/config.json"}
{"tool":"fs","action":"write","path":"/workspace/out.txt","content":"hello"}
{"tool":"shell","command":"ls -la /workspace"}
{"tool":"network","action":"status"}
{"tool":"network","action":"ping","host":"baidu.com","count":3}
{"tool":"network","action":"curl","url":"https://api.github.com"}
{"tool":"network","action":"wget","url":"http://example.com/file.zip","output":"/workspace/file.zip"}
{"tool":"final","answer":"任务完成"}"""

    def _send_llm_request(self) -> Optional[dict[str, Any]]:
        """发送 LLM 请求到宿主机"""
        request_id = f"llm-{self.task_id}-{self.step:03d}"

        request = {
            "request_id": request_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "messages": self.messages,
            "temperature": 0.2,
            "max_tokens": 300
        }

        outbox_path = OUTBOX_DIR / f"{request_id}.json"
        self._atomic_write_json(outbox_path, request)
        self._log_transcript("llm_request_sent", {"request_id": request_id})
        self.logger.info(f"Sent LLM request: {request_id}")

        # 等待响应
        inbox_path = INBOX_DIR / f"{request_id}.json"
        start_time = time.time()

        while time.time() - start_time < REQUEST_TIMEOUT:
            if inbox_path.exists():
                try:
                    response = json.loads(inbox_path.read_text())
                    # 移动到 done 目录
                    done_path = DONE_DIR / f"{request_id}.json"
                    inbox_path.rename(done_path)
                    self._log_transcript("llm_response_received", {"request_id": request_id, "ok": response.get("ok")})
                    return response
                except (json.JSONDecodeError, OSError) as e:
                    self.logger.error(f"Failed to read response: {e}")
                    # 移到 error 目录
                    error_path = ERROR_DIR / f"{request_id}.json"
                    inbox_path.rename(error_path)
                    return None

            time.sleep(POLL_INTERVAL)

        self.logger.error(f"LLM request timeout: {request_id}")
        self._log_transcript("llm_request_timeout", {"request_id": request_id})
        return None

    def _parse_tool_call(self, text: str) -> Optional[dict[str, Any]]:
        """解析工具调用 JSON"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试在文本中查找 JSON 对象
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    def _execute_fs_tool(self, action: str, path: str, content: Optional[str] = None) -> str:
        """执行 fs 工具"""
        wrapper = "/opt/sandbox/bin/fs_wrapper.sh"

        if action == "list":
            result = subprocess.run(
                [wrapper, f"list {path}"],
                capture_output=True, text=True
            )
        elif action == "read":
            result = subprocess.run(
                [wrapper, f"read {path}"],
                capture_output=True, text=True
            )
        elif action == "write":
            if not content:
                return "ERROR: write requires content"
            result = subprocess.run(
                ["sh", "-c", f"printf '%s' {json.dumps(content)} | {wrapper} 'write {path}'"],
                capture_output=True, text=True
            )
        else:
            return f"ERROR: unknown fs action: {action}"

        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip() if result.stdout else "OK"

    def _execute_shell_tool(self, command: str) -> str:
        """执行 shell 工具"""
        wrapper = "/opt/sandbox/bin/shell_wrapper.sh"
        result = subprocess.run(
            [wrapper, command],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip() if result.stdout else "OK"

    def _execute_network_tool(self, action: str, **kwargs: Any) -> str:
        """执行 network 工具"""
        wrapper = "/opt/sandbox/bin/network_wrapper.sh"

        if action == "status":
            result = subprocess.run(
                [wrapper, "status"],
                capture_output=True, text=True
            )
        elif action == "ping":
            host = kwargs.get("host", "")
            count = kwargs.get("count", 4)
            result = subprocess.run(
                [wrapper, "ping", host, str(count)],
                capture_output=True, text=True
            )
        elif action == "dns":
            domain = kwargs.get("domain", "")
            result = subprocess.run(
                [wrapper, "dns", domain],
                capture_output=True, text=True
            )
        elif action == "curl":
            url = kwargs.get("url", "")
            result = subprocess.run(
                [wrapper, "curl", url],
                capture_output=True, text=True
            )
        elif action == "wget":
            url = kwargs.get("url", "")
            output = kwargs.get("output", "-")
            result = subprocess.run(
                [wrapper, "wget", url, output],
                capture_output=True, text=True
            )
        elif action == "connect":
            host = kwargs.get("host", "")
            port = kwargs.get("port", "")
            result = subprocess.run(
                [wrapper, "connect", host, str(port)],
                capture_output=True, text=True
            )
        elif action == "ports":
            host = kwargs.get("host", "")
            ports = kwargs.get("ports", "80,443,22,8080")
            result = subprocess.run(
                [wrapper, "ports", host, ports],
                capture_output=True, text=True
            )
        elif action == "traceroute":
            host = kwargs.get("host", "")
            result = subprocess.run(
                [wrapper, "traceroute", host],
                capture_output=True, text=True
            )
        elif action == "speedtest":
            result = subprocess.run(
                [wrapper, "speedtest"],
                capture_output=True, text=True
            )
        else:
            return f"ERROR: unknown network action: {action}"

        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip() if result.stdout else "OK"

    def _execute_tool(self, tool_call: dict[str, Any]) -> str:
        """执行工具调用"""
        tool = tool_call.get("tool", "")

        if tool == "fs":
            return self._execute_fs_tool(
                tool_call.get("action", ""),
                tool_call.get("path", ""),
                tool_call.get("content")
            )
        elif tool == "shell":
            return self._execute_shell_tool(tool_call.get("command", ""))
        elif tool == "network":
            return self._execute_network_tool(
                tool_call.get("action", ""),
                host=tool_call.get("host", ""),
                count=tool_call.get("count", 4),
                domain=tool_call.get("domain", ""),
                url=tool_call.get("url", ""),
                output=tool_call.get("output", ""),
                port=tool_call.get("port", ""),
                ports=tool_call.get("ports", "")
            )
        elif tool == "final":
            return f"FINAL: {tool_call.get('answer', '')}"
        else:
            return f"ERROR: unknown tool: {tool}"

    def run(self) -> dict[str, Any]:
        """运行 agent"""
        self.logger.info(f"Starting agent for task: {self.task_id}")

        # 构建初始消息
        self.messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": f"任务：{self.task}"}
        ]

        while self.step < MAX_STEPS:
            self.step += 1
            self.logger.info(f"Step {self.step}/{MAX_STEPS}")

            # 发送 LLM 请求
            response = self._send_llm_request()

            if not response:
                error_msg = f"LLM request failed after {REQUEST_TIMEOUT}s"
                self.messages.append({
                    "role": "user",
                    "content": f"[Step {self.step}] Error: {error_msg}. 请重试。"
                })
                self.conversation_history.append({
                    "step": self.step,
                    "request": None,
                    "response": None,
                    "error": error_msg
                })
                continue

            if not response.get("ok"):
                error_msg = response.get("error", "Unknown error")
                self.messages.append({
                    "role": "user",
                    "content": f"[Step {self.step}] LLM API Error: {error_msg}. 请重试。"
                })
                self.conversation_history.append({
                    "step": self.step,
                    "request": None,
                    "response": response,
                    "error": error_msg
                })
                continue

            # 获取 assistant 回复
            assistant_text = response.get("assistant_text", "")
            self.messages.append({"role": "assistant", "content": assistant_text})

            # 解析工具调用
            tool_call = self._parse_tool_call(assistant_text)

            if not tool_call:
                error_msg = "模型输出不是有效的 JSON"
                self.logger.warning(f"Invalid JSON from model: {assistant_text[:200]}")
                self.messages.append({
                    "role": "user",
                    "content": f"[Step {self.step}] Error: {error_msg}。请输出正确的 JSON 格式。"
                })
                self.conversation_history.append({
                    "step": self.step,
                    "request": self.messages[-2:],
                    "response": assistant_text,
                    "tool_call": None,
                    "error": error_msg
                })
                continue

            self._log_transcript("tool_call", {"tool_call": tool_call})
            self.logger.info(f"Tool call: {tool_call}")

            # 检查是否是 final
            if tool_call.get("tool") == "final":
                answer = tool_call.get("answer", "")
                self._log_transcript("final_answer", {"answer": answer})
                self.logger.info(f"Final answer: {answer}")
                return {"status": "success", "answer": answer, "steps": self.step}

            # 执行工具
            result = self._execute_tool(tool_call)
            self._log_transcript("tool_result", {"tool_call": tool_call, "result": result})
            self.logger.info(f"Tool result: {result[:200]}...")

            # 添加结果到对话
            self.messages.append({
                "role": "user",
                "content": f"[Step {self.step}] Tool result:\n{result}"
            })

            self.conversation_history.append({
                "step": self.step,
                "tool_call": tool_call,
                "result": result
            })

        # 超过最大步数
        self._log_transcript("max_steps_reached", {"steps": self.step})
        self.logger.warning(f"Max steps ({MAX_STEPS}) reached")
        return {
            "status": "max_steps",
            "message": f"达到最大步数限制 ({MAX_STEPS})",
            "steps": self.step
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS Agent Runner")
    parser.add_argument("--task-id", required=True, help="任务 ID")
    parser.add_argument("--task", help="任务描述")
    parser.add_argument("--task-file", help="任务文件路径")
    args = parser.parse_args()

    # 获取任务描述
    if args.task_file:
        task = Path(args.task_file).read_text().strip()
    elif args.task:
        task = args.task
    else:
        print("Error: 必须提供 --task 或 --task-file", file=sys.stderr)
        sys.exit(1)

    # 运行 agent
    runner = AgentRunner(args.task_id, task)
    result = runner.run()

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
