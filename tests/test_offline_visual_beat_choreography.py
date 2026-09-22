"""The Visual Beat comparison keeps outputs out of its fixed model request."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.offline_visual_beat_choreography import model_request, parse_response


class OfflineVisualBeatChoreographyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / (
            "docs/assets/research/visual-beat-choreography-2026-09-22/fixture.json"
        )
        self.fixture = json.loads(path.read_text(encoding="utf-8"))

    def test_fixed_request_has_source_lyrics_but_no_cached_outputs(self):
        request = model_request(self.fixture)
        self.assertEqual([slot["scene_number"] for slot in request["slots"]], [11, 12])
        self.assertEqual(request["planner_policy_contract"]["performance_mode"], "dance_phrase")
        serialized = json.dumps(request, ensure_ascii=False)
        for secret in ("身体主導=", "終端=", "右足を鳥居の上に置く"):
            self.assertNotIn(secret, serialized)

    def test_line_protocol_records_are_not_rewritten(self):
        raw = "BEAT\t1\t甲\nBEAT\t2\t乙\n"
        parsed = parse_response(raw, self.fixture["slots"])
        self.assertEqual([row["text"] for row in parsed["records"]], ["甲", "乙"])
        self.assertEqual(parsed["missing"], [])

    def test_compact_motion_changes_only_direction_motion(self):
        full = model_request(self.fixture)
        compact = model_request(self.fixture, motion_mode="compact")
        self.assertEqual(full["slots"], compact["slots"])
        self.assertEqual(full["planner_policy_contract"], compact["planner_policy_contract"])
        self.assertNotEqual(full["direction"]["motion"], compact["direction"]["motion"])


if __name__ == "__main__":
    unittest.main()
