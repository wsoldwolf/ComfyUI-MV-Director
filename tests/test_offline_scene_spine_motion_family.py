import unittest

from tools.offline_scene_spine_motion_family import SCENES, request_for_scene


class SceneSpineMotionFamilyProbeTests(unittest.TestCase):
    def test_only_guided_variant_has_family(self):
        baseline = request_for_scene(SCENES[0], guided=False)
        guided = request_for_scene(SCENES[0], guided=True)
        self.assertNotIn("suggested_motion_family", baseline)
        self.assertEqual(guided["suggested_motion_family"], SCENES[0]["motion_family"])
        self.assertEqual(baseline["slots"], guided["slots"])
        self.assertEqual(baseline["lyric_lines"], guided["lyric_lines"])

    def test_unlock_removes_only_body_decisions(self):
        baseline = request_for_scene(SCENES[0])
        unlocked = request_for_scene(SCENES[0], unlock_body=True)
        self.assertEqual(unlocked["visual_beat_grounding"]["body_driver"], "")
        self.assertEqual(unlocked["visual_beat_grounding"]["final_state"], "")
        for key in ("target", "evidence", "contact", "emotion", "spatial_anchor"):
            self.assertEqual(
                baseline["visual_beat_grounding"][key],
                unlocked["visual_beat_grounding"][key],
            )
        self.assertEqual(baseline["slots"], unlocked["slots"])


if __name__ == "__main__":
    unittest.main()
