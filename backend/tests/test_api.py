from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import extract
import utils
from app import app

FIXTURE = Path(__file__).parent / "fixtures" / "url-20260718-210133.html"


class AnalyzeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_url_request_returns_entry_array(self) -> None:
        expected = [{"decision_id": "kyoku-0-0-000", "kyoku": "East 1"}]
        with patch("app.utils.run_analysis", return_value={"entries": expected}) as run_analysis:
            response = self.client.post(
                "/api/v1/analyze",
                json={
                    "seat": 2,
                    "source": {"type": "url", "data": "https://example.test/replay"},
                    "kyokus": ["kyoku-0-0", "kyoku-1-0"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        run_analysis.assert_called_once_with(
            source_type="url",
            seat=2,
            url="https://example.test/replay",
            json_body=None,
            kyokus=["kyoku-0-0", "kyoku-1-0"],
        )

    def test_rejects_invalid_kyokus(self) -> None:
        response = self.client.post(
            "/api/v1/analyze",
            json={"seat": 0, "source": {"type": "url", "data": "https://example.test"}, "kyokus": []},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "kyokus must be a non-empty array when specified")

    def test_accepts_embedded_replay_json(self) -> None:
        with patch("app.utils.run_analysis", return_value={"entries": []}) as run_analysis:
            response = self.client.post(
                "/api/v1/analyze",
                json={"seat": 1, "source": {"type": "json", "data": {"log": []}}},
            )

        self.assertEqual(response.status_code, 200)
        call = run_analysis.call_args.kwargs
        self.assertEqual(call["source_type"], "json")
        self.assertEqual(call["seat"], 1)
        self.assertIn(b'"log": []', call["json_body"])

    def test_frontend_json_contains_complete_decision_state(self) -> None:
        entry = extract.extract_entries(str(FIXTURE))[7]
        entry["commentary"] = None
        output = utils.to_json_entry(entry)

        self.assertEqual(
            {
                "decision_id",
                "kyoku",
                "kyoku_id",
                "turn",
                "wall_remaining",
                "state_available",
                "dora_indicator",
                "dora_indicators",
                "scores",
                "hand",
                "draw",
                "melds",
                "rivers",
                "riichi",
                "tehai",
                "player_discard",
                "player_ev",
                "player_deal_in",
                "ai_discard",
                "ai_ev",
                "ai_deal_in",
                "loss",
                "commentary",
            },
            set(output),
        )
        self.assertEqual(output["wall_remaining"], 44)
        self.assertEqual(output["dora_indicator"], "7s")
        self.assertEqual(output["player_deal_in"], 2.74)

    def test_analysis_filters_multiple_requested_rounds(self) -> None:
        report_html = FIXTURE.read_text(encoding="utf-8")
        with (
            patch("utils.interactakochan.call_report", return_value=report_html),
            patch("utils.interactllm._generate_advice", return_value="test advice"),
        ):
            data = utils.run_analysis(
                source_type="url",
                seat=2,
                url="https://example.test/replay",
                kyokus=["kyoku-1-2", "kyoku-0-1"],
            )

        self.assertEqual(len(data["entries"]), 6)
        self.assertEqual(
            [entry["kyoku_id"] for entry in data["entries"]],
            ["kyoku-1-2"] * 3 + ["kyoku-0-1"] * 3,
        )


if __name__ == "__main__":
    unittest.main()
