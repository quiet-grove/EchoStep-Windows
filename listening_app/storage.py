"""试卷持久化：每套卷一个 JSON 文件，刷新页面后仍可继续做。"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schema import public_test

TEST_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class TestStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def save(self, test: dict) -> dict:
        with self._lock:
            test = dict(test)
            test["id"] = test.get("id") or uuid.uuid4().hex[:12]
            test["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            path = self.directory / f"{test['id']}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(test, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return test

    def get(self, test_id: str) -> dict | None:
        if not TEST_ID_RE.match(test_id or ""):
            return None
        path = self.directory / f"{test_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return data
        except (OSError, ValueError):
            return None

    def delete(self, test_id: str) -> bool:
        if not TEST_ID_RE.match(test_id or ""):
            return False
        path = self.directory / f"{test_id}.json"
        if path.exists():
            path.unlink(missing_ok=True)
            return True
        return False

    def list(self, limit: int = 30) -> list[dict]:
        items: list[dict] = []
        with self._lock:
            for path in self.directory.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict) or data.get("template") != "A":
                    continue
                items.append(
                    {
                        "id": data.get("id") or path.stem,
                        "title": data.get("title", "未命名试卷"),
                        "grade": data.get("grade", ""),
                        "book": data.get("book", ""),
                        "unit_title": data.get("unit_title", ""),
                        "topic": data.get("topic", ""),
                        "question_count": data.get("question_count", 0),
                        "created_at": data.get("created_at", ""),
                        "model": data.get("model", ""),
                    }
                )
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return items[: max(1, min(100, limit))]

    def public(self, test_id: str) -> dict | None:
        test = self.get(test_id)
        return public_test(test) if test else None
