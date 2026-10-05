import unittest
from tools.prepare_beat_motion_h3 import fresh_plan, replace_scene_prose, verify_subject_only
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE


class BeatH3ProbeTests(unittest.TestCase):
    def test_only_target_scene_prose_changes(self):
        text = ('> `シーン` 10\n* `演技` previous\n* `カメラ` old\n'
                '> `シーン` 11\n* `演技` chosen\n* `カメラ` target\n'
                '> `シーン` 12\n* `演技` next\n* `カメラ` next\n')
        updated = replace_scene_prose(text, "new", "newcam")
        self.assertEqual(updated, text.replace('`演技` chosen', '`演技` new').replace('`カメラ` target', '`カメラ` newcam'))

    def test_missing_or_multiple_fields_rejected(self):
        for text in ('> `シーン` 12\n', '> `シーン` 11\n* `演技` a\n* `演技` b\n* `カメラ` c\n'):
            with self.assertRaises(ValueError):
                replace_scene_prose(text, "new", "cam")

    def test_fresh_plan_does_not_mutate_full_song(self):
        plan = {"shots": [{"length": 260, "context_length": 22, "audio_context_length": 22,
                            "prompt": [str(i)]} for i in range(11)], "mv_director_audio_activity": {"old": True},
                "prompt_prefix": ["fixed"]}
        updated = fresh_plan(plan, 243)
        self.assertEqual(len(updated["shots"]), 1)
        self.assertEqual(updated["shots"][0]["prompt"], ["10"])
        self.assertEqual(updated["shots"][0]["context_length"], 0)
        self.assertEqual(updated["shots"][0]["audio_context_length"], 0)
        self.assertNotIn("mv_director_audio_activity", updated)
        self.assertEqual(plan["shots"][10]["context_length"], 22)
        self.assertIn("mv_director_audio_activity", plan)

    def test_first_scene_clock_requires_only_five_tail_frames(self):
        self.assertEqual(DEFAULT_H3_TIMING_PROFILE.quantize_delivered_frames(238, first_scene=True), (243, 243, 0))

    def test_subject_repair_preserves_body_and_globals(self):
        before = {"shots": [{"prompt": ["Subject old costume", "action"], "seed": 1}], "prefix": "fixed"}
        after = {"shots": [{"prompt": ["Subject new costume", "action"], "seed": 1}], "prefix": "fixed"}
        verify_subject_only(before, after, "old costume", "new costume")
        after["shots"][0]["seed"] = 2
        with self.assertRaises(ValueError):
            verify_subject_only(before, after, "old costume", "new costume")


if __name__ == "__main__":
    unittest.main()
