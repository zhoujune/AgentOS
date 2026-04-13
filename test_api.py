#!/usr/bin/env python3
"""
test_api.py — 测试 SiliconFlow API 连接
"""

import json
import urllib.request
import urllib.error
import sys

API_KEY = "sk-fwdhonbyuwsztqdeltjexvpggdqcaqpxmqjvhtmrfvlbticp"
URL = "https://api.siliconflow.cn/v1/chat/completions"

# 测试不同模型名
models_to_test = [
    "Qwen/Qwen3.5-27B",
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-R1",
]

messages = [
    {"role": "system", "content": "你是一个有用的助手"},
    {"role": "user", "content": "你好，请简单介绍一下自己，用一句话回答"}
]

def test_model(model: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 100
    }
    
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "data": data}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        try:
            error_json = json.loads(error_body)
            return {"ok": False, "error": f"HTTP {e.code}: {error_json}"}
        except:
            return {"ok": False, "error": f"HTTP {e.code}: {error_body[:500]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main():
    print("=" * 60)
    print("SiliconFlow API 测试")
    print("=" * 60)
    
    for model in models_to_test:
        print(f"\n测试模型: {model}")
        print("-" * 40)
        result = test_model(model)
        
        if result["ok"]:
            data = result["data"]
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content", "")
                print(f"✓ 成功! 响应: {content[:100]}...")
            else:
                print(f"✓ 成功! 响应: {json.dumps(data, ensure_ascii=False)[:200]}")
        else:
            print(f"✗ 失败: {result['error']}")
    
    print("\n" + "=" * 60)
    
    # 详细测试第一个可用的模型
    print("\n详细测试 Qwen/Qwen3.5-27B:")
    print("-" * 40)
    
    # 先发送一个请求看看详细错误
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    payload = {
        "model": "Qwen/Qwen3.5-27B",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 100
    }
    
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("完整响应:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        print(f"HTTP {e.code} 错误:")
        print(f"Headers: {dict(e.headers)}")
        print(f"Body: {error_body[:1000]}")
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    main()
