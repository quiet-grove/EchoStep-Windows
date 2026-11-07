"""EchoStep 本地服务器：标准库 HTTP + DeepSeek + 本地 TTS。

启动：
    python app.py
默认打开 http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from listening_app import __version__
from listening_app.config import ConfigError, ConfigStore, normalize_base_url
from listening_app.deepseek import (
    DeepSeekClient,
    DeepSeekError,
    build_search_query,
    format_search_context,
)
from listening_app.prompts import build_generation_messages, build_repair_message
from listening_app.schema import (
    ValidationError,
    normalize_test,
    public_test,
    result_payload,
)
from listening_app.storage import TestStore
from listening_app.tts import TTSError, TTSService
from listening_app.units import get_unit, public_catalog

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
MIME_OVERRIDES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".json": "application/json; charset=utf-8",
}


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, details: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


class Application:
    def __init__(self, root: Path = ROOT, data_dir: Path | None = None, debug: bool = False,
                 cache_dir: Path | None = None):
        self.root = Path(root)
        self.data_dir = Path(data_dir) if data_dir else self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = ConfigStore(self.data_dir / "config.json")
        self.store = TestStore(self.data_dir / "tests")
        self.tts = TTSService(self.root, cache_dir=cache_dir)
        self.debug = bool(debug)
        self.started_at = time.time()

    # --------------------------------------------------------------- helpers
    def resolved_tts(self) -> dict:
        cfg = self.config.data()
        engine, _ = self.tts.resolve_engine(cfg["tts_engine"])
        voice = cfg.get("tts_voice") or self.tts.default_voice(engine)
        try:
            voice = self.tts.validate_voice(engine, voice)
        except TTSError:
            voice = self.tts.default_voice(engine)
        return {"engine": engine, "voice": voice}

    def state(self) -> dict:
        resolved = self.resolved_tts()
        count, size = self.tts.cache_size()
        return {
            "version": __version__,
            "config": self.config.public(),
            "tts_resolved": resolved,
            "catalog": public_catalog(),
            "engines": self.tts.engines(),
            "cache": {"files": count, "bytes": size},
            "debug": self.debug,
            "server": {
                "uptime": int(time.time() - self.started_at),
                "data_dir": str(self.data_dir),
                "root": str(self.root),
            },
        }

    def save_config(self, payload: dict) -> dict:
        if payload.get("clear_key"):
            self.config.clear_key()
        patch = {
            key: payload[key]
            for key in (
                "api_key",
                "base_url",
                "model",
                "thinking",
                "web_search",
                "search_count",
                "tts_engine",
                "tts_voice",
                "speed",
                "read_questions",
                "read_questions_zh",
                "read_options",
                "soundcheck",
                "repeat",
            )
            if key in payload
        }
        if "base_url" in patch:
            try:
                patch["base_url"] = normalize_base_url(str(patch["base_url"]))
            except ConfigError as exc:
                raise ApiError(400, str(exc)) from exc
        if "model" in patch and patch["model"] not in {"deepseek-flash", "deepseek-v4-pro"}:
            raise ApiError(400, "不支持的模型")
        try:
            self.config.save(patch)
        except ConfigError as exc:
            raise ApiError(400, str(exc)) from exc
        return self.state()

    def test_connection(self, payload: dict) -> dict:
        cfg = self.config.data()
        key = str(payload.get("api_key") or "").strip() or self.config.effective_key()
        if not key:
            raise ApiError(400, "请先填写 DeepSeek API Key")
        try:
            base = normalize_base_url(str(payload.get("base_url") or cfg["base_url"]))
        except ConfigError as exc:
            raise ApiError(400, str(exc)) from exc
        model = str(payload.get("model") or cfg["model"])
        started = time.time()
        client = DeepSeekClient(base, key, model)
        result = client.test_connection()
        result["latency_ms"] = int((time.time() - started) * 1000)
        result["model"] = model
        return result

    def _client(self, model: str | None = None) -> DeepSeekClient:
        cfg = self.config.data()
        key = self.config.effective_key()
        if not key:
            raise ApiError(400, "还没有填写 DeepSeek API Key，请点击右上角「设置」填写")
        return DeepSeekClient(cfg["base_url"], key, model or cfg["model"])

    # -------------------------------------------------------------- generate
    def generate(self, payload: dict) -> dict:
        started = time.time()
        grade = str(payload.get("grade") or "").strip()
        book = str(payload.get("book") or "").strip()
        unit_id = str(payload.get("unit_id") or "").strip()
        unit = get_unit(grade, book, unit_id)
        if not unit:
            raise ApiError(400, "请选择有效的年级、册和单元")
        count = 30
        topic = str(payload.get("topic") or "").strip()[:300]
        cfg = self.config.data()
        client = self._client()
        web_search = _as_bool(payload.get("web_search"), cfg["web_search"])

        search_sources: list[dict] = []
        search_warning = ""
        search_context = ""
        if web_search:
            query = build_search_query(grade, book, unit["title"], topic)
            try:
                results = client.search(
                    query,
                    count=cfg.get("search_count", 5),
                    ori_question=f"{grade}{book} {unit['title']} 初中英语听力练习",
                )
                search_sources = [
                    {
                        "title": item["title"],
                        "url": item["url"],
                        "site_name": item.get("site_name"),
                        "date": item.get("date"),
                    }
                    for item in results[:8]
                ]
                search_context = format_search_context(results, max_chars=3600)
                if not results:
                    search_warning = "联网搜索没有返回结果，已根据教材单元直接出卷。"
            except DeepSeekError as exc:
                search_warning = f"联网搜索失败：{exc}（已继续离线出卷）"

        messages = build_generation_messages(
            grade=grade,
            book=book,
            unit_id=unit_id,
            count=count,
            topic=topic,
            search_context=search_context,
            search_sources=search_sources,
        )
        request = {
            "grade": grade,
            "book": book,
            "unit_id": unit_id,
            "unit_title": unit["title"],
            "topic": topic,
        }
        last_error: Exception | None = None
        test: dict | None = None
        meta: dict = {}
        for attempt in range(3):
            try:
                obj, meta = client.chat_json(
                    messages,
                    thinking=bool(cfg.get("thinking")),
                    temperature=[0.9, 0.7, 0.55][attempt],
                    timeout=200,
                )
                test = normalize_test(obj, count=count, request=request)
                break
            except (ValidationError, DeepSeekError) as exc:
                last_error = exc
                if isinstance(exc, DeepSeekError) and exc.code not in {
                    "bad_json",
                    "empty_content",
                    "no_json",
                }:
                    raise
                if attempt < 2:
                    repair = build_repair_message(str(exc), count)
                    if meta.get("raw_content"):
                        messages = messages + [
                            {"role": "assistant", "content": meta["raw_content"][:12000]},
                            {"role": "user", "content": repair},
                        ]
                    else:
                        messages = messages + [{"role": "user", "content": repair}]
                    continue
                break
        if test is None:
            if isinstance(last_error, DeepSeekError):
                raise last_error
            raise ApiError(502, f"AI 生成的内容未通过校验：{last_error}。请重新生成。")

        test["model"] = meta.get("model", cfg["model"])
        test["search_sources"] = search_sources
        test["search_warning"] = search_warning
        test["thinking"] = bool(cfg.get("thinking"))
        test["usage"] = meta.get("usage", {})
        test = self.store.save(test)
        elapsed = round(time.time() - started, 1)
        return {
            "test": public_test(test),
            "meta": {
                "elapsed": elapsed,
                "model": test.get("model"),
                "usage": test.get("usage", {}),
                "search_count": len(search_sources),
                "search_warning": search_warning,
                "search_sources": search_sources,
            },
        }

    # ---------------------------------------------------------------- grade
    def grade(self, payload: dict) -> dict:
        test_id = str(payload.get("test_id") or "")
        test = self.store.get(test_id)
        if not test:
            raise ApiError(404, "找不到这套试卷，请重新生成")
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            answers = {}
        result = result_payload(test, answers)
        result["test_id"] = test_id
        result["title"] = test.get("title", "")
        return result

    # ---------------------------------------------------------------- audio
    def section_audio(self, test_id: str, section_id: str, query: dict) -> Path:
        test = self.store.get(test_id)
        if not test:
            raise ApiError(404, "找不到这套试卷")
        section = next(
            (item for item in test.get("sections", []) if item.get("id") == section_id), None
        )
        if not section:
            raise ApiError(404, "找不到这段音频")
        cfg = self.config.data()
        engine = str(query.get("engine") or cfg["tts_engine"])
        voice = str(query.get("voice") or cfg["tts_voice"])
        try:
            speed = float(query.get("speed", cfg["speed"]))
        except (TypeError, ValueError):
            speed = cfg["speed"]
        try:
            repeat = int(query.get("repeat", cfg["repeat"]))
        except (TypeError, ValueError):
            repeat = cfg["repeat"]
        read_questions = _as_bool(query.get("read_questions"), cfg["read_questions"])
        read_questions_zh = _as_bool(
            query.get("read_questions_zh"), cfg.get("read_questions_zh", True)
        )
        read_options = _as_bool(query.get("read_options"), cfg.get("read_options", False))
        try:
            return self.tts.synthesize_section(
                section,
                engine=engine,
                voice=voice,
                speed=speed,
                repeat=repeat,
                read_questions=read_questions,
                read_questions_zh=read_questions_zh,
                read_options=read_options,
            )
        except TTSError as exc:
            raise ApiError(502, str(exc)) from exc

    def exam_audio(self, test_id: str, query: dict) -> Path:
        test = self.store.get(test_id)
        if not test:
            raise ApiError(404, "找不到这套试卷")
        cfg = self.config.data()
        engine = str(query.get("engine") or cfg["tts_engine"])
        voice = str(query.get("voice") or cfg["tts_voice"])
        try:
            speed = float(query.get("speed", cfg["speed"]))
        except (TypeError, ValueError):
            speed = cfg["speed"]
        try:
            repeat = int(query.get("repeat", cfg["repeat"]))
        except (TypeError, ValueError):
            repeat = cfg["repeat"]
        read_questions = _as_bool(query.get("read_questions"), cfg["read_questions"])
        read_questions_zh = _as_bool(
            query.get("read_questions_zh"), cfg.get("read_questions_zh", True)
        )
        read_options = _as_bool(query.get("read_options"), cfg.get("read_options", False))
        soundcheck = _as_bool(query.get("soundcheck"), cfg.get("soundcheck", True))
        try:
            return self.tts.synthesize_exam(
                test,
                engine=engine,
                voice=voice,
                speed=speed,
                repeat=repeat,
                read_questions=read_questions,
                read_questions_zh=read_questions_zh,
                soundcheck=soundcheck,
                read_options=read_options,
            )
        except TTSError as exc:
            raise ApiError(502, str(exc)) from exc

    def preview_audio(self, query: dict) -> Path:
        cfg = self.config.data()
        engine = str(query.get("engine") or cfg["tts_engine"])
        voice = str(query.get("voice") or cfg["tts_voice"])
        try:
            speed = float(query.get("speed", cfg["speed"]))
        except (TypeError, ValueError):
            speed = cfg["speed"]
        try:
            return self.tts.preview(engine=engine, voice=voice, speed=speed)
        except TTSError as exc:
            raise ApiError(502, str(exc)) from exc


class Handler(BaseHTTPRequestHandler):
    application: Application
    protocol_version = "HTTP/1.1"
    server_version = "EchoStep/1.0"

    # ------------------------------------------------------------- responses
    def _common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'",
        )

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def send_error_json(self, status: int, message: str, details: str = "") -> None:
        payload = {"error": {"message": message, "status": status}}
        if details:
            payload["error"]["details"] = details
        self.send_json(status, payload)

    def send_file(
        self, path: Path, *, cache: str = "no-cache", content_type: str | None = None
    ) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            self.send_error_json(404, "文件不存在")
            return
        ctype = content_type or MIME_OVERRIDES.get(path.suffix.lower())
        if not ctype:
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        etag = f'"{int(path.stat().st_mtime)}-{size}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self._common_headers()
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.end_headers()
            return
        start = 0
        end = size - 1
        partial = False
        range_header = self.headers.get("Range", "")
        if range_header.startswith("bytes="):
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                first, second = match.groups()
                if first:
                    start = int(first)
                    end = int(second) if second else size - 1
                elif second:
                    length = int(second)
                    start = max(0, size - length)
                    end = size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self._common_headers()
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                partial = True
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self._common_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache)
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", self.date_time_string(path.stat().st_mtime))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as file:
                file.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = file.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ------------------------------------------------------------------ body
    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 2_000_000:
            raise ApiError(413, "请求内容过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ApiError(400, "请求 JSON 格式不正确") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "请求内容需要是 JSON 对象")
        return data

    def _handle_exception(self, exc: Exception) -> None:
        if isinstance(exc, ApiError):
            self.send_error_json(exc.status, exc.message, exc.details)
            return
        if isinstance(exc, DeepSeekError):
            status = exc.status if exc.status and 400 <= exc.status < 600 else 502
            self.send_error_json(status, str(exc))
            return
        if isinstance(exc, TTSError):
            self.send_error_json(502, str(exc))
            return
        traceback.print_exc()
        self.send_error_json(500, "服务器内部错误，请查看启动窗口的日志")

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = {
            key: values[-1]
            for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()
        }
        try:
            if path == "/api/health":
                self.send_json(200, {"ok": True, "version": __version__})
                return
            if path == "/api/state":
                self.send_json(200, self.application.state())
                return
            if path == "/api/history":
                self.send_json(200, {"items": self.application.store.list(40)})
                return
            if path.startswith("/api/test/"):
                test_id = path[len("/api/test/") :]
                test = self.application.store.public(test_id)
                if not test:
                    raise ApiError(404, "找不到这套试卷")
                self.send_json(200, {"test": test})
                return
            if path.startswith("/api/exam-audio/"):
                test_id = path[len("/api/exam-audio/") :]
                file_path = self.application.exam_audio(test_id, query)
                self.send_file(file_path, cache="public, max-age=31536000, immutable")
                return
            if path.startswith("/api/audio/"):
                rest = path[len("/api/audio/") :]
                parts = rest.split("/")
                if len(parts) != 2:
                    raise ApiError(400, "音频地址不正确")
                file_path = self.application.section_audio(parts[0], parts[1], query)
                self.send_file(file_path, cache="public, max-age=31536000, immutable")
                return
            if path == "/api/tts/preview":
                file_path = self.application.preview_audio(query)
                self.send_file(file_path, cache="no-store")
                return
            self.serve_static(path)
        except Exception as exc:  # noqa: BLE001
            self._handle_exception(exc)

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            payload = self.read_json()
            if path == "/api/generate":
                self.send_json(200, self.application.generate(payload))
                return
            if path == "/api/grade":
                self.send_json(200, self.application.grade(payload))
                return
            if path == "/api/config":
                self.send_json(200, {"state": self.application.save_config(payload)})
                return
            if path == "/api/test-connection":
                self.send_json(200, self.application.test_connection(payload))
                return
            if path == "/api/cache/clear":
                removed = self.application.tts.clear_cache()
                self.send_json(200, {"removed": removed, "cache": self.application.state()["cache"]})
                return
            raise ApiError(404, "接口不存在")
        except Exception as exc:  # noqa: BLE001
            self._handle_exception(exc)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    # --------------------------------------------------------------- static
    def serve_static(self, path: str) -> None:
        mapping = {
            "/": "index.html",
            "/index.html": "index.html",
            "/app.js": "app.js",
            "/styles.css": "styles.css",
            "/favicon.svg": "favicon.svg",
        }
        name = mapping.get(path)
        if not name:
            raise ApiError(404, "页面不存在")
        file_path = (WEB_DIR / name).resolve()
        if not str(file_path).startswith(str(WEB_DIR.resolve())):
            raise ApiError(403, "拒绝访问")
        if not file_path.exists():
            raise ApiError(404, "页面文件缺失")
        cache = "no-cache" if name in {"index.html", "app.js", "styles.css"} else "public, max-age=86400"
        self.send_file(file_path, cache=cache)

    def log_message(self, fmt: str, *args: Any) -> None:
        # 只记录 API，静态资源不刷屏。
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        exc_type = sys.exc_info()[0]
        if exc_type and issubclass(exc_type, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    root: Path = ROOT,
    data_dir: Path | None = None,
    debug: bool = False,
    cache_dir: Path | None = None,
) -> tuple[ThreadingHTTPServer, Application]:
    app = Application(root=root, data_dir=data_dir, debug=debug, cache_dir=cache_dir)

    class AppHandler(Handler):
        application = app

    server = AppServer((host, port), AppHandler)
    return server, app


def _pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"端口 {preferred}-{preferred + 19} 都被占用了，请用 --port 换一个")


def main() -> None:
    parser = argparse.ArgumentParser(description="EchoStep 初中英语听力练习")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--debug", action="store_true", help="允许回放和拖动听力音频")
    args = parser.parse_args()
    port = _pick_port(args.host, args.port) if args.port else 0
    server, app = create_server(args.host, port, data_dir=args.data_dir, debug=args.debug)
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}"
    resolved = app.resolved_tts()
    engines = {item["id"]: item for item in app.tts.engines()}
    engine = engines.get(resolved["engine"], {})
    print("=" * 58)
    print("  EchoStep · 初中英语听力练习")
    print(f"  打开：{url}")
    print(f"  语音：{engine.get('name', resolved['engine'])} / {resolved['voice']}")
    print(f"  数据：{app.data_dir}")
    print(f"  模式：{'DEBUG（可回放/拖动）' if app.debug else '考试模式（听力不可回放）'}")
    print("  按 Ctrl+C 停止")
    print("=" * 58)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止……")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
