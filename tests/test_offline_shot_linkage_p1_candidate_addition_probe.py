"""The added user-style cue must be the sole P1 counterfactual change."""

import json
from pathlib import Path
import unittest

from tools.offline_shot_linkage_p1_candidate_addition_probe import candidate_addition_cases


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "tests/fixtures/research/scene-composition-full-sequence-2026-09-23"
    / "p1b-six-scenes-seed2-v2/summary.json"
)
CANDIDATE = (
    ROOT / "tests/fixtures/research/shot-linkage-p1-2026-09-24"
    / "flower-staging-candidate.txt"
)


class CandidateAdditionProbeTests(unittest.TestCase):
    def test_only_appends_one_candidate(self):
        summary = json.loads(SOURCE.read_text(encoding="utf-8"))
        text = CANDIDATE.read_text(encoding="utf-8").strip()
        baseline, added, only_flower = candidate_addition_cases(
            summary, scene_number=4, candidate=text,
        )
        self.assertEqual((baseline[0], added[0], only_flower[0]),
                         ("baseline", "added", "only_flower"))
        before, after = baseline[1], added[1]
        self.assertEqual(only_flower[1]["staging_candidates_optional"], [text])
        self.assertEqual(len(after["staging_candidates_optional"]), 8)
        self.assertEqual(
            after["staging_candidates_optional"],
            [*before["staging_candidates_optional"], text],
        )
        self.assertEqual(
            {key: value for key, value in before.items()
             if key != "staging_candidates_optional"},
            {key: value for key, value in after.items()
             if key != "staging_candidates_optional"},
        )

    def test_duplicate_candidate_rejected(self):
        summary = json.loads(SOURCE.read_text(encoding="utf-8"))
        original = json.loads(next(
            row["payload"] for row in summary["trace"]
            if row["task"] == "scene-author-event"
            and json.loads(row["payload"])["scene_number"] == 4
        ))
        with self.assertRaises(ValueError):
            candidate_addition_cases(
                summary, scene_number=4,
                candidate=original["staging_candidates_optional"][0],
            )


if __name__ == "__main__":
    unittest.main()
