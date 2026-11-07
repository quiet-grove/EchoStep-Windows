"""DeepSeek 官方 API 客户端：Chat Completions + 官方 Search API。

只依赖标准库，避免要求用户额外安装 openai/requests。
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 180


class DeepSeekError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


def _endpoints(base_url: str) -> tuple[str, str, str]:
    root = (base_url or "https://api.deepseek.com").rstrip("/")
    if root.endswith("/v1"):
        return root + "/chat/completions", root + "/tools/search", root + "/models"
    return root + "/chat/completions", root + "/v1/tools/search", root + "/models"


def _friendly_http_error(status: int, body: str) -> str:
    message = ""
    try:
        obj = json.loads(body)
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict):
                message = str(err.get("message") or "")
            elif isinstance(err, str):
                message = err
            message = message or str(obj.get("message") or "")
    except ValueError:
        message = body[:300].strip()
    mapping = {
        400: "请求参数有误",
        401: "API Key 无效或已过期，请在设置里检查",
        402: "账户余额不足，请先充值",
        403: "请求被拒绝（可能是内容安全策略或权限不足）",
        404: "接口地址不存在，请检查 API 地址",
        408: "请求超时，请稍后重试",
        413: "请求内容过大",
        429: "请求太频繁或额度受限，请稍后重试",
        500: "DeepSeek 服务内部错误，请稍后重试",
        502: "DeepSeek 网关错误，请稍后重试",
        503: "DeepSeek 服务繁忙，请稍后重试",
        504: "DeepSeek 服务超时，请稍后重试",
    }
    base = mapping.get(status, f"请求失败（HTTP {status}）")
    if message and message not in base:
        return f"{base}：{message[:300]}"
    return base


def _post_json(
    url: str,
    payload: dict,
    api_key: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 1,
) -> dict:
    if not api_key:
        raise DeepSeekError("还没有填写 DeepSeek API Key", 401, "missing_api_key")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "EchoStep-English-Listening/1.0",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except ValueError as exc:
                raise DeepSeekError("DeepSeek 返回了无法解析的内容", 502, "bad_json") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            message = _friendly_http_error(exc.code, body)
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < retries:
                last_error = DeepSeekError(message, exc.code, "retryable")
                time.sleep(1.6 * (attempt + 1))
                continue
            raise DeepSeekError(message, exc.code, "http_error") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            message = f"无法连接 DeepSeek：{reason}"
            if attempt < retries:
                last_error = DeepSeekError(message, None, "network")
                time.sleep(1.2)
                continue
            raise DeepSeekError(message, None, "network") from exc
    raise DeepSeekError(str(last_error or "请求失败"), None, "unknown")


def extract_json(text: str) -> dict:
    """从模型输出里稳妥地取出第一个 JSON 对象。"""
    if not text or not text.strip():
        raise DeepSeekError("模型返回了空内容，请重新生成", 502, "empty_content")
    cleaned = text.strip().lstrip("\ufeff")
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    if start < 0:
        raise DeepSeekError("模型没有返回 JSON，请重新生成", 502, "no_json")
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except ValueError:
        # 常见的小毛病：末尾多了逗号。尽量不擅自改内容，只做一次温和尝试。
        fixed = cleaned[start:]
        fixed = fixed.replace(",\n}", "\n}").replace(",}", "}")
        try:
            obj, _ = json.JSONDecoder().raw_decode(fixed)
        except ValueError as exc:
            raise DeepSeekError("模型返回的 JSON 格式不完整，请重新生成", 502, "bad_json") from exc
    if not isinstance(obj, dict):
        raise DeepSeekError("模型返回的 JSON 不是对象", 502, "bad_json")
    return obj


class DeepSeekClient:
    def __init__(self, base_url: str, api_key: str, model: str = "deepseek-flash"):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.chat_url, self.search_url, self.models_url = _endpoints(base_url)

    # ------------------------------------------------------------------ chat
    def chat_json(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        thinking: bool = False,
        temperature: float = 0.85,
        max_tokens: int = 16000,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> tuple[dict, dict]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
        raw = _post_json(self.chat_url, payload, self.api_key, timeout=timeout)
        choices = raw.get("choices") or []
        if not choices:
            raise DeepSeekError("DeepSeek 没有返回候选结果", 502, "no_choices")
        choice = choices[0] or {}
        finish = choice.get("finish_reason")
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if finish == "length":
            raise DeepSeekError("生成内容被截断（模板较长），请重试一次", 502, "length")
        if finish == "content_filter":
            raise DeepSeekError("内容触发了安全过滤，请调整主题后重试", 502, "content_filter")
        obj = extract_json(content)
        usage = raw.get("usage") or {}
        meta = {
            "model": raw.get("model") or payload["model"],
            "finish_reason": finish,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            "raw_content": content,
        }
        return obj, meta

    # ---------------------------------------------------------------- search
    def search(
        self,
        query: str,
        *,
        count: int = 5,
        ori_question: str | None = None,
        need_content: bool = False,
        timeout: int = 45,
    ) -> list[dict]:
        query = " ".join((query or "").split())
        if not query:
            return []
        query = query[:128]
        payload: dict[str, Any] = {
            "query": query,
            "count": max(1, min(50, int(count or 5))),
            "need_content": bool(need_content),
        }
        if ori_question:
            payload["ori_question"] = " ".join(ori_question.split())[:128]
        raw = _post_json(self.search_url, payload, self.api_key, timeout=timeout, retries=1)
        results = raw.get("results") or []
        cleaned: list[dict] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            cleaned.append(
                {
                    "title": str(item.get("title") or "未命名网页")[:200],
                    "url": url,
                    "snippet": str(item.get("snippet") or "")[:500],
                    "summary": str(item.get("summary") or "")[:1200],
                    "site_name": item.get("site_name"),
                    "date": item.get("date"),
                    "authority": item.get("authority"),
                    "rerank_score": item.get("rerank_score"),
                }
            )
        return cleaned

    # ------------------------------------------------------------- connection
    def test_connection(self) -> dict:
        if not self.api_key:
            raise DeepSeekError("还没有填写 DeepSeek API Key", 401, "missing_api_key")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "EchoStep-English-Listening/1.0",
        }
        request = urllib.request.Request(self.models_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read().decode("utf-8", "replace")
            data = json.loads(raw or "{}")
            models = [
                item.get("id")
                for item in (data.get("data") or [])
                if isinstance(item, dict) and item.get("id")
            ]
            return {"ok": True, "models": models}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise DeepSeekError(_friendly_http_error(exc.code, body), exc.code, "http_error") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise DeepSeekError(f"无法连接 DeepSeek：{getattr(exc, 'reason', exc)}", None, "network") from exc


def format_search_context(results: list[dict], max_chars: int = 3600) -> str:
    if not results:
        return ""
    blocks: list[str] = []
    used = 0
    for index, item in enumerate(results, 1):
        summary = item.get("summary") or item.get("snippet") or ""
        date = item.get("date") or ""
        block = (
            f"[{index}] {item.get('title', '')}\n"
            f"来源：{item.get('site_name') or item.get('url', '')} {date}\n"
            f"摘要：{summary}\n"
        )
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks).strip()


def build_search_query(grade: str, book: str, unit_title: str, topic: str = "") -> str:
    topic = " ".join((topic or "").split())
    base = f"{grade}{book} {unit_title} 初中英语听力 单元话题"
    if topic:
        base = f"{base} {topic}"
    return base[:128]
