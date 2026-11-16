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

            # 打牌行動における acceptance (受け入れ情報) スキーマ検証
            pl_choice = first["decision"]["player_choice"]
            ai_choice = first["decision"]["ai_choice"]
            if pl_choice.get("type") == "discard":
                self.assertIn("acceptance", pl_choice)
                acc = pl_choice["acceptance"]
                self.assertIsNotNone(acc)
                self.assertIn("shanten", acc)
                self.assertIn("shanten_desc", acc)
                self.assertIn("tiles", acc)
                self.assertIn("remaining_count", acc)
                self.assertIn("max_count", acc)
                self.assertIsInstance(acc["shanten"], int)
                self.assertIsInstance(acc["tiles"], list)
                self.assertIsInstance(acc["remaining_count"], int)
                self.assertIsInstance(acc["max_count"], int)
            if ai_choice.get("type") == "discard":
                self.assertIn("acceptance", ai_choice)
                self.assertIsNotNone(ai_choice["acceptance"])

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
            self.assertIn("マークの見方:", html_text)
            self.assertIn("AIからのアドバイス（ワースト1）:", html_text)

    def test_player_action_not_in_candidates_does_not_400(self):
        if not self.sample_html_path.exists():
            self.skipTest("Sample report.html not found")

        with open(self.sample_html_path, "r", encoding="utf-8") as f:
            sample_html = f.read()

        # 候補表からプレイヤーの実際の打牌行(pai-w)を別の牌(pai-9p)に書き換え、候補外にする
        modified_html = sample_html.replace(
            "<tr><td>Discard <svg class=tile><use class=face href=#pai-w></use></svg><td>",
            "<tr><td>Discard <svg class=tile><use class=face href=#pai-9p></use></svg><td>",
            1
        )

        with patch("interactakochan.call_report", return_value=modified_html), \
             patch("interactllm._generate_advice", return_value="【AIアドバイス】テスト"):
            res = self.client.post(
                "/analyze",
                data={"input_data": "https://tenhou.net/0/?log=test", "seat": "0"},
                headers={"Accept": "text/html"}
            )
            self.assertEqual(res.status_code, 200)
            html_text = res.get_data(as_text=True)
            self.assertIn("期待値差を算出できませんでした", html_text)

    def test_invalid_text_input_returns_400(self):
        res = self.client.post(
            "/analyze",
            data={"input_data": "not_a_url_and_not_json", "seat": "0"},
            headers={"Accept": "text/html"}
        )
        self.assertEqual(res.status_code, 400)

    def test_shanten_calculator_logic(self):
        import shanten_calculator as sc

        # テンパイ手牌 (待ち: 3s)
        hand_tenpai = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "1p", "1p", "2s", "4s"]
        res = sc.calculate_acceptance(hand_tenpai, meld_count=0, visible_tiles=["3s"])
        self.assertEqual(res["shanten"], 0)
        self.assertEqual(res["shanten_desc"], "テンパイ")
        self.assertIn("3s", res["tiles"])
        self.assertEqual(res["max_count"], 4)
        self.assertEqual(res["remaining_count"], 3)

        # 一向聴手牌
        hand_1shanten = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "1p", "1p", "2s", "4s", "9p"]
        res_1s = sc.calculate_acceptance(hand_1shanten, meld_count=0)
        self.assertEqual(res_1s["shanten"], 1)
        self.assertEqual(res_1s["shanten_desc"], "一向聴")
        self.assertTrue(set(["3s", "6s", "9s"]).issubset(set(res_1s["tiles"])))

        # compute_choice_acceptance テスト
        full_hand = hand_tenpai + ["9s"]
        choice = {"type": "discard", "tile": "9s"}
        acc = sc.compute_choice_acceptance(choice, full_hand, melds=[], visible_tiles=["3s", "3s"])
        self.assertIsNotNone(acc)
        self.assertEqual(acc["shanten"], 0)
        self.assertEqual(acc["remaining_count"], 2)


if __name__ == "__main__":
    unittest.main()
