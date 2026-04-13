#!/usr/bin/env python3
"""
test_pipeline.py — AgentOS 端到端测试脚本（VM 内运行）

简化流程：
1. 创建 LLM 请求到 outbox
2. 等待宿主机 llm_proxy 处理
3. 读取响应
4. 解析工具调用并执行
"""

import json
import sys
import time
from pathlib import Path

# 配置路径（假设 /mnt/agent_bridge 已挂载）
BRIDGE_DIR = Path("/mnt/agent_bridge")
OUTBOX_DIR = BRIDGE_DIR / "outbox"
INBOX_DIR = BRIDGE_DIR / "inbox"
DONE_DIR = BRIDGE_DIR / "done"

POLL_INTERVAL = 1
REQUEST_TIMEOUT = 120


def wait_for_bridge():
    """等待 bridge 挂载"""
    if not BRIDGE_DIR.exists():
        print(f"错误: {BRIDGE_DIR} 不存在，请先挂载 9P")
        sys.exit(1)
    print(f"✓ Bridge 已就绪: {BRIDGE_DIR}")


def create_llm_request(task: str, model: str = "Qwen/Qwen2.5-72B-Instruct") -> dict:
    """创建 LLM 请求"""
    request_id = f"test-{int(time.time())}"
    
    system_prompt = """你是一个谨慎的文件操作助手。

可用工具：
1. fs list <路径>    - 列出目录内容
2. fs read <路径>    - 读取文件内容
3. shell <命令>      - 执行 shell 命令

规则：
- 每次只能输出一个 JSON 对象
- 输出格式：{"tool":"fs","action":"list","path":"/workspace"}
- 完成后输出 final 工具：{"tool":"final","answer":"你的回答"}"""

    request = {
        "request_id": request_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"任务：{task}"}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    
    return request_id, request


def send_and_wait(request_id: str, request: dict) -> dict:
    """发送请求并等待响应"""
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    
    # 写入请求
    outbox_path = OUTBOX_DIR / f"{request_id}.json"
    tmp_path = outbox_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(request, ensure_ascii=False, indent=2))
    tmp_path.rename(outbox_path)
    
    print(f"✓ 请求已发送: {outbox_path}")
    print(f"  请确保宿主机上的 llm_proxy.py 正在运行...")
    
    # 等待响应
    inbox_path = INBOX_DIR / f"{request_id}.json"
    start_time = time.time()
    
    while time.time() - start_time < REQUEST_TIMEOUT:
        if inbox_path.exists():
            try:
                response = json.loads(inbox_path.read_text())
                print(f"✓ 收到响应: {response.get('ok', False)}")
                return response
            except Exception as e:
                print(f"响应读取失败: {e}")
        
        elapsed = int(time.time() - start_time)
        print(f"\r  等待响应... ({elapsed}s)", end="", flush=True)
        time.sleep(POLL_INTERVAL)
    
    print("\n✗ 请求超时")
    return {"ok": False, "error": "timeout"}


def parse_tool_call(text: str) -> dict:
    """解析工具调用"""
    try:
        return json.loads(text)
    except:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    return None


def execute_tool(tool_call: dict) -> str:
    """执行工具调用"""
    import subprocess
    
    tool = tool_call.get("tool", "")
    result = ""
    
    if tool == "fs":
        action = tool_call.get("action", "")
        path = tool_call.get("path", "/workspace")
        wrapper = "/opt/sandbox/bin/fs_wrapper.sh"
        
        cmd = f"{wrapper} {action} {path}"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        result = proc.stdout if proc.returncode == 0 else f"ERROR: {proc.stderr}"
    
    elif tool == "shell":
        command = tool_call.get("command", "")
        wrapper = "/opt/sandbox/bin/shell_wrapper.sh"
        
        proc = subprocess.run(f"{wrapper} '{command}'", shell=True, capture_output=True, text=True)
        result = proc.stdout if proc.returncode == 0 else f"ERROR: {proc.stderr}"
    
    elif tool == "final":
        result = f"FINAL: {tool_call.get('answer', '')}"
    
    else:
        result = f"ERROR: unknown tool {tool}"
    
    return result


def main():
    print("=" * 50)
    print("AgentOS 端到端测试")
    print("=" * 50)
    
    # 1. 检查 bridge
    wait_for_bridge()
    
    # 2. 获取任务描述
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = "你好，请用中文简单介绍一下自己，并用 JSON 格式输出"
    
    print(f"\n任务: {task}")
    
    # 3. 创建请求
    request_id, request = create_llm_request(task)
    
    # 4. 发送并等待响应
    response = send_and_wait(request_id, request)
    
    print("\n" + "=" * 50)
    print("响应内容:")
    print("=" * 50)
    
    if not response.get("ok"):
        print(f"✗ 失败: {response.get('error', 'unknown error')}")
        return 1
    
    assistant_text = response.get("assistant_text", "")
    print(assistant_text)
    
    # 5. 解析并执行工具
    tool_call = parse_tool_call(assistant_text)
    if tool_call:
        print("\n" + "=" * 50)
        print("执行工具调用:")
        print(json.dumps(tool_call, indent=2, ensure_ascii=False))
        print("-" * 50)
        
        result = execute_tool(tool_call)
        print(f"结果:\n{result}")
    
    print("\n" + "=" * 50)
    print("测试完成!")
    print("=" * 50)
    
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())