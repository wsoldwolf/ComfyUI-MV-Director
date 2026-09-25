"""The P1 counterfactual must alter only optional staging candidates."""

import json
from pathlib import Path
import unittest

from tools.offline_shot_linkage_p1_probe import candidate_off_cases


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = (
    ROOT / "tests/fixtures/research/scene-composition-full-sequence-2026-09-23"
    / "no-previous-state-full-seed2/summary.json"
)


class CandidateOffProbeTests(unittest.TestCase):
    def test_only_candidate_list_changes(self):
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        cases = candidate_off_cases(summary, (3, 9))
        self.assertEqual([case["scene"] for case in cases], [3, 9])
        for case in cases:
            original = case["baseline_payload"]
            changed = case["candidate_off_payload"]
            self.assertGreater(case["candidate_count"], 0)
            self.assertEqual(changed["staging_candidates_optional"], [])
            self.assertEqual(
                {key: value for key, value in original.items()
                 if key != "staging_candidates_optional"},
                {key: value for key, value in changed.items()
                 if key != "staging_candidates_optional"},
            )
            self.assertNotEqual(
                case["baseline_payload_sha256"],
                case["candidate_off_payload_sha256"],
            )

    def test_missing_scene_rejected(self):
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            candidate_off_cases(summary, (99,))


if __name__ == "__main__":
    unittest.main()
