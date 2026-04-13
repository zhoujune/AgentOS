#!/usr/bin/env python3
"""
llm_proxy.py — AgentOS LLM 代理（宿主机运行）

功能：
  - 监控 outbox 目录的 LLM 请求
  - 调用 Moonshot API（Kimi）获取回复
  - 将响应写入 inbox 目录

用法：
  python3 llm_proxy.py --api-key <key> --model kimi-k2-0905-preview
  python3 llm_proxy.py --api-key-file ~/.config/agentos/api_key --model kimi-k2-0905-preview

环境变量：
  OPENAI_API_KEY - Moonshot API 密钥
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# 配置路径（可通过环境变量覆盖）
BRIDGE_DIR = Path(os.environ.get("AGENT_BRIDGE_DIR", "/mnt/agent_bridge"))
OUTBOX_DIR = BRIDGE_DIR / "outbox"
INBOX_DIR = BRIDGE_DIR / "inbox"
ERROR_DIR = BRIDGE_DIR / "error"

# 常量
POLL_INTERVAL = 2  # 秒
PROXY_LOG = Path(os.environ.get("LLM_PROXY_LOG", "/tmp/llm_proxy.log"))


class LLMProxy:
    """LLM 代理"""

    def __init__(self, api_key: str, model: str = "kimi-k2-0905-preview"):
        self.api_key = api_key
        self.default_model = model
        self._setup_logging()

    def _setup_logging(self) -> None:
        """配置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.StreamHandler(sys.stderr),
                logging.FileHandler(PROXY_LOG, encoding="utf-8")
            ]
        )
        self.logger = logging.getLogger("llm_proxy")

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        """原子写入 JSON 文件"""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        tmp.rename(path)

    def _call_openai_api(self, messages: list[dict[str, str]], model: str = "kimi-k2-0905-preview",
                         temperature: float = 0.2, max_tokens: int = 300) -> dict[str, Any]:
        """调用 Moonshot API（Kimi）"""
        import urllib.request
        import urllib.error

        # Moonshot API 端点
        url = "https://api.moonshot.cn/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                return {
                    "finish_reason": choice.get("finish_reason", "stop"),
                    "content": choice.get("message", {}).get("content", "")
                }
            else:
                return {"error": "Invalid API response", "raw": data}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self.logger.error(f"HTTP {e.code} error body: {error_body[:1000]}")
            return {"error": f"HTTP {e.code}: {e.reason}", "detail": error_body}
        except urllib.error.URLError as e:
            return {"error": f"URL error: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def _process_request(self, request_path: Path) -> None:
        """处理单个 LLM 请求"""
        try:
            request = json.loads(request_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            self.logger.error(f"Failed to read request {request_path}: {e}")
            return

        request_id = request.get("request_id", "unknown")
        self.logger.info(f"Processing request: {request_id}")

        # 提取参数
        messages = request.get("messages", [])
        model = request.get("model", self.default_model)
        temperature = request.get("temperature", 0.2)
        max_tokens = request.get("max_tokens", 300)

        # 调用 API
        start_time = time.time()
        api_result = self._call_openai_api(messages, model, temperature, max_tokens)
        elapsed = time.time() - start_time

        self.logger.info(f"API call completed in {elapsed:.2f}s")

        # 构建响应
        ts = datetime.now(timezone.utc).isoformat()

        if "error" in api_result:
            response = {
                "request_id": request_id,
                "ts": ts,
                "ok": False,
                "assistant_text": "",
                "raw_response": None,
                "error": api_result["error"]
            }
            self.logger.error(f"API error for {request_id}: {api_result['error']}")
        else:
            response = {
                "request_id": request_id,
                "ts": ts,
                "ok": True,
                "assistant_text": api_result.get("content", ""),
                "raw_response": {
                    "finish_reason": api_result.get("finish_reason", "stop")
                },
                "error": None
            }

        # 写入响应
        inbox_path = INBOX_DIR / f"{request_id}.json"
        try:
            self._atomic_write_json(inbox_path, response)
            self.logger.info(f"Response written: {inbox_path}")
        except OSError as e:
            self.logger.error(f"Failed to write response: {e}")
            error_path = ERROR_DIR / f"{request_id}.json"
            self._atomic_write_json(error_path, response)

        # 删除原始请求
        try:
            request_path.unlink()
        except OSError:
            pass

    def run(self) -> None:
        """运行代理主循环"""
        self.logger.info("LLM Proxy starting...")

        # 确保目录存在
        for d in [OUTBOX_DIR, INBOX_DIR, ERROR_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Watching: {OUTBOX_DIR}")

        processed = set()

        while True:
            try:
                # 扫描 outbox 中的请求
                for request_path in sorted(OUTBOX_DIR.glob("*.json")):
                    if request_path.name not in processed:
                        self._process_request(request_path)
                        processed.add(request_path.name)

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                self.logger.info("LLM Proxy stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(POLL_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS LLM Proxy")
    parser.add_argument("--api-key", help="OpenAI API Key")
    parser.add_argument("--api-key-file", help="File containing API Key")
    parser.add_argument("--model", default="kimi-k2-0905-preview", help="Default LLM model (default: kimi-k2-0905-preview)")
    parser.add_argument("--bridge-dir", default="/mnt/agent_bridge", help="Bridge directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # 获取 API Key
    api_key = args.api_key
    if not api_key and args.api_key_file:
        try:
            api_key = Path(args.api_key_file).read_text().strip()
        except OSError as e:
            print(f"Error reading API key file: {e}", file=sys.stderr)
            sys.exit(1)

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        print("Error: API key required (--api-key, --api-key-file, or OPENAI_API_KEY)", file=sys.stderr)
        sys.exit(1)

    # 配置路径
    if args.bridge_dir:
        os.environ["AGENT_BRIDGE_DIR"] = args.bridge_dir

    # 运行代理
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    proxy = LLMProxy(api_key, args.model)
    proxy.run()


if __name__ == "__main__":
    main()
