"""EchoStep Windows desktop shell.

Runs the existing local HTTP server inside a native window (WebView2 via
pywebview). The browser is no longer opened by default; it can be opened from
the in-app "浏览器打开" button or with ``--browser``.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from app import ROOT, _pick_port, create_server

try:
    import webview
    from webview.menu import Menu, MenuAction, MenuSeparator
except Exception as exc:  # pragma: no cover - only on missing dependency
    raise SystemExit(
        "缺少 pywebview，请先运行 setup.bat 或执行：\n"
        "  .venv\\Scripts\\python.exe -m pip install pywebview"
    ) from exc


class DesktopApi:
    def __init__(self, url: str):
        self.url = url
        self._opened = False

    def open_browser(self) -> bool:
        """Open the current local URL in the user's default browser."""
        webbrowser.open_new_tab(self.url)
        self._opened = True
        return True

    def close(self) -> bool:
        for window in list(webview.windows):
            window.destroy()
        return True


def _run_browser_only(url: str) -> None:
    print(f"  浏览器：{url}")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="EchoStep 初中英语听力练习（桌面窗口）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--debug", action="store_true", help="允许回放/拖动；同时打开 WebView 调试")
    parser.add_argument("--browser", action="store_true", help="不创建窗口，直接在默认浏览器打开")
    args = parser.parse_args()

    frozen = bool(getattr(sys, "frozen", False))
    resource_root = Path(sys._MEIPASS) if frozen else ROOT
    base_dir = Path(sys.executable).resolve().parent if frozen else ROOT
    data_dir = args.data_dir or (base_dir / "data")
    cache_dir = base_dir / "output" / "audio"

    port = _pick_port(args.host, args.port) if args.port else 0
    server, application = create_server(
        args.host,
        port,
        root=resource_root,
        data_dir=data_dir,
        debug=args.debug,
        cache_dir=cache_dir,
    )
    actual_port = server.server_address[1]
    base_url = f"http://{args.host}:{actual_port}"
    embedded_url = f"{base_url}/?embedded=1"

    print("=" * 58)
    print("  EchoStep · 初中英语听力练习")
    print(f"  本机地址：{base_url}")
    print(f"  数据目录：{application.data_dir}")
    print(f"  模式：{'DEBUG（可回放/拖动）' if application.debug else '考试模式（听力不可回放）'}")
    print("=" * 58)

    thread = threading.Thread(target=server.serve_forever, name="echostep-http", daemon=True)
    thread.start()

    if args.browser:
        try:
            _run_browser_only(base_url)
        finally:
            server.shutdown()
            server.server_close()
        return

    api = DesktopApi(base_url)
    menu = [
        Menu(
            "文件",
            [
                MenuAction("在浏览器中打开", api.open_browser),
                MenuSeparator(),
                MenuAction("退出", api.close),
            ],
        )
    ]
    webview.create_window(
        "EchoStep · 初中英语听力练习",
        embedded_url,
        js_api=api,
        width=1100,
        height=680,
        min_size=(820, 560),
        background_color="#F4F1E9",
        text_select=True,
        confirm_close=False,
        menu=menu,
    )
    storage = application.data_dir / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    try:
        icon = resource_root / "app.ico"
        webview.start(
            debug=bool(args.debug),
            private_mode=False,
            storage_path=str(storage),
            icon=str(icon) if icon.exists() else None,
        )
    finally:
        server.shutdown()
        server.server_close()


def _report_fatal(exc: BaseException) -> None:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
    log = base / "echostep-error.log"
    try:
        log.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"EchoStep 启动失败：{exc}\n\n详细信息已写入：\n{log}",
            "EchoStep",
            0x10,
        )
    except Exception:
        print(traceback.format_exc())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:
        _report_fatal(exc)
