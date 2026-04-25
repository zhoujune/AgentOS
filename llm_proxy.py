#!/usr/bin/env python3
"""
Host-side LLM proxy for AgentOS.

Supports:
- OpenAI-compatible chat completion endpoints
- Anthropic messages API
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_BRIDGE_DIR = str(REPO_ROOT / "runtime" / "agent_bridge")
DEFAULT_OPENAI_ENDPOINT = "https://api.moonshot.cn/v1/chat/completions"
DEFAULT_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

POLL_INTERVAL = 2
PROXY_LOG = Path(os.environ.get("LLM_PROXY_LOG", "/tmp/llm_proxy.log"))


class LLMProxy:
    def __init__(
        self,
        api_key: str,
        model: str = "kimi-k2-0905-preview",
        bridge_dir: str | Path | None = None,
        api_endpoint: str | None = None,
        api_style: str = "openai",
        anthropic_version: str = DEFAULT_ANTHROPIC_VERSION,
        temperature_override: float | None = None,
    ):
        self.api_key = api_key
        self.default_model = model
        self.api_style = api_style
        self.api_endpoint = api_endpoint or self._default_endpoint(api_style)
        self.anthropic_version = anthropic_version
        self.temperature_override = temperature_override
        self.bridge_dir = Path(bridge_dir or os.environ.get("AGENT_BRIDGE_DIR", DEFAULT_BRIDGE_DIR))
        self.outbox_dir = self.bridge_dir / "outbox"
        self.inbox_dir = self.bridge_dir / "inbox"
        self.error_dir = self.bridge_dir / "error"
        self._setup_logging()

    @staticmethod
    def _default_endpoint(api_style: str) -> str:
        if api_style == "anthropic":
            return DEFAULT_ANTHROPIC_ENDPOINT
        return DEFAULT_OPENAI_ENDPOINT

    def _setup_logging(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.StreamHandler(sys.stderr),
                logging.FileHandler(PROXY_LOG, encoding="utf-8"),
            ],
        )
        self.logger = logging.getLogger("llm_proxy")

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(path)

    def _call_openai_api(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            self.api_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                return {
                    "finish_reason": choice.get("finish_reason", "stop"),
                    "content": choice.get("message", {}).get("content", ""),
                }
            return {"error": "Invalid API response", "raw": data}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self.logger.error("HTTP %s error body: %s", e.code, error_body[:1000])
            return {"error": f"HTTP {e.code}: {e.reason}", "detail": error_body}
        except urllib.error.URLError as e:
            return {"error": f"URL error: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def _normalize_anthropic_messages(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = str(message.get("content", ""))
            if role == "system":
                system_parts.append(content)
                continue
            mapped_role = "assistant" if role == "assistant" else "user"
            anthropic_messages.append(
                {
                    "role": mapped_role,
                    "content": [{"type": "text", "text": content}],
                }
            )
        system = "\n\n".join(part for part in system_parts if part.strip()) or None
        return system, anthropic_messages

    def _call_anthropic_api(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        system, anthropic_messages = self._normalize_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
        }
        req = urllib.request.Request(
            self.api_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            parts = data.get("content", [])
            content = "".join(str(part.get("text", "")) for part in parts if part.get("type") == "text")
            return {
                "finish_reason": data.get("stop_reason", "end_turn"),
                "content": content,
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self.logger.error("HTTP %s error body: %s", e.code, error_body[:1000])
            return {"error": f"HTTP {e.code}: {e.reason}", "detail": error_body}
        except urllib.error.URLError as e:
            return {"error": f"URL error: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def _call_llm_api(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if self.api_style == "anthropic":
            return self._call_anthropic_api(messages, model, temperature, max_tokens)
        return self._call_openai_api(messages, model, temperature, max_tokens)

    def _process_request(self, request_path: Path) -> None:
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self.logger.error("Failed to read request %s: %s", request_path, e)
            return

        request_id = request.get("request_id", "unknown")
        self.logger.info("Processing request: %s", request_id)

        messages = request.get("messages", [])
        model = request.get("model", self.default_model)
        temperature = self.temperature_override
        if temperature is None:
            temperature = request.get("temperature", 1.0)
        max_tokens = request.get("max_tokens", 300)

        start_time = time.time()
        api_result = self._call_llm_api(messages, model, temperature, max_tokens)
        elapsed = time.time() - start_time
        self.logger.info("API call completed in %.2fs", elapsed)

        ts = datetime.now(timezone.utc).isoformat()
        if "error" in api_result:
            response = {
                "request_id": request_id,
                "ts": ts,
                "ok": False,
                "assistant_text": "",
                "raw_response": None,
                "error": api_result["error"],
            }
            self.logger.error("API error for %s: %s", request_id, api_result["error"])
        else:
            response = {
                "request_id": request_id,
                "ts": ts,
                "ok": True,
                "assistant_text": api_result.get("content", ""),
                "raw_response": {
                    "finish_reason": api_result.get("finish_reason", "stop"),
                },
                "error": None,
            }

        inbox_path = self.inbox_dir / f"{request_id}.json"
        try:
            self._atomic_write_json(inbox_path, response)
            self.logger.info("Response written: %s", inbox_path)
        except OSError as e:
            self.logger.error("Failed to write response: %s", e)
            error_path = self.error_dir / f"{request_id}.json"
            self._atomic_write_json(error_path, response)

        try:
            request_path.unlink()
        except OSError:
            pass

    def run(self) -> None:
        self.logger.info("LLM Proxy starting...")
        self.logger.info("API style: %s", self.api_style)
        self.logger.info("API endpoint: %s", self.api_endpoint)

        for d in [self.outbox_dir, self.inbox_dir, self.error_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.logger.info("Watching: %s", self.outbox_dir)
        processed = set()

        while True:
            try:
                for request_path in sorted(self.outbox_dir.glob("*.json")):
                    if request_path.name not in processed:
                        self._process_request(request_path)
                        processed.add(request_path.name)
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                self.logger.info("LLM Proxy stopped by user")
                break
            except Exception as e:
                self.logger.error("Error in main loop: %s", e)
                time.sleep(POLL_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS LLM Proxy")
    parser.add_argument("--api-key", help="LLM API key")
    parser.add_argument("--api-key-file", help="File containing API key")
    parser.add_argument("--model", default="kimi-k2-0905-preview", help="Default LLM model")
    parser.add_argument("--api-style", choices=["openai", "anthropic"], default=os.environ.get("LLM_API_STYLE", "openai"))
    parser.add_argument("--api-endpoint", default=os.environ.get("LLM_API_ENDPOINT"), help="Custom LLM API endpoint")
    parser.add_argument("--anthropic-version", default=os.environ.get("ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION))
    parser.add_argument("--temperature", type=float, default=None, help="Override request temperature")
    parser.add_argument("--bridge-dir", default=DEFAULT_BRIDGE_DIR, help="Bridge directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key and args.api_key_file:
        try:
            api_key = Path(args.api_key_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"Error reading API key file: {e}", file=sys.stderr)
            sys.exit(1)

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: API key required (--api-key, --api-key-file, OPENAI_API_KEY, or ANTHROPIC_API_KEY)", file=sys.stderr)
        sys.exit(1)

    if args.bridge_dir:
        os.environ["AGENT_BRIDGE_DIR"] = args.bridge_dir

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    proxy = LLMProxy(
        api_key=api_key,
        model=args.model,
        bridge_dir=args.bridge_dir,
        api_endpoint=args.api_endpoint,
        api_style=args.api_style,
        anthropic_version=args.anthropic_version,
        temperature_override=args.temperature,
    )
    proxy.run()


if __name__ == "__main__":
    main()
