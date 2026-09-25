"""The completed-phrase probe must preserve the original lyric transport."""

import json
from pathlib import Path
import unittest

from tools.offline_shot_linkage_p1_phrase_probe import completed_phrase_cases


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = (
    ROOT / "tests/fixtures/research/scene-composition-full-sequence-2026-09-23"
    / "p1b-six-scenes-seed2-v2/summary.json"
)


class CompletedPhraseProbeTests(unittest.TestCase):
    def test_only_completed_phrase_field_changes(self):
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        cases = completed_phrase_cases(
            summary, scene_number=4, shot_number=2,
            source_lines=("人は花より", "短く咲いて"),
        )
        self.assertEqual([name for name, _ in cases], ["empty", "joined", "text_only"])
        empty, joined, text_only = (case[1] for case in cases)
        self.assertEqual(empty["completed_lyric_phrase"], [])
        self.assertEqual(joined["completed_lyric_phrase"], [{
            "shot": 2,
            "source_lines": ["人は花より", "短く咲いて"],
            "text": "人は花より短く咲いて",
        }])
        self.assertEqual(text_only["completed_lyric_phrase"], [
            {"text": "人は花より短く咲いて"},
        ])
        self.assertEqual(
            {key: value for key, value in empty.items()
             if key != "completed_lyric_phrase"},
            {key: value for key, value in joined.items()
             if key != "completed_lyric_phrase"},
        )
        self.assertEqual(
            {key: value for key, value in empty.items()
             if key != "completed_lyric_phrase"},
            {key: value for key, value in text_only.items()
             if key != "completed_lyric_phrase"},
        )

    def test_cross_shot_or_non_contiguous_phrase_rejected(self):
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            completed_phrase_cases(
                summary, scene_number=4, shot_number=1,
                source_lines=("人は花より", "短く咲いて"),
            )
        with self.assertRaises(ValueError):
            completed_phrase_cases(
                summary, scene_number=4, shot_number=2,
                source_lines=("わらわだけ", "短く咲いて"),
            )


if __name__ == "__main__":
    unittest.main()
