"""内置听力卷 示例卷（直接取 Prompt 中的完整 30 题示例）。"""

from __future__ import annotations

import json

from .prompts import SYSTEM_PROMPT
from .schema import normalize_test

_start = SYSTEM_PROMPT.find("{")
SAMPLE_RAW, _ = json.JSONDecoder().raw_decode(SYSTEM_PROMPT[_start:])

REQUEST = {
    "grade": "九年级",
    "book": "全一册",
    "unit_id": "9-U1",
    "unit_title": "Unit 1 How can we become good learners?",
    "topic": "学习与校园生活",
}


def get_sample() -> dict:
    return normalize_test(SAMPLE_RAW, count=30, request=REQUEST)
