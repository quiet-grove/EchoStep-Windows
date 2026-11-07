"""下载 Piper 小型英语语音模型，并可选压缩为 int8。

用法：
    python tools/install_voice.py
    python tools/install_voice.py en_GB-alan-low
    python tools/install_voice.py en_US-amy-low --keep-fp32

默认下载 en_US-amy-low（约 61 MB），再动态量化为 int8（约 19 MB）。
模型放在项目根目录的 models/piper 下，整个项目可以搬到 D 盘任意位置。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "models" / "piper"
VOICE_RE = re.compile(r"^(?P<family>[^-]+)_(?P<region>[^-]+)-(?P<name>[^-]+)-(?P<quality>.+)$")
URL_TEMPLATE = (
    "https://{host}/rhasspy/piper-voices/resolve/main/"
    "{family}/{lang}/{name}/{quality}/{lang}-{name}-{quality}{ext}?download=true"
)
HOSTS = ["huggingface.co", "hf-mirror.com"]


def parse_voice(voice: str) -> dict:
    match = VOICE_RE.match(voice.strip())
    if not match:
        raise SystemExit(
            f"音色名「{voice}」格式不对，应类似 en_US-amy-low 或 en_GB-alan-low"
        )
    family = match.group("family")
    region = match.group("region")
    return {
        "voice": voice,
        "family": family,
        "lang": f"{family}_{region}",
        "name": match.group("name"),
        "quality": match.group("quality"),
    }


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "EchoStep/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        temp = target.with_suffix(target.suffix + ".part")
        with temp.open("wb") as file:
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                file.write(chunk)
                done += len(chunk)
                if total:
                    percent = done * 100 / total
                    print(f"\r  {target.name}: {percent:5.1f}%  ({done/1e6:5.1f}/{total/1e6:5.1f} MB)", end="")
                else:
                    print(f"\r  {target.name}: {done/1e6:5.1f} MB", end="")
        print()
    temp.replace(target)


def fetch_with_fallback(path: Path, info: dict) -> None:
    errors = []
    for host in HOSTS:
        url = URL_TEMPLATE.format(
            host=host,
            family=info["family"],
            lang=info["lang"],
            name=info["name"],
            quality=info["quality"],
            ext=path.name[len(info["voice"]) :],
        )
        try:
            print(f"下载 {path.name} …")
            download(url, path)
            return
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            errors.append(f"{host}: {exc}")
            print(f"  失败：{exc}")
    raise SystemExit("模型下载失败：\n" + "\n".join(errors))


def quantize(model: Path, keep_fp32: bool) -> None:
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except Exception as exc:
        print(f"未安装 onnx，跳过 int8 压缩（{exc}）。")
        print("如需压缩：.venv\\Scripts\\python.exe -m pip install onnx")
        return
    target = model.with_name(model.stem + ".int8.onnx")
    if target.exists():
        print(f"已存在 {target.name}，跳过压缩。")
        return
    print("正在压缩为 int8（通常 20-30 秒）……")
    try:
        quantize_dynamic(str(model), str(target), weight_type=QuantType.QInt8)
    except Exception as exc:
        print(f"int8 压缩失败，保留 fp32 模型：{exc}")
        target.unlink(missing_ok=True)
        return
    config = model.with_suffix(".onnx.json")
    if config.exists():
        shutil.copyfile(config, target.with_name(target.name + ".json"))
    print(f"已生成 {target.name}（{target.stat().st_size / 1e6:.1f} MB）。")
    if not keep_fp32:
        try:
            model.unlink()
            print("已删除 fp32 模型以节省空间。")
        except OSError:
            print("fp32 模型正在被占用，暂时保留。")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 Piper 英语语音模型")
    parser.add_argument("voice", nargs="?", default="en_US-amy-low")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--keep-fp32", action="store_true", help="压缩后保留原始 61 MB 模型")
    parser.add_argument("--no-quantize", action="store_true", help="只下载，不压缩")
    args = parser.parse_args()
    info = parse_voice(args.voice)
    model = args.dir / f"{info['voice']}.onnx"
    config = args.dir / f"{info['voice']}.onnx.json"
    int8 = args.dir / f"{info['voice']}.int8.onnx"
    if int8.exists() and int8.with_name(int8.name + ".json").exists():
        print(f"int8 模型已存在：{int8}")
        return
    if not model.exists():
        fetch_with_fallback(model, info)
    else:
        print(f"已存在：{model}")
    if not config.exists():
        fetch_with_fallback(config, info)
    if not args.no_quantize:
        quantize(model, args.keep_fp32)
    print("\n完成。模型目录：", args.dir)
    print("启动应用后，在「设置 → 语音朗读」里选择这个音色。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
