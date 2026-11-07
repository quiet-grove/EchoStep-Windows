"""模板 A 试卷结构校验、公开版与批改结果。"""

from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Any

LETTERS = "ABCDEF"
CJK_RE = re.compile(r"[\u3400-\u9fff]")
MARKDOWN_RE = re.compile(r"[*_`#]+")
BRACKET_RE = re.compile(r"\[[^\]]{0,40}\]")
OPTION_PREFIX_RE = re.compile(r"^\s*[A-Fa-fＡ-Ｆ]\s*[\.\)、:：]\s*")
FILL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9'’\-\s:.,/]*$")

SECTION_DEFS = {
    1: {
        "type": "word_choice",
        "instruction": "第一节  听句子，选出句子中含有的单词。每个句子读两遍。（5 分）",
        "materials": 5,
        "questions": 5,
    },
    2: {
        "type": "short_dialogue",
        "instruction": "第二节  听短对话，选择最佳答案。每段对话读两遍。（5 分）",
        "materials": 5,
        "questions": 5,
    },
    3: {
        "type": "long_dialogue",
        "instruction": "第三节  听长对话，选择最佳答案。每段对话读两遍。（10 分）",
        "materials": 3,
        "questions": 10,
    },
    4: {
        "type": "passage",
        "instruction": "第四节  听短文，选择最佳答案。短文读两遍。（5 分）",
        "materials": 1,
        "questions": 5,
    },
    5: {
        "type": "table_fill",
        "instruction": "第五节  听短文，完成下面的信息表。每空一词。短文读三遍。（5 分）",
        "materials": 1,
        "questions": 5,
    },
}


class ValidationError(ValueError):
    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.details = details


def _text(value: Any, field: str) -> str:
    if value is None:
        raise ValidationError(f"{field} 不能为空")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} 不能为空")
    return text


def _clean_audio_text(value: Any, field: str, *, min_len: int = 5) -> str:
    text = _text(value, field)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = MARKDOWN_RE.sub("", text)
    text = BRACKET_RE.sub("", text)
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line)
    text = "\n".join(lines).strip()
    if CJK_RE.search(text):
        raise ValidationError(f"{field} 必须是纯英文，不能出现中文")
    if len(text) < min_len:
        raise ValidationError(f"{field} 太短")
    if "\ufffd" in text:
        raise ValidationError(f"{field} 含有乱码字符")
    return text


def _clean_option(value: Any, field: str) -> str:
    text = MARKDOWN_RE.sub("", _text(value, field))
    text = OPTION_PREFIX_RE.sub("", text).strip()
    text = " ".join(text.split())
    if not text:
        raise ValidationError(f"{field} 为空")
    return text


def _answer_index(value: Any, count: int, field: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{field} 格式不正确")
    if isinstance(value, int):
        if 0 <= value < count:
            return value
        raise ValidationError(f"{field} 超出范围")
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"缺少 {field}")
    text = text.translate(str.maketrans("ＡＢＣＤＥＦ", "ABCDEF")).upper()
    text = re.sub(r"^[\(\[]?([A-F])[\)\].、:：]?$", r"\1", text)
    if text in LETTERS[:count]:
        return LETTERS.index(text)
    if text.isdigit():
        number = int(text)
        if 0 <= number < count:
            return number
    raise ValidationError(f"{field} 不是 A-{LETTERS[count - 1]} 之一")


def _normalize_fill(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _material_index(value: Any, material_count: int, field: str) -> int:
    try:
        index = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} 的 material_index 不正确") from exc
    if not 0 <= index < material_count:
        raise ValidationError(f"{field} 的 material_index 超出范围")
    return index


def normalize_test(obj: dict, *, request: dict, count: int = 30) -> dict:
    if not isinstance(obj, dict):
        raise ValidationError("模型返回的不是 JSON 对象")
    raw_sections = obj.get("sections")
    if not isinstance(raw_sections, list) or len(raw_sections) != 5:
        raise ValidationError("模板 A 必须有且只有 5 节")

    sections: list[dict] = []
    question_no = 0
    total_words = 0
    for section_index, raw_section in enumerate(raw_sections, 1):
        if not isinstance(raw_section, dict):
            raise ValidationError(f"第 {section_index} 节不是对象")
        definition = SECTION_DEFS[section_index]
        expected_type = definition["type"]
        section_type = str(raw_section.get("type") or expected_type)
        if section_type != expected_type:
            raise ValidationError(f"第 {section_index} 节类型应为 {expected_type}")

        raw_materials = raw_section.get("materials")
        if not isinstance(raw_materials, list) or len(raw_materials) != definition["materials"]:
            raise ValidationError(
                f"第 {section_index} 节应有 {definition['materials']} 段材料"
            )
        materials = []
        for material_index, raw_material in enumerate(raw_materials, 1):
            min_len = {1: 8, 2: 12, 3: 30, 4: 30, 5: 30}.get(section_index, 8)
            audio_text = _clean_audio_text(
                raw_material.get("audio_text") if isinstance(raw_material, dict) else raw_material,
                f"第 {section_index} 节第 {material_index} 段听力材料",
                min_len=min_len,
            )
            total_words += len(audio_text.split())
            materials.append(
                {
                    "id": f"s{section_index}m{material_index}",
                    "index": material_index,
                    "audio_text": audio_text,
                }
            )

        raw_questions = raw_section.get("questions")
        if not isinstance(raw_questions, list) or len(raw_questions) != definition["questions"]:
            raise ValidationError(
                f"第 {section_index} 节应有 {definition['questions']} 题"
            )

        word_bank = None
        table = None
        if section_type == "table_fill":
            raw_table = raw_section.get("table")
            if not isinstance(raw_table, dict) or not isinstance(raw_table.get("rows"), list):
                raise ValidationError("第五节缺少 table.rows")
            rows = raw_table["rows"]
            if len(rows) != 5:
                raise ValidationError("第五节信息表必须有 5 行")
            table = {
                "title": str(raw_table.get("title") or "Information Table").strip(),
                "rows": [],
            }
            for i, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    raise ValidationError("第五节信息表行格式不正确")
                table["rows"].append(
                    {
                        "number": int(row.get("number") or 25 + i),
                        "label": str(row.get("label") or "").strip(),
                        "prefix": str(row.get("prefix") or "").strip(),
                        "suffix": str(row.get("suffix") or "").strip(),
                    }
                )

        questions: list[dict] = []
        for raw_question in raw_questions:
            if not isinstance(raw_question, dict):
                raise ValidationError(f"第 {section_index} 节存在无效题目")
            question_no += 1
            number = int(raw_question.get("number") or question_no)
            if number != question_no:
                raise ValidationError(
                    f"题号不连续：应为 {question_no}，实际为 {number}"
                )
            material_index = _material_index(
                raw_question.get("material_index", 0),
                len(materials),
                f"第 {question_no} 题",
            )
            explanation = str(
                raw_question.get("explanation")
                or raw_question.get("analysis")
                or "答案依据录音内容。"
            ).strip()
            explanation = " ".join(explanation.split())

            if section_type == "table_fill":
                answer_text = _text(raw_question.get("answer_text"), f"第 {question_no} 题 answer_text")
                answer_text = " ".join(answer_text.split())
                if CJK_RE.search(answer_text) or len(answer_text) > 40 or not FILL_RE.match(answer_text):
                    raise ValidationError(f"第 {question_no} 题答案必须是英文单词、数字或时间（不能是句子）")
                questions.append(
                    {
                        "id": f"q{question_no}",
                        "number": question_no,
                        "type": "fill",
                        "material_index": material_index,
                        "question": "",
                        "options": [],
                        "answer": -1,
                        "answer_text": answer_text.casefold(),
                        "explanation": explanation,
                    }
                )
            else:
                default_question = "Which word did you hear?" if section_type == "word_choice" else ""
                question_text = _text(raw_question.get("question") or default_question, f"第 {question_no} 题 question")
                question_text = MARKDOWN_RE.sub("", " ".join(question_text.split()))
                raw_options = raw_question.get("options")
                if not isinstance(raw_options, list) or len(raw_options) != 3:
                    raise ValidationError(f"第 {question_no} 题必须有 3 个选项")
                options = [
                    _clean_option(item, f"第 {question_no} 题选项") for item in raw_options
                ]
                if len({item.casefold() for item in options}) != 3:
                    raise ValidationError(f"第 {question_no} 题有重复选项")
                answer = _answer_index(raw_question.get("answer"), 3, f"第 {question_no} 题 answer")
                questions.append(
                    {
                        "id": f"q{question_no}",
                        "number": question_no,
                        "type": "choice",
                        "material_index": material_index,
                        "question": question_text,
                        "options": options,
                        "answer": answer,
                        "explanation": explanation,
                    }
                )

        if section_type == "word_choice":
            # 保证第一节不是按顺序的 A/B/C；只打乱句子/题目顺序，
            # 选项和 explanation 里的字母仍一一对应。
            pairs = [(materials[q["material_index"]], q) for q in questions]
            rng = random.SystemRandom()
            for _ in range(16):
                rng.shuffle(pairs)
                letters = [q["answer"] for _, q in pairs]
                if letters not in ([0, 1, 2, 3, 4], [4, 3, 2, 1, 0]):
                    break
            materials = []
            questions = []
            for i, (material, question) in enumerate(pairs, 1):
                material["id"] = f"s1m{i}"
                material["index"] = i
                question["material_index"] = i - 1
                question["number"] = i
                question["id"] = f"q{i}"
                materials.append(material)
                questions.append(question)

        if section_type in {"word_choice", "table_fill"}:
            instruction = definition["instruction"]
        else:
            instruction = str(raw_section.get("instruction") or definition["instruction"]).strip()
            instruction = MARKDOWN_RE.sub("", instruction)
        sections.append(
            {
                "id": f"s{section_index}",
                "index": section_index,
                "type": section_type,
                "instruction": instruction,
                "word_bank": word_bank or [],
                "table": table,
                "materials": materials,
                "questions": questions,
            }
        )

    if question_no != 30:
        raise ValidationError(f"模板 A 必须是 30 题，实际生成 {question_no} 题")

    table_section = sections[-1]
    if table_section["type"] == "table_fill" and table_section["table"]:
        row_numbers = [row["number"] for row in table_section["table"]["rows"]]
        question_numbers = [question["number"] for question in table_section["questions"]]
        if row_numbers != question_numbers:
            raise ValidationError("第五节信息表题号与题目题号不一致")

    unit_title = request.get("unit_title") or "听力练习"
    title = str(obj.get("title") or "").strip()
    if not title or len(title) > 80:
        title = f"{request.get('grade', '')}{request.get('book', '')} {unit_title} 听力试卷（模板 A）"
    topic = str(obj.get("topic") or request.get("topic") or "").strip()

    return {
        "template": "A",
        "title": title,
        "topic": topic[:80],
        "grade": request.get("grade", ""),
        "book": request.get("book", ""),
        "unit_id": request.get("unit_id", ""),
        "unit_title": unit_title,
        "level": f"{request.get('grade', '')}{request.get('book', '')}",
        "question_count": 30,
        "total_score": 30,
        "section_count": 5,
        "total_words": total_words,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": sections,
    }


def public_test(test: dict) -> dict:
    sections = []
    for section in test.get("sections", []):
        sections.append(
            {
                "id": section["id"],
                "index": section["index"],
                "type": section["type"],
                "instruction": section["instruction"],
                "word_bank": list(section.get("word_bank") or []),
                "table": section.get("table"),
                "questions": [
                    {
                        "id": q["id"],
                        "number": q["number"],
                        "type": q["type"],
                        "material_index": q["material_index"],
                        "question": q["question"],
                        "options": list(q["options"]),
                    }
                    for q in section["questions"]
                ],
            }
        )
    return {
        "id": test.get("id", ""),
        "template": "A",
        "title": test.get("title", ""),
        "topic": test.get("topic", ""),
        "grade": test.get("grade", ""),
        "book": test.get("book", ""),
        "unit_id": test.get("unit_id", ""),
        "unit_title": test.get("unit_title", ""),
        "level": test.get("level", ""),
        "question_count": 30,
        "total_score": 30,
        "section_count": 5,
        "total_words": test.get("total_words", 0),
        "created_at": test.get("created_at", ""),
        "model": test.get("model", ""),
        "search_sources": test.get("search_sources", []),
        "search_warning": test.get("search_warning", ""),
        "sections": sections,
    }


def result_payload(test: dict, answers: dict[str, Any]) -> dict:
    details = []
    correct_count = 0
    for section in test.get("sections", []):
        for question in section["questions"]:
            raw = answers.get(question["id"])
            if question["type"] == "fill":
                selected_text = "" if raw is None else str(raw).strip()
                is_correct = _normalize_fill(selected_text) == _normalize_fill(
                    question.get("answer_text", "")
                )
                detail = {
                    "id": question["id"],
                    "number": question["number"],
                    "type": "fill",
                    "selected": selected_text,
                    "answer": question.get("answer_text", ""),
                    "correct": is_correct,
                    "explanation": question["explanation"],
                }
            else:
                try:
                    selected = int(raw) if raw is not None and str(raw) != "" else None
                except (TypeError, ValueError):
                    selected = None
                if selected is not None and selected not in range(len(question["options"])):
                    selected = None
                is_correct = selected == question["answer"]
                detail = {
                    "id": question["id"],
                    "number": question["number"],
                    "type": "choice",
                    "selected": selected,
                    "answer": question["answer"],
                    "correct": is_correct,
                    "explanation": question["explanation"],
                }
            if is_correct:
                correct_count += 1
            details.append(detail)

    total = len(details)
    percent = round(correct_count * 100 / total) if total else 0
    return {
        "score": correct_count,
        "total": total,
        "percent": percent,
        "details": details,
        "sections": [
            {
                "id": section["id"],
                "index": section["index"],
                "type": section["type"],
                "instruction": section["instruction"],
                "table": section.get("table"),
                "materials": [
                    {
                        "index": material["index"],
                        "transcript": material["audio_text"],
                        "questions": [
                            q["number"]
                            for q in section["questions"]
                            if q["material_index"] == material["index"] - 1
                        ],
                    }
                    for material in section["materials"]
                ],
            }
            for section in test.get("sections", [])
        ],
    }
