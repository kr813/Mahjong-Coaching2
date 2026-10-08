from __future__ import annotations

import unittest
from pathlib import Path

import extract
import tenhou_state

FIXTURE = Path(__file__).parent / "fixtures" / "url-20260718-210133.html"


class TileDecoderTests(unittest.TestCase):
    def test_decodes_normal_honor_and_red_tiles(self) -> None:
        self.assertEqual(tenhou_state.decode_tile(14), "4m")
        self.assertEqual(tenhou_state.decode_tile(37), "7s")
        self.assertEqual(tenhou_state.decode_tile(41), "e")
        self.assertEqual(tenhou_state.decode_tile(52), "5pr")
        self.assertIsNone(tenhou_state.decode_tile(60))


class AkochanReportExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = extract.extract_entries(str(FIXTURE))

    def test_all_decisions_receive_unique_ids_and_replayed_state(self) -> None:
        self.assertEqual(len(self.entries), 63)
        self.assertEqual(len({entry["decision_id"] for entry in self.entries}), 63)
        self.assertTrue(all(entry["state_available"] for entry in self.entries))

    def test_extracts_complete_state_for_east_one_turn_eight(self) -> None:
        entry = next(
            entry
            for entry in self.entries
            if entry["kyoku_id"] == "kyoku-0-0" and entry["turn"] == 8
        )

        self.assertEqual(entry["wall_remaining"], 44)
        self.assertEqual(entry["dora_indicators"], ["7s"])
        self.assertEqual(entry["scores"], [25000, 25000, 25000, 25000])
        self.assertEqual(entry["hand"], ["2p", "4p", "6p", "6s", "7s", "s", "s"])
        self.assertEqual(entry["tsumo"], "4m")
        self.assertEqual(
            entry["melds"],
            [
                {"type": "pon", "tile": "p", "tiles": ["p", "p", "p"], "from": "対面"},
                {"type": "chi", "tile": "2m", "tiles": ["2m", "1m", "3m"], "from": "上家"},
            ],
        )
        self.assertEqual(entry["rivers"]["self"], ["8m", "3s", "w", "e", "1m", "2p"])
        self.assertEqual(entry["riichi"], [False, False, False, False])
        self.assertEqual(entry["player_discard"], "4m")
        self.assertAlmostEqual(entry["player_ev"], -2.68720)
        self.assertAlmostEqual(entry["player_deal_in"], 2.74247)
        self.assertEqual(entry["ai_discard"], "4m")
        self.assertAlmostEqual(entry["ai_ev"], -2.68720)
        self.assertAlmostEqual(entry["ai_deal_in"], 2.74247)
        self.assertAlmostEqual(entry["loss"], 0.0)

    def test_replays_open_kan_and_additional_dora(self) -> None:
        entry = next(
            entry
            for entry in self.entries
            if entry["decision_id"] == "kyoku-0-2-008"
        )
        self.assertEqual(entry["dora_indicators"], ["9p", "3s"])
        self.assertIn(
            {"type": "kan", "tile": "w", "tiles": ["w", "w", "w", "w"], "from": "下家"},
            entry["melds"],
        )

    def test_replays_riichi_and_live_scores(self) -> None:
        entry = next(
            entry
            for entry in self.entries
            if entry["decision_id"] == "kyoku-1-2-002"
        )
        self.assertEqual(entry["riichi"], [False, False, True, False])
        self.assertEqual(entry["scores"], [52600, 39000, 6400, 1000])


if __name__ == "__main__":
    unittest.main()
