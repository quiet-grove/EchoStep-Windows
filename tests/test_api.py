import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_server
from listening_app.sample import SAMPLE_RAW, get_sample


class MockDeepSeek(BaseHTTPRequestHandler):
    calls = []

    def _send(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        MockDeepSeek.calls.append((self.path, payload))
        if self.path.endswith("/chat/completions"):
            self._send({
                "id": "mock",
                "model": "deepseek-flash",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(SAMPLE_RAW, ensure_ascii=False)},
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            })
        elif self.path.endswith("/tools/search"):
            self._send({
                "results": [{
                    "title": "Unit 1 listening practice",
                    "url": "https://example.com/unit1",
                    "snippet": "A travel dialogue.",
                    "summary": "A short travel dialogue about a summer vacation.",
                    "site_name": "Example",
                    "date": "2026-09-01T00:00:00+00:00",
                    "authority": 3,
                    "rerank_score": 2.0,
                }]
            })
        else:
            self._send({"error": {"message": "not found"}}, 404)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._send({"object": "list", "data": [{"id": "deepseek-flash"}]})
        else:
            self._send({"error": {"message": "not found"}}, 404)

    def log_message(self, *args):
        pass


def request(url, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        exc.close()
        return exc.code, json.loads(body or b"{}")


class ApiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = ThreadingHTTPServer(("127.0.0.1", 0), MockDeepSeek)
        cls.mock_port = cls.mock.server_address[1]
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        cls.tmp = tempfile.mkdtemp(prefix="echostep-api-")
        cls.server, cls.app = create_server(port=0, data_dir=Path(cls.tmp))
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.mock.shutdown()
        cls.mock.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        MockDeepSeek.calls.clear()
        status, _ = request(self.base + "/api/config", "POST", {
            "api_key": "sk-test-1234567890",
            "base_url": f"http://127.0.0.1:{self.mock_port}",
            "tts_engine": "piper",
            "tts_voice": "en_US-amy-low",
            "speed": 1.0,
            "web_search": True,
            "model": "deepseek-flash",
        })
        self.assertEqual(status, 200)

    def _generate(self, **overrides):
        payload = {
            "grade": "八年级", "book": "上册", "unit_id": "8A-U1",
            "topic": "", "web_search": False,
        }
        payload.update(overrides)
        return request(self.base + "/api/generate", "POST", payload)

    def test_state_hides_raw_key(self):
        status, state = request(self.base + "/api/state")
        self.assertEqual(status, 200)
        text = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("sk-test-1234567890", text)
        self.assertTrue(state["config"]["has_key"])
        self.assertEqual(state["config"]["key_masked"][:3], "sk-")
        self.assertFalse(state["debug"])

    def test_connection(self):
        status, data = request(self.base + "/api/test-connection", "POST", {})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["models"], ["deepseek-flash"])

    def test_generate_template_and_grade(self):
        status, data = self._generate(web_search=True)
        self.assertEqual(status, 200, data)
        test = data["test"]
        self.assertEqual(test["template"], "A")
        self.assertEqual(test["question_count"], 30)
        self.assertEqual(test["total_score"], 30)
        self.assertEqual(len(test["sections"]), 5)
        self.assertEqual([len(s["questions"]) for s in test["sections"]], [5, 5, 10, 5, 5])
        self.assertEqual(test["sections"][0]["type"], "word_choice")
        self.assertEqual(len(test["sections"][0]["questions"][0]["options"]), 3)
        self.assertEqual(len(test["sections"][1]["questions"][0]["options"]), 3)
        self.assertEqual(test["sections"][4]["table"]["rows"][0]["number"], 26)
        self.assertEqual(test["sections"][4]["questions"][0]["type"], "fill")
        self.assertNotIn('"answer"', json.dumps(test, ensure_ascii=False))
        self.assertNotIn('"explanation"', json.dumps(test, ensure_ascii=False))
        self.assertNotIn('"audio_text"', json.dumps(test, ensure_ascii=False))
        self.assertEqual(data["meta"]["search_count"], 1)
        self.assertEqual(test["search_sources"][0]["url"], "https://example.com/unit1")
        self.assertTrue(any(path.endswith("/tools/search") for path, _ in MockDeepSeek.calls))
        self.assertTrue(any(path.endswith("/chat/completions") for path, _ in MockDeepSeek.calls))

        full = get_sample()
        answers = {q["id"]: (q["answer"] if q["type"] == "choice" else q["answer_text"]) for q in (q for s in full["sections"] for q in s["questions"])}
        status, result = request(self.base + "/api/grade", "POST", {"test_id": test["id"], "answers": answers})
        self.assertEqual(status, 200)
        self.assertEqual(result["score"], 30)
        self.assertEqual(result["percent"], 100)
        self.assertEqual(len(result["sections"]), 5)
        self.assertIn("Two boys", result["sections"][0]["materials"][0]["transcript"])

    def test_partial_grade_and_fill(self):
        status, data = self._generate()
        self.assertEqual(status, 200, data)
        test = data["test"]
        status, result = request(self.base + "/api/grade", "POST", {
            "test_id": test["id"],
            "answers": {"q1": 1, "q26": " SIX "},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["total"], 30)
        fill = next(item for item in result["details"] if item["id"] == "q26")
        self.assertEqual(fill["answer"], "six")
        self.assertTrue(fill["correct"])

    def test_invalid_unit(self):
        status, data = self._generate(unit_id="not-a-unit")
        self.assertEqual(status, 400)
        self.assertIn("有效的年级", data["error"]["message"])

    def test_history_and_no_sample_route(self):
        status, data = self._generate()
        self.assertEqual(status, 200, data)
        status, history = request(self.base + "/api/history")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(history["items"]), 1)
        self.assertEqual(history["items"][0]["question_count"], 30)
        status, _ = request(self.base + "/api/sample")
        self.assertEqual(status, 404)

    def test_clear_key(self):
        status, data = request(self.base + "/api/config", "POST", {"clear_key": True})
        self.assertEqual(status, 200)
        self.assertFalse(data["state"]["config"]["has_key"])
        self.assertEqual(data["state"]["config"]["key_masked"], "")

    def test_debug_flag(self):
        tmp = tempfile.mkdtemp(prefix="echostep-debug-")
        server, app = create_server(port=0, data_dir=Path(tmp), debug=True)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, state = request(f"http://127.0.0.1:{port}/api/state")
            self.assertEqual(status, 200)
            self.assertTrue(state["debug"])
        finally:
            server.shutdown()
            server.server_close()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
