"""TTS 引擎：本地 Piper（默认）、Edge 在线、Windows SAPI。

- 英文片段用英文音色；中文题干/指令用中文音色。
- 默认 Piper：en_US-amy-low int8（18.7 MB）+ zh_CN-huayan-x_low int8（7.6 MB）。
- 支持“整套试卷音频”：试音 → 中文指令/题干 → 英文材料/选项。
- 所有结果按内容哈希缓存到 output/audio。
"""

from __future__ import annotations

import array
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any

from .schema import CJK_RE

LETTERS = "ABCD"
EDGE_BILINGUAL_VOICE = "en-US-AvaMultilingualNeural"
EDGE_VOICES = [
    {"id": "en-US-AriaNeural", "name": "Aria · 美音女声", "desc": "自然清晰，适合日常对话", "lang": "en"},
    {"id": "en-US-GuyNeural", "name": "Guy · 美音男声", "desc": "沉稳，适合独白", "lang": "en"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia · 英音女声", "desc": "英式发音，适合中考英音", "lang": "en"},
    {"id": "en-GB-RyanNeural", "name": "Ryan · 英音男声", "desc": "英式男声", "lang": "en"},
    {"id": "en-AU-NatashaNeural", "name": "Natasha · 澳音女声", "desc": "澳式发音", "lang": "en"},
    {"id": EDGE_BILINGUAL_VOICE, "name": "Ava · 中英双语", "desc": "中文题干 + 英文材料，整套考试推荐", "lang": "multi"},
]
PIPER_LABELS = {
    "en_US-amy-low": "Amy · 美音女声",
    "en_GB-alan-low": "Alan · 英音男声",
    "en_US-lessac-low": "Lessac · 美音女声",
    "en_US-ryan-low": "Ryan · 美音男声",
    "zh_CN-huayan-x_low": "Huayan · 中文女声",
    "zh_CN-huayan-medium": "Huayan · 中文女声（medium）",
    "zh_CN-xiao_ya-medium": "Xiao Ya · 中文女声",
    "zh_CN-chaowen-medium": "Chao Wen · 中文男声",
}


class TTSError(RuntimeError):
    pass


# Segment = (text, pause_after_seconds, lang)
Segment = tuple[str, float, str]


def _clean_for_tts(text: str) -> str:
    text = text.replace("\u2014", ", ").replace("\u2013", ", ")
    text = text.replace("&", " and ")
    text = text.replace("*", "").replace("#", "").replace("`", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return text.strip()


def _zh_instruction(section: dict) -> str:
    text = _clean_for_tts(str(section.get("instruction") or ""))
    if CJK_RE.search(text):
        return text
    return "听下面一段材料，回答后面的问题。"


def _section_questions_text(
    section: dict,
    *,
    read_questions: bool,
    read_questions_zh: bool,
    zh_available: bool,
    read_options: bool = False,
) -> list[Segment]:
    if not read_questions:
        return []
    use_zh = read_questions_zh and zh_available
    segments: list[Segment] = []
    if use_zh:
        segments.append(("请听题。", 0.55, "zh"))
    else:
        segments.append(("Now, the questions.", 0.55, "en"))
    for question in section.get("questions") or []:
        if use_zh:
            stem = _clean_for_tts(question.get("question_zh") or question.get("question", ""))
            segments.append((f"第 {question['number']} 题。{stem}", 0.42, "zh"))
        else:
            stem = _clean_for_tts(question.get("question", ""))
            segments.append((f"Question {question['number']}. {stem}", 0.42, "en"))
        if read_options:
            for letter, option in zip(LETTERS, question.get("options") or []):
                segments.append((f"Option {letter}. {_clean_for_tts(option)}", 0.28, "en"))
    return segments


def _material_segments(audio_text: str, *, after: float, repeats: int = 2) -> list[Segment]:
    """One material, read N times with a 2-second gap, then answer pause."""
    lines = [_clean_for_tts(line) for line in str(audio_text).splitlines()]
    lines = [line for line in lines if line]
    segments: list[Segment] = []
    repeats = max(1, int(repeats))
    for pass_index in range(repeats):
        for line in lines:
            segments.append((line, 0.32, "en"))
        if pass_index < repeats - 1:
            segments.append(("", 2.0, "en"))
    segments.append(("", max(0.5, after), "en"))
    return segments


def build_section_segments(
    section: dict,
    *,
    repeat: int = 2,
    read_questions: bool = True,
    read_questions_zh: bool = True,
    zh_available: bool = True,
    read_options: bool = False,
) -> list[Segment]:
    """Section replay (used only after the exam / debug mode)."""
    segments: list[Segment] = [(_zh_instruction(section), 1.0, "zh")]
    repeats = 3 if section.get("type") == "table_fill" else 2
    for material in section.get("materials") or []:
        segments.extend(_material_segments(material.get("audio_text", ""), after=3.0, repeats=repeats))
    return segments


def build_exam_segments(
    test: dict,
    *,
    repeat: int = 2,
    read_questions: bool = True,
    read_questions_zh: bool = True,
    zh_available: bool = True,
    soundcheck: bool = True,
    read_options: bool = False,
) -> list[Segment]:
    """Template A audio: soundcheck, section instructions, materials, pauses.

    Per the supplied listening script, questions and options are NOT read.
    """
    segments: list[Segment] = []
    if soundcheck:
        segments.append(
            (
                "Hello, this is a microphone test. Testing, one, two, three. "
                "The quick brown fox jumps over the lazy dog. "
                "Can you hear me clearly? If so, we are ready to begin.",
                2.0,
                "en",
            )
        )
    segments.append(("听力考试现在开始。请同学们翻到第 1 页。", 3.0, "zh"))

    for section in test.get("sections") or []:
        index = section.get("index", 1)
        section_type = section.get("type", "")
        segments.append((_zh_instruction(section), 3.0, "zh"))
        questions = section.get("questions") or []
        if section_type in {"word_choice", "word_match", "short_dialogue"}:
            for material_index, material in enumerate(section.get("materials") or []):
                nums = [q["number"] for q in questions if q.get("material_index") == material_index]
                if nums:
                    segments.append((f"第 {nums[0]} 题。", 1.0, "zh"))
                segments.extend(_material_segments(material.get("audio_text", ""), after=5.0))
        elif section_type == "long_dialogue":
            for material_index, material in enumerate(section.get("materials") or []):
                nums = [q["number"] for q in questions if q.get("material_index") == material_index]
                if nums:
                    first, last = nums[0], nums[-1]
                    cue = f"听下面一段对话，回答第 {first} 至 {last} 题。" if first != last else f"听下面一段对话，回答第 {first} 题。"
                    segments.append((cue, 2.0, "zh"))
                segments.extend(_material_segments(material.get("audio_text", ""), after=8.0 * max(1, len(nums))))
        elif section_type in {"passage", "table_fill"}:
            repeats = 3 if section_type == "table_fill" else 2
            for material in section.get("materials") or []:
                nums = [q["number"] for q in questions if q.get("material_index") == 0]
                if nums:
                    segments.append((f"第 {nums[0]} 至 {nums[-1]} 题。", 1.0, "zh"))
                segments.extend(_material_segments(material.get("audio_text", ""), after=30.0, repeats=repeats))
        segments.append((f"第{index}节到此结束。", 3.0, "zh"))

    segments.append(("听力考试到此结束。请同学们继续作答笔试部分。", 1.5, "zh"))
    return segments


def build_segments(
    section: dict,
    *,
    repeat: int = 2,
    read_questions: bool = True,
    read_questions_zh: bool = True,
    zh_available: bool = True,
    read_options: bool = False,
) -> list[Segment]:
    return build_section_segments(section)


def _segments_text(segments: list[Segment]) -> str:
    return "\n\n".join(text for text, _, _ in segments if text.strip())


def _hash(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]


def _pcm16_mono(
    frames: bytes,
    channels: int,
    sample_width: int,
    rate: int,
    target_rate: int,
) -> bytes:
    """把 Piper/SAPI 的 16-bit PCM 转成单声道 + 目标采样率。"""
    if sample_width != 2:
        raise TTSError(f"不支持的采样位宽：{sample_width * 8} bit")
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if channels == 2:
        mono = array.array("h", [0]) * (len(samples) // 2)
        for i in range(len(mono)):
            mono[i] = (samples[2 * i] + samples[2 * i + 1]) // 2
        samples = mono
    elif channels != 1:
        raise TTSError(f"不支持的声道数：{channels}")
    if rate != target_rate and samples:
        ratio = target_rate / rate
        out_len = max(1, int(len(samples) * ratio))
        out = array.array("h", [0]) * out_len
        last = len(samples) - 1
        for i in range(out_len):
            pos = i / ratio
            idx = int(pos)
            frac = pos - idx
            s0 = samples[min(idx, last)]
            s1 = samples[min(idx + 1, last)]
            out[i] = int(s0 + (s1 - s0) * frac)
        samples = out
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


class TTSService:
    def __init__(self, root: Path, cache_dir: Path | None = None):
        self.root = Path(root)
        self.model_dir = self.root / "models" / "piper"
        self.cache_dir = Path(cache_dir) if cache_dir else self.root / "output" / "audio"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tools_dir = self.root / "tools"
        self._piper_lock = threading.RLock()
        self._synth_lock = threading.Lock()
        self._piper_voices: dict[str, Any] = {}
        self._sapi_voices_cache: tuple[float, list[dict]] | None = None
        # 中文题干里常混有英文人名，Piper 会打印大量 missing phoneme 警告；
        # 不影响音频，压到 ERROR 级别避免刷屏。
        for logger_name in ("piper.phoneme_ids", "piper.phonemize_chinese"):
            logging.getLogger(logger_name).setLevel(logging.ERROR)

    # ------------------------------------------------------------ discovery
    def _piper_models(self) -> dict[str, dict]:
        models: dict[str, dict] = {}
        if not self.model_dir.exists():
            return models
        for path in sorted(self.model_dir.glob("*.onnx")):
            name = path.name
            base = name[: -len(".onnx")]
            int8 = base.endswith(".int8")
            voice_id = base[: -len(".int8")] if int8 else base
            config = path.with_suffix(".onnx.json")
            if not config.exists():
                alt = self.model_dir / f"{voice_id}.onnx.json"
                config = alt if alt.exists() else config
            if not config.exists():
                continue
            entry = models.setdefault(
                voice_id,
                {
                    "id": voice_id,
                    "path": path,
                    "config": config,
                    "int8": int8,
                    "size": 0,
                    "lang": "zh" if voice_id.startswith("zh_") else "en",
                },
            )
            if int8 or not entry.get("int8"):
                entry.update({"path": path, "config": config, "int8": int8})
            entry["size"] += path.stat().st_size
        for entry in models.values():
            entry["size_mb"] = round(entry["size"] / 1_000_000, 1)
            entry["name"] = PIPER_LABELS.get(entry["id"], entry["id"])
        return models

    def _sapi_available(self) -> bool:
        return os.name == "nt" and (self.tools_dir / "sapi_segments.ps1").exists()

    def _sapi_voice_entries(self) -> list[dict]:
        return self._list_sapi_voices()

    def engines(self) -> list[dict]:
        piper_models = self._piper_models()
        piper_en = [model for model in piper_models.values() if model["lang"] == "en"]
        piper_zh = [model for model in piper_models.values() if model["lang"] == "zh"]
        piper_ready = bool(piper_en)
        try:
            import edge_tts  # noqa: F401

            edge_ready = True
        except Exception:
            edge_ready = False
        sapi_ready = self._sapi_available()
        sapi_all = self._sapi_voice_entries() if sapi_ready else []
        sapi_en = [voice for voice in sapi_all if voice.get("lang") == "en"]
        sapi_zh = [voice for voice in sapi_all if voice.get("lang") == "zh"]
        if sapi_ready and not sapi_en:
            sapi_en = [{"id": "", "name": "系统默认英语语音", "desc": "使用 Windows 默认 TTS", "lang": "en"}]
        return [
            {
                "id": "piper",
                "name": "本地神经语音",
                "badge": "推荐",
                "available": piper_ready,
                "offline": True,
                "size_mb": round(sum(model["size_mb"] for model in piper_models.values()), 1) or 0,
                "detail": (
                    f"本地 Piper 模型：英文 {len(piper_en)} 个，中文 {len(piper_zh)} 个，离线可用"
                    if piper_ready
                    else "未找到 models/piper 下的英文语音模型"
                ),
                "voices": [
                    {
                        "id": model["id"],
                        "name": model["name"],
                        "desc": f"本地 · {model['size_mb']} MB" + (" · int8" if model["int8"] else ""),
                        "lang": "en",
                    }
                    for model in piper_en
                ],
                "chinese_available": bool(piper_zh),
                "chinese_voice": piper_zh[0]["id"] if piper_zh else "",
                "chinese_name": piper_zh[0]["name"] if piper_zh else "",
            },
            {
                "id": "edge",
                "name": "Edge 在线语音",
                "badge": "更自然",
                "available": edge_ready,
                "offline": False,
                "size_mb": 0,
                "detail": "微软神经网络语音；含中文题干时自动使用双语语音 Ava",
                "voices": EDGE_VOICES,
                "chinese_available": edge_ready,
                "chinese_voice": EDGE_BILINGUAL_VOICE,
                "chinese_name": "Ava · 中英双语",
            },
            {
                "id": "sapi",
                "name": "Windows 本地语音",
                "badge": "0 MB",
                "available": sapi_ready,
                "offline": True,
                "size_mb": 0,
                "detail": "调用系统 SAPI；中文题干使用系统中文语音，英文材料使用英文语音",
                "voices": sapi_en,
                "chinese_available": bool(sapi_zh),
                "chinese_voice": sapi_zh[0]["id"] if sapi_zh else "",
                "chinese_name": sapi_zh[0]["name"] if sapi_zh else "",
            },
        ]

    def resolve_engine(self, engine: str) -> tuple[str, str]:
        engines = {item["id"]: item for item in self.engines()}
        if engine in engines and engines[engine]["available"]:
            return engine, ""
        for candidate in ("piper", "edge", "sapi"):
            if engines.get(candidate, {}).get("available"):
                return candidate, ""
        return "piper", ""

    def default_voice(self, engine: str) -> str:
        engines = {item["id"]: item for item in self.engines()}
        voices = engines.get(engine, {}).get("voices") or []
        return voices[0]["id"] if voices else ""

    def chinese_available(self, engine: str) -> bool:
        engines = {item["id"]: item for item in self.engines()}
        return bool(engines.get(engine, {}).get("chinese_available"))

    def chinese_voice(self, engine: str) -> str:
        engines = {item["id"]: item for item in self.engines()}
        return str(engines.get(engine, {}).get("chinese_voice") or "")

    def validate_voice(self, engine: str, voice: str) -> str:
        engines = {item["id"]: item for item in self.engines()}
        if engine not in engines or not engines[engine]["available"]:
            raise TTSError(f"语音引擎「{engine}」不可用")
        voices = engines[engine]["voices"]
        if not voices:
            raise TTSError("该引擎没有可用音色")
        ids = [item["id"] for item in voices]
        if voice in ids:
            return voice
        return ids[0]

    # --------------------------------------------------------------- public
    def synthesize_section(
        self,
        section: dict,
        *,
        engine: str,
        voice: str,
        speed: float = 1.0,
        repeat: int = 1,
        read_questions: bool = True,
        read_questions_zh: bool = True,
        read_options: bool = False,
    ) -> Path:
        engine, _ = self.resolve_engine(engine)
        try:
            voice = self.validate_voice(engine, voice)
        except TTSError:
            voice = self.default_voice(engine)
        speed = max(0.5, min(1.5, float(speed or 1.0)))
        repeat = max(1, min(3, int(repeat or 1)))
        zh_available = self.chinese_available(engine)
        segments = build_section_segments(
            section,
            repeat=repeat,
            read_questions=bool(read_questions),
            read_questions_zh=bool(read_questions_zh),
            zh_available=zh_available,
            read_options=bool(read_options),
        )
        return self._synthesize_cached(
            segments,
            engine=engine,
            voice=voice,
            speed=speed,
            extra={"kind": "section"},
        )

    def synthesize_exam(
        self,
        test: dict,
        *,
        engine: str,
        voice: str,
        speed: float = 1.0,
        repeat: int = 1,
        read_questions: bool = True,
        read_questions_zh: bool = True,
        soundcheck: bool = True,
        read_options: bool = False,
    ) -> Path:
        engine, _ = self.resolve_engine(engine)
        try:
            voice = self.validate_voice(engine, voice)
        except TTSError:
            voice = self.default_voice(engine)
        speed = max(0.5, min(1.5, float(speed or 1.0)))
        zh_available = self.chinese_available(engine)
        segments = build_exam_segments(
            test,
            repeat=max(1, min(3, int(repeat or 1))),
            read_questions=bool(read_questions),
            read_questions_zh=bool(read_questions_zh),
            zh_available=zh_available,
            soundcheck=bool(soundcheck),
            read_options=bool(read_options),
        )
        return self._synthesize_cached(
            segments,
            engine=engine,
            voice=voice,
            speed=speed,
            extra={"kind": "exam", "test_id": test.get("id", "")},
        )

    def preview(self, *, engine: str, voice: str, speed: float = 1.0) -> Path:
        engine, _ = self.resolve_engine(engine)
        try:
            voice = self.validate_voice(engine, voice)
        except TTSError:
            voice = self.default_voice(engine)
        speed = max(0.5, min(1.5, float(speed or 1.0)))
        zh_available = self.chinese_available(engine)
        segments: list[Segment] = []
        if zh_available:
            segments += [
                ("试音环节。请调整音量。", 0.5, "zh"),
                ("第一题：Mary 假期去了哪里？", 0.45, "zh"),
            ]
        segments += [
            ("Hello! This is EchoStep.", 0.4, "en"),
            ("Listen to the conversation and choose the best answer.", 0.4, "en"),
            ("Option A. I went to the mountains.", 0.35, "en"),
            ("Option B. I stayed at home.", 0.5, "en"),
        ]
        return self._synthesize_cached(
            segments,
            engine=engine,
            voice=voice,
            speed=speed,
            extra={"kind": "preview"},
        )

    def cache_size(self) -> tuple[int, int]:
        count = 0
        size = 0
        for path in self.cache_dir.glob("*"):
            if path.is_file():
                count += 1
                size += path.stat().st_size
        return count, size

    def clear_cache(self) -> int:
        removed = 0
        for path in self.cache_dir.glob("*"):
            if not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    # -------------------------------------------------------------- internal
    def _synthesize_cached(
        self,
        segments: list[Segment],
        *,
        engine: str,
        voice: str,
        speed: float,
        extra: dict[str, Any],
    ) -> Path:
        has_zh = any(lang == "zh" and text.strip() for text, _, lang in segments)
        effective_voice = voice
        if engine == "edge" and has_zh and "Multilingual" not in voice:
            effective_voice = EDGE_BILINGUAL_VOICE
        ext = "mp3" if engine == "edge" else "wav"
        key_material = {
            "v": 4,
            "engine": engine,
            "voice": effective_voice,
            "speed": round(speed, 3),
            "segments": segments,
            **extra,
        }
        key = _hash(key_material)
        target = self.cache_dir / f"{key}.{ext}"
        if target.exists() and target.stat().st_size > 100:
            return target
        with self._synth_lock:
            if target.exists() and target.stat().st_size > 100:
                return target
            temp = self.cache_dir / f".{key}.{uuid.uuid4().hex[:8]}.{ext}"
            try:
                if engine == "piper":
                    self._synth_piper(segments, voice, speed, temp)
                elif engine == "edge":
                    self._synth_edge(segments, effective_voice, speed, temp)
                elif engine == "sapi":
                    self._synth_sapi(segments, voice, speed, temp)
                else:
                    raise TTSError(f"未知语音引擎：{engine}")
                if not temp.exists() or temp.stat().st_size < 100:
                    raise TTSError("语音合成失败：生成的文件为空")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        return target

    def _get_piper(self, voice: str):
        models = self._piper_models()
        if voice not in models:
            raise TTSError(f"未找到本地语音模型：{voice}")
        model = models[voice]
        path = str(model["path"])
        with self._piper_lock:
            if path in self._piper_voices:
                return self._piper_voices[path]
            try:
                from piper import PiperVoice
            except Exception as exc:
                raise TTSError("未安装 piper-tts，请运行 setup.bat") from exc
            self._piper_voices[path] = PiperVoice.load(
                path,
                config_path=str(model["config"]),
            )
            return self._piper_voices[path]

    def _synth_piper(
        self, segments: list[Segment], voice: str, speed: float, target: Path
    ) -> None:
        from piper.config import SynthesisConfig

        zh_voice = self.chinese_voice("piper")
        config = SynthesisConfig(length_scale=1.0 / speed)
        chunks: list[tuple[bytes, int, int, int, float]] = []
        target_rate: int | None = None
        target_channels = 1
        target_width = 2
        with self._piper_lock:
            for text, pause, lang in segments:
                seg_voice = zh_voice if lang == "zh" and zh_voice else voice
                if not text.strip():
                    if target_rate:
                        chunks.append((b"", target_rate, target_channels, target_width, pause))
                    continue
                piper_voice = self._get_piper(seg_voice)
                buffer = io.BytesIO()
                try:
                    with wave.open(buffer, "wb") as wav:
                        piper_voice.synthesize_wav(text, wav, syn_config=config)
                except Exception as exc:
                    raise TTSError(f"Piper 合成失败：{exc}") from exc
                buffer.seek(0)
                with wave.open(buffer, "rb") as wav:
                    params = wav.getparams()
                    frames = wav.readframes(params.nframes)
                if target_rate is None:
                    target_rate = params.framerate
                if (
                    params.framerate != target_rate
                    or params.nchannels != 1
                    or params.sampwidth != 2
                ):
                    frames = _pcm16_mono(
                        frames, params.nchannels, params.sampwidth, params.framerate, target_rate
                    )
                chunks.append((frames, target_rate, 1, 2, pause))
        if target_rate is None:
            raise TTSError("Piper 没有生成音频")
        lead = b"\x00\x00" * int(target_rate * 0.25)
        tail = b"\x00\x00" * int(target_rate * 0.7)
        with wave.open(str(target), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(target_rate)
            out.writeframes(lead)
            for frames, _, _, _, pause in chunks:
                if frames:
                    out.writeframes(frames)
                out.writeframes(b"\x00\x00" * int(target_rate * max(0.05, pause)))
            out.writeframes(tail)

    def _synth_edge(
        self, segments: list[Segment], voice: str, speed: float, target: Path
    ) -> None:
        try:
            import edge_tts
        except Exception as exc:
            raise TTSError("未安装 edge-tts，请运行 setup.bat") from exc
        text = _segments_text(segments)
        if not text:
            raise TTSError("没有可朗读的文本")
        percent = int(round((speed - 1.0) * 100))
        percent = max(-50, min(50, percent))
        rate = f"{percent:+d}%"

        async def run() -> None:
            communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
            await asyncio.wait_for(communicate.save(str(target)), timeout=260)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        except asyncio.TimeoutError as exc:
            raise TTSError("Edge 语音合成超时，请检查网络后重试") from exc
        except Exception as exc:
            raise TTSError(f"Edge 语音合成失败：{exc}") from exc
        finally:
            loop.close()

    def _synth_sapi(
        self, segments: list[Segment], voice: str, speed: float, target: Path
    ) -> None:
        if not self._sapi_available():
            raise TTSError("当前系统不支持 Windows SAPI 语音")
        zh_voice = self.chinese_voice("sapi")
        payload = []
        for text, pause, lang in segments:
            if not text.strip():
                if pause > 0:
                    payload.append({"text": "", "voice": "", "pause": pause})
                continue
            seg_voice = zh_voice if lang == "zh" and zh_voice else voice
            payload.append({"text": text, "voice": seg_voice, "pause": max(0.05, pause)})
        if not payload:
            raise TTSError("没有可朗读的文本")
        rate = max(-8, min(8, int(round((speed - 1.0) * 8))))
        json_file = self.cache_dir / f".sapi-{uuid.uuid4().hex}.json"
        json_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        script = self.tools_dir / "sapi_segments.ps1"
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-JsonFile",
            str(json_file),
            "-OutFile",
            str(target),
            "-Rate",
            str(rate),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise TTSError("Windows 语音合成超时") from exc
        finally:
            json_file.unlink(missing_ok=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:400]
            raise TTSError(f"Windows 语音合成失败：{detail}")

    def _list_sapi_voices(self) -> list[dict]:
        now = time.time()
        if self._sapi_voices_cache and now - self._sapi_voices_cache[0] < 300:
            return self._sapi_voices_cache[1]
        script = self.tools_dir / "sapi_voices.ps1"
        if not script.exists():
            return []
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=creationflags,
            )
        except Exception:
            return []
        voices = []
        for line in (result.stdout or "").splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 2 and parts[0]:
                name, culture = parts[0], parts[1]
                lang = "zh" if culture.lower().startswith("zh") else "en" if culture.lower().startswith("en") else ""
                if not lang:
                    continue
                voices.append(
                    {
                        "id": name,
                        "name": name.replace("Microsoft ", "").replace(" Desktop", ""),
                        "desc": f"{culture} · 系统语音",
                        "lang": lang,
                    }
                )
        self._sapi_voices_cache = (now, voices)
        return voices
