"""人教版 Go for it! 初中英语教材单元与年级能力范围。

这里只放“教材目录 + 年级边界”，具体词汇、语法、话题和题型交给
DeepSeek 根据年级/册/单元自行命题。这样既不用维护庞大的词表，也能
让模型明确知道“不能超纲”。
"""

from __future__ import annotations

from collections import OrderedDict

GRADES: "OrderedDict[str, dict]" = OrderedDict(
    [
        (
            "七年级",
            {
                "label": "七年级",
                "short": "G7",
                "tagline": "打基础 · 短对话 · 直接信息",
                "books": ["上册", "下册"],
                "scope": (
                    "七年级学生。七上以一般现在时、现在进行时、can、there be、名词单复数、"
                    "人称代词、数词、时间与地点介词为主；七下开始学习一般过去时、祈使句、"
                    "情态动词 would like 等。词汇量约 800，句子以简单句为主。听力材料应短小、"
                    "语速自然偏慢，题目以“谁/何时/何地/做什么/为什么”等直接信息题为主，"
                    "最多加入少量简单推断。不得使用现在完成时、定语从句、被动语态、虚拟语气等超纲语法。"
                ),
                "style": "2-4 个来回的日常对话或 60-100 词的独白，话题贴近校园与家庭。",
            },
        ),
        (
            "八年级",
            {
                "label": "八年级",
                "short": "G8",
                "tagline": "重运用 · 情景推断 · 单元语法",
                "books": ["上册", "下册"],
                "scope": (
                    "八年级学生。八上重点是一般将来时、比较级/最高级、情态动词、"
                    "how often 等频率表达、条件状语从句（if）、可数/不可数名词；"
                    "八下重点是过去进行时、现在完成时、反身代词、情态动词 could/should、"
                    "动词不定式、宾语从句初步等。词汇量约 1600，可出现简单复合句和因果、转折关系。"
                    "题目以细节理解、简单推断、场景判断、数字/时间计算为主。不得使用九年级才学的"
                    "定语从句、较复杂的被动语态或高中词汇。"
                ),
                "style": "80-140 词的对话或独白，含 1-2 个信息转折，问题覆盖细节与简单推断。",
            },
        ),
        (
            "九年级",
            {
                "label": "九年级",
                "short": "G9",
                "tagline": "中考标准 · 综合理解 · 观点态度",
                "books": ["全一册"],
                "scope": (
                    "九年级学生，按中考听力标准命题。可综合七至九年级语法：宾语从句、定语从句、"
                    "被动语态、现在完成时、过去完成时、used to、情态动词表推测、感叹句等。"
                    "词汇量约 2000，材料可涉及文化、科技、环保、成长、人际交往等话题。"
                    "题目应包含细节理解、推断、主旨、说话人意图/态度、数字计算等中考常见设问，"
                    "但仍不得出现高中及以上词汇或过度专业的背景知识。"
                ),
                "style": "120-180 词的对话或独白，信息层次更丰富，设问接近中考听力真题。",
            },
        ),
    ]
)


def _unit(uid: str, title: str) -> dict:
    return {"id": uid, "title": title, "name": title.split(" ", 1)[0] if " " in title else title}


def _build_books() -> dict:
    books: dict = {}
    for grade, meta in GRADES.items():
        for book in meta["books"]:
            key = f"{grade}{book}"
            units: list[dict] = []
            if grade == "七年级" and book == "上册":
                units = [
                    _unit("7A-S1", "Starter Unit 1 Hello!"),
                    _unit("7A-S2", "Starter Unit 2 Keep Tidy!"),
                    _unit("7A-S3", "Starter Unit 3 Welcome!"),
                    _unit("7A-U1", "Unit 1 You and Me"),
                    _unit("7A-U2", "Unit 2 We’re Family!"),
                    _unit("7A-U3", "Unit 3 My School"),
                    _unit("7A-U4", "Unit 4 My Favourite Subject"),
                    _unit("7A-U5", "Unit 5 Fun Clubs"),
                    _unit("7A-U6", "Unit 6 A Day in the Life"),
                    _unit("7A-U7", "Unit 7 Happy Birthday"),
                ]
            elif grade == "七年级" and book == "下册":
                units = [
                    _unit("7B-U1", "Unit 1 Animal Friends"),
                    _unit("7B-U2", "Unit 2 No Rules, No Order"),
                    _unit("7B-U3", "Unit 3 Keep Fit"),
                    _unit("7B-U4", "Unit 4 Eat Well"),
                    _unit("7B-U5", "Unit 5 Here and Now"),
                    _unit("7B-U6", "Unit 6 Rain or Shine"),
                    _unit("7B-U7", "Unit 7 A Day to Remember"),
                    _unit("7B-U8", "Unit 8 Once upon a Time"),
                ]
            elif grade == "八年级" and book == "上册":
                units = [
                    _unit("8A-U1", "Unit 1 Happy Holiday"),
                    _unit("8A-U2", "Unit 2 Home Sweet Home"),
                    _unit("8A-U3", "Unit 3 Same or Different?"),
                    _unit("8A-U4", "Unit 4 Amazing Plants and Animals"),
                    _unit("8A-U5", "Unit 5 What a Delicious Meal!"),
                    _unit("8A-U6", "Unit 6 Plan for Yourself"),
                    _unit("8A-U7", "Unit 7 When Tomorrow Comes"),
                    _unit("8A-U8", "Unit 8 Let’s Communicate!"),
                ]
            elif grade == "八年级" and book == "下册":
                units = [
                    _unit("8B-U1", "Unit 1 Time to Relax"),
                    _unit("8B-U2", "Unit 2 Stay Healthy"),
                    _unit("8B-U3", "Unit 3 Growing Up"),
                    _unit("8B-U4", "Unit 4 The Wonders of Nature"),
                    _unit("8B-U5", "Unit 5 Nature’s Temper"),
                    _unit("8B-U6", "Unit 6 Crossing Cultures"),
                    _unit("8B-U7", "Unit 7 A Good Read"),
                    _unit("8B-U8", "Unit 8 Making a Difference"),
                ]
            elif grade == "九年级" and book == "全一册":
                units = [
                    _unit("9-U1", "Unit 1 How can we become good learners?"),
                    _unit("9-U2", "Unit 2 I think that mooncakes are delicious!"),
                    _unit("9-U3", "Unit 3 Could you please tell me where the restrooms are?"),
                    _unit("9-U4", "Unit 4 I used to be afraid of the dark."),
                    _unit("9-U5", "Unit 5 What are the shirts made of?"),
                    _unit("9-U6", "Unit 6 When was it invented?"),
                    _unit("9-U7", "Unit 7 Teenagers should be allowed to choose their own clothes."),
                    _unit("9-U8", "Unit 8 It must belong to Carla."),
                    _unit("9-U9", "Unit 9 I like music that I can dance to."),
                    _unit("9-U10", "Unit 10 You're supposed to shake hands."),
                    _unit("9-U11", "Unit 11 Sad movies make me cry."),
                    _unit("9-U12", "Unit 12 Life is full of the unexpected."),
                    _unit("9-U13", "Unit 13 We're trying to save the earth!"),
                    _unit("9-U14", "Unit 14 I remember meeting all of you in Grade 7."),
                ]
            midterm_ranges = {
                "七年级上册": "Starter Units 1–3 + Unit 1–4",
                "七年级下册": "Unit 1–4",
                "八年级上册": "Unit 1–4",
                "八年级下册": "Unit 1–4",
                "九年级全一册": "Unit 1–7",
            }
            midterm_range = midterm_ranges.get(key, "前半册")
            units.append(
                {
                    "id": f"{key}-MID",
                    "title": f"期中考试（{midterm_range}）",
                    "name": "期中考试",
                    "note": f"期中考试范围：只考本册前半部分 {midterm_range}，不要考后半册；按期中考试难度和题型比例命题。",
                }
            )
            units.append(
                {
                    "id": f"{key}-ALL",
                    "title": "综合复习（全册）",
                    "name": "综合复习",
                }
            )
            books[key] = {"grade": grade, "book": book, "units": units}
    return books


BOOKS = _build_books()


def grade_scope(grade: str) -> dict:
    return GRADES.get(grade, GRADES["八年级"])


def get_unit(grade: str, book: str, unit_id: str) -> dict | None:
    data = BOOKS.get(f"{grade}{book}")
    if not data:
        return None
    for unit in data["units"]:
        if unit["id"] == unit_id:
            return unit
    return None


def public_catalog() -> dict:
    return {
        "grades": [
            {
                "id": grade,
                "label": meta["label"],
                "short": meta["short"],
                "tagline": meta["tagline"],
                "books": meta["books"],
                "scope": meta["scope"],
            }
            for grade, meta in GRADES.items()
        ],
        "books": BOOKS,
    }
