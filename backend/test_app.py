import unittest
from unittest.mock import patch
from pathlib import Path
import sys

# backend ディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import app


class MahjongCoachingBackendTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.sample_html_path = Path(__file__).resolve().parent / "source" / "test_report.html"

    def test_invalid_seat(self):
        res = self.client.post("/analyze?seat=5")
        self.assertEqual(res.status_code, 400)

    def test_empty_request(self):
        res = self.client.post("/analyze")
        self.assertEqual(res.status_code, 400)

    def test_index_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("麻雀 AI牌譜添削ツール", res.get_data(as_text=True))

    def test_successful_analysis_json_format(self):
        if not self.sample_html_path.exists():
            self.skipTest("Sample report.html not found")

        with open(self.sample_html_path, "r", encoding="utf-8") as f:
            sample_html = f.read()

        with patch("interactakochan.call_report", return_value=sample_html), \
             patch("interactllm._generate_advice", return_value="【AIアドバイス】リーチ判断が優れています。"):
            # API エンドポイント /api/analyze で JSON を取得
            res = self.client.post("/api/analyze", data={
                "input_data": "https://tenhou.net/0/?log=test",
                "seat": "0"
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)

            # JSONスキーマ検証（ai-input-format仕様）
            first = data[0]
            required_keys = ["meta", "situation", "self", "others", "hidden_info", "decision", "commentary"]
            for key in required_keys:
                self.assertIn(key, first)

            self.assertIn("kyoku", first["meta"])
            self.assertIn("turn", first["situation"])
            self.assertIn("hand_with_trigger_tile", first["self"])
            self.assertIn("shimocha", first["others"])
            self.assertIn("hands", first["hidden_info"])
            self.assertIn("player_choice", first["decision"])
            self.assertIn("ai_choice", first["decision"])
            self.assertIn("candidates", first["decision"])

    def test_successful_analysis_html_format(self):
        if not self.sample_html_path.exists():
            self.skipTest("Sample report.html not found")

        with open(self.sample_html_path, "r", encoding="utf-8") as f:
            sample_html = f.read()

        with patch("interactakochan.call_report", return_value=sample_html), \
             patch("interactllm._generate_advice", return_value="【AIアドバイス】リーチ判断が優れています。"):
            # ブラウザアクセス (Accept: text/html) で /analyze にリクエスト
            res = self.client.post(
                "/analyze",
                data={
                    "input_data": "https://tenhou.net/0/?log=test",
                    "seat": "0"
                },
                headers={"Accept": "text/html"}
            )
            self.assertEqual(res.status_code, 200)
            html_text = res.get_data(as_text=True)
            self.assertIn("牌譜検討", html_text)
            self.assertIn("東1局", html_text)
            self.assertIn("AIからのアドバイス", html_text)


if __name__ == "__main__":
    unittest.main()
