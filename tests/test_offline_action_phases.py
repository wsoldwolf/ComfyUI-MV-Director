"""The phase comparison has identical source inputs for both prompt variants."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.offline_action_phases import model_request, prompts


class OfflineActionPhaseTests(unittest.TestCase):
    def test_variants_change_only_the_long_shot_instruction(self):
        variants = prompts()
        self.assertNotEqual(variants["baseline"], variants["multi_phase"])
        self.assertIn("4秒以上の通常Shot", variants["multi_phase"])
        self.assertLess(len(variants["minimal"]), len(variants["baseline"]))

    def test_original_action_never_enters_request(self):
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads((root /
            "tests/fixtures/research/scene-body-chain-2026-09-22/fixture.json"
        ).read_text(encoding="utf-8"))
        request = model_request(fixture)
        serialized = json.dumps(request, ensure_ascii=False)
        for shot in fixture["scenes"][0]["shots"]:
            self.assertNotIn(shot["original_action"], serialized)
        self.assertEqual(len(request["slots"]), 2)
        compact = model_request(fixture, motion_mode="compact")
        self.assertEqual(compact["slots"], request["slots"])
        self.assertNotEqual(compact["direction"]["motion"], request["direction"]["motion"])
        phases = model_request(fixture, slot_layout="phase")
        self.assertEqual(len(phases["slots"]), 4)
        self.assertEqual(
            [slot["phase_in_shot"] for slot in phases["slots"]],
            ["prepare", "accent", "continue", "resolve"],
        )


if __name__ == "__main__":
    unittest.main()
