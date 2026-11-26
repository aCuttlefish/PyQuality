import json
import re
import time

import requests

from backend.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT, get_api_key
from backend.logger import get_logger

logger = get_logger("deepseek")


class DeepSeekError(Exception):
    pass


def is_available() -> bool:
    return bool(get_api_key())


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 4096,
         json_mode: bool = False, retries: int = 1) -> str:
    api_key = get_api_key()
    if not api_key:
        raise DeepSeekError("未配置 DEEPSEEK_API_KEY，请在环境变量或 .env 文件中设置")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    last_err = None
    for attempt in range(retries + 1):
        try:
            t0 = time.time()
            resp = requests.post(url, headers=headers, json=body, timeout=DEEPSEEK_TIMEOUT)
            elapsed = time.time() - t0
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                logger.info("DeepSeek OK %.1fs tokens=%s", elapsed, usage.get("total_tokens", "?"))
                if content:
                    return content
                last_err = DeepSeekError("DeepSeek 返回空内容")
            elif resp.status_code in (429, 500, 502, 503):
                logger.warning("DeepSeek HTTP %d %.1fs", resp.status_code, elapsed)
                last_err = DeepSeekError(f"DeepSeek 服务暂时不可用 (HTTP {resp.status_code})")
            else:
                detail = resp.text[:300]
                logger.warning("DeepSeek HTTP %d %.1fs: %s", resp.status_code, elapsed, detail)
                raise DeepSeekError(f"DeepSeek API 错误 (HTTP {resp.status_code}): {detail}")
        except requests.exceptions.Timeout:
            raise DeepSeekError(f"DeepSeek 请求超时（{DEEPSEEK_TIMEOUT} 秒），请检查网络连接")
        except requests.exceptions.ConnectionError:
            raise DeepSeekError("无法连接到 DeepSeek API，请检查网络")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last_err or DeepSeekError("DeepSeek 请求失败")


def chat_json(messages: list[dict], temperature: float = 0.3) -> dict:
    content = chat(messages, temperature=temperature, json_mode=True)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return _extract_json(content)


def _extract_json(content: str) -> dict:
    candidates = []
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1))
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        candidates.append(content[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise DeepSeekError(f"DeepSeek 返回的不是有效 JSON: {content[:200]}")