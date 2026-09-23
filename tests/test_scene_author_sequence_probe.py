"""Frozen sequence probe must retain original Scene IDs and timestamps."""

import json
from pathlib import Path
import unittest

from core.planner.template import parse_template_emd
from core.planner.scene_author import _split_terminal_state
from tools.offline_scene_author_sequence_probe import scene_prefix


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/assets/research/scene-composition-full-sequence-2026-09-23"


class SceneAuthorSequenceProbeTests(unittest.TestCase):
    def test_frozen_prefix_retains_original_scene_numbers_and_times(self):
        source = (FIXTURE / "template.md").read_text(encoding="utf-8")
        prefix = scene_prefix(source, 4)
        parsed = parse_template_emd(prefix)
        self.assertEqual([scene.scene_number for scene in parsed.scenes], [1, 2, 3, 4])
        self.assertEqual(parsed.scenes[0].start_ms, 0)
        self.assertEqual(parsed.scenes[3].end_ms, 39167)
        self.assertTrue(all(scene.continuation for scene in parsed.scenes[1:]))
        self.assertEqual(scene_prefix(source, 16), source)

    def test_rejects_out_of_range_scene_count(self):
        source = (FIXTURE / "template.md").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            scene_prefix(source, 0)
        with self.assertRaises(ValueError):
            scene_prefix(source, 17)

    def test_real_eight_b_terminal_variants_do_not_leak_into_emd_prose(self):
        evidence = FIXTURE / "terminal-state-full-seed2/summary.json"
        summary = json.loads(evidence.read_text(encoding="utf-8"))
        covered = 0
        for call in summary["trace"]:
            for line in call["response"].splitlines():
                if "END_STATE" not in line or "\t" not in line:
                    continue
                prose, state = _split_terminal_state(line.split("\t", 2)[-1])
                self.assertNotIn("END_STATE", prose, line)
                self.assertTrue(state, line)
                covered += 1
        self.assertGreaterEqual(covered, 10)


if __name__ == "__main__":
    unittest.main()
