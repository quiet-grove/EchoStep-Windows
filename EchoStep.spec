# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ("web", "web"),
    ("models", "models"),
    ("tools", "tools"),
    ("app.ico", "."),
]
binaries = []
hiddenimports = []

for package in [
    "webview",
    "pythonnet",
    "clr_loader",
    "piper",
    "onnxruntime",
    "edge_tts",
    "aiohttp",
    "certifi",
    "bottle",
    "proxy_tools",
    "cffi",
]:
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception as error:
        print(f"[spec] collect_all({package}) failed: {error}")

hiddenimports += [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "webview.platforms.win32",
    "clr",
    "pythonnet",
    "encodings.idna",
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EchoStep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EchoStep",
)
