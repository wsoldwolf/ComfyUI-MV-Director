import unittest
from copy import deepcopy
from types import SimpleNamespace

from tools.debug_instrumental_full import assert_full_content, verify_plan, USER_REQUEST
from core.direction.enhancer import split_staging_directives


class InstrumentalFullProbeTests(unittest.TestCase):
    def test_requires_every_generated_kind_for_every_shot(self):
        template = SimpleNamespace(shot_keys=((1, 1), (2, 1)))
        content = SimpleNamespace(events=((1, 1, "水。"), (2, 1, "葉。")),
            actions=((1, 1, "舞う。"), (2, 1, "歌う。")),
            cameras=((1, 1, "Arc。"), (2, 1, "接近。")), motion_compositions=())
        assert_full_content(content, template)
        for rows in ((), ((1, 1, "水。"),)):
            valid = deepcopy(content)
            valid.events = rows
            assert_full_content(valid, template)
        for kind, rows in (("events", ((1, 1, "水。"), (1, 1, "葉。"))),
                           ("events", ((3, 1, "水。"),)),
                           ("events", ((1, 1, "検証対象外。"),)),
                           ("actions", ((1, 1, "舞う。"),)),
                           ("actions", ((1, 1, "舞う。"), (2, 1, "検証対象外。"))),
                           ("cameras", ((1, 1, "Arc。"), (1, 1, "接近。"))),
                           ("motion_compositions", ((1, 1, "補完"),))):
            invalid = deepcopy(content)
            setattr(invalid, kind, rows)
            with self.assertRaises(ValueError):
                assert_full_content(invalid, template)

    def test_full_pcm_clock_and_locked_vocal(self):
        template = SimpleNamespace(scenes=(
            SimpleNamespace(scene_number=1, h3_length=243, continuation=False, end_ms=10125),
            SimpleNamespace(scene_number=2, h3_length=243, continuation=True, end_ms=19333)))
        plan = {"shots": [{"id": "scene_0001", "length": 243, "context_length": 0,
            "audio_context_length": 0, "source_audio_target": "locked", "prompt": ["Shot"]},
            {"id": "scene_0002", "length": 243, "context_length": 22,
            "audio_context_length": 22, "source_audio_target": "locked", "prompt": ["Shot"]}]}
        self.assertEqual(verify_plan(plan, template), 464)
        for key, value in (("context_length", 0), ("source_audio_target", "off"),
                           ("prompt", ["検証対象外。"]), ("length", 244)):
            invalid = deepcopy(plan)
            invalid["shots"][1][key] = value
            with self.assertRaises(ValueError):
                verify_plan(invalid, template)

    def test_only_optional_candidates_not_global_orders(self):
        common, candidates = split_staging_directives(USER_REQUEST)
        self.assertFalse(common)
        self.assertEqual(len(candidates), 4)
        self.assertIn("長い伴奏", candidates[0])
        self.assertIn("Camera", candidates[1])


if __name__ == "__main__":
    unittest.main()
