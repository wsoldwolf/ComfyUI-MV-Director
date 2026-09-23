"""CPU-only checks for the saved-trace pre-Cue experiment."""

import json
import unittest

from tools.offline_motion_template_pre_cue_probe import (
    SOURCE, _parse_cues, _parse_spine, _saved_requests,
)


class MotionTemplatePreCueProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(SOURCE.read_text(encoding="utf-8"))

    def test_saved_cue_batches_cover_both_target_scenes(self) -> None:
        requests = _saved_requests(self.source["trace"], "visual-beats")
        self.assertEqual(set(requests), {11, 14})
        for scene, entry in requests.items():
            payload = json.loads(entry["payload"])
            self.assertIn(scene, {slot["scene_number"] for slot in payload["slots"]})
            parsed = _parse_cues(entry["response"], payload)
            self.assertTrue(parsed["valid"])
            self.assertIn(str(scene), parsed["cards"])

    def test_saved_spines_parse_with_current_contract(self) -> None:
        requests = _saved_requests(self.source["trace"], "scene-spine")
        self.assertEqual(set(requests), {11, 14})
        for entry in requests.values():
            payload = json.loads(entry["payload"])
            parsed = _parse_spine(entry["response"], payload)
            self.assertTrue(parsed["valid"], parsed)


if __name__ == "__main__":
    unittest.main()
