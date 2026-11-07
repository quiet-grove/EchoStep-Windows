"""应用配置：保存在 data/config.json，API Key 只留在本机。"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

DEFAULTS = {
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "thinking": False,
    "web_search": True,
    "search_count": 5,
    "tts_engine": "piper",
    "tts_voice": "en_US-amy-low",
    "speed": 1.0,
    "read_questions": True,
    "read_questions_zh": True,
    "read_options": False,
    "soundcheck": True,
    "repeat": 1,
}

MODELS = [
    {"id": "deepseek-flash", "label": "deepseek-flash", "hint": "快 · 日常出卷"},
    {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro", "hint": "强 · 复杂命题"},
]


class ConfigError(ValueError):
    pass


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def normalize_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return DEFAULTS["base_url"]
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("API 地址需要是 http(s):// 开头的完整地址")
    return value


class ConfigStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> dict:
        with self._lock:
            data = dict(DEFAULTS)
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        data.update({k: v for k, v in raw.items() if k in DEFAULTS})
                except (OSError, ValueError):
                    pass
            self._data = self._sanitize(data)
            return dict(self._data)

    def _sanitize(self, data: dict) -> dict:
        out = dict(DEFAULTS)
        out.update(data)
        out["api_key"] = str(out.get("api_key") or "").strip()
        try:
            out["base_url"] = normalize_base_url(str(out.get("base_url") or ""))
        except ConfigError:
            out["base_url"] = DEFAULTS["base_url"]
        out["model"] = str(out.get("model") or "deepseek-flash")
        if out["model"] not in {item["id"] for item in MODELS}:
            out["model"] = "deepseek-flash"
        out["thinking"] = _bool(out.get("thinking"))
        out["web_search"] = _bool(out.get("web_search"))
        out["read_questions"] = _bool(out.get("read_questions"))
        out["read_questions_zh"] = _bool(out.get("read_questions_zh"))
        out["read_options"] = _bool(out.get("read_options"))
        out["soundcheck"] = _bool(out.get("soundcheck", True))
        try:
            out["search_count"] = max(1, min(10, int(out.get("search_count", 5))))
        except (TypeError, ValueError):
            out["search_count"] = 5
        try:
            out["speed"] = max(0.5, min(1.5, float(out.get("speed", 1.0))))
        except (TypeError, ValueError):
            out["speed"] = 1.0
        try:
            out["repeat"] = max(1, min(3, int(out.get("repeat", 1))))
        except (TypeError, ValueError):
            out["repeat"] = 1
        if out["tts_engine"] not in {"piper", "edge", "sapi"}:
            out["tts_engine"] = "piper"
        out["tts_voice"] = str(out.get("tts_voice") or "").strip()
        return out

    def save(self, patch: dict, *, allow_empty_key: bool = False) -> dict:
        with self._lock:
            data = dict(self._data)
            for key, value in (patch or {}).items():
                if key not in DEFAULTS:
                    continue
                if key == "api_key":
                    value = str(value or "").strip()
                    if value == "" and not allow_empty_key:
                        # 空字符串表示“不修改已保存的密钥”，删除密钥请用 clear_key。
                        continue
                data[key] = value
            self._data = self._sanitize(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self.path)
            return dict(self._data)

    def clear_key(self) -> dict:
        with self._lock:
            return self.save({"api_key": ""}, allow_empty_key=True)

    def effective_key(self) -> str:
        # 环境变量优先，方便不想把密钥写进文件的用户。
        return (os.environ.get("DEEPSEEK_API_KEY") or "").strip() or self._data["api_key"]

    def data(self) -> dict:
        return dict(self._data)

    def public(self) -> dict:
        data = dict(self._data)
        key = self.effective_key()
        data.pop("api_key", None)
        data["has_key"] = bool(key)
        data["key_from_env"] = bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip())
        data["key_masked"] = mask_key(key) if key else ""
        data["models"] = MODELS
        return data


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "•" * max(2, len(key) - 4) + key[-2:]
    return f"{key[:5]}••••••{key[-4:]}"
