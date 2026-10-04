import unittest
from copy import deepcopy

from core.lyrics import format_emd_time
from tools.debug_momentum_pipeline import production_inputs
from tools.debug_instrumental_camera_candidate import USER_REQUEST, verify_candidate_plan


class InstrumentalCameraCandidateTests(unittest.TestCase):
    def test_only_camera_slots_reopened(self):
        text = "# サブジェクト\n* `画像1` 人物。\n\n# シーン設定\n## 環境\n* 滝。\n\n# 共通プロンプト\n## モーション\n* 既存の身体演技。\n"
        for n in range(1, 14):
            start, end = format_emd_time((n-1)*10125), format_emd_time(n*10125)
            continued = " 継続" if n > 11 else ""
            text += (f"\n> `シーン` {n}\n# シーン {start} --> {end}{continued}\n"
                     f"* `H3長` 243\n## ショット {start}\n"
                     "* `演出` 水しぶき。\n* `カメラ` 旧Camera。\n* `演技` 既存演技。\n")
        template, direction, _, _ = production_inputs(text, USER_REQUEST, target_scenes=(11, 12),
                                                     preserve_continuation=True, target_kind="カメラ")
        self.assertEqual(len(direction.staging_candidates), 1)
        self.assertEqual(direction.motion_templates, ())
        for scene in template.scenes:
            kinds = [d.kind for d in scene.shots[0].directives]
            self.assertEqual(kinds, ["演出", "演技"] if scene.scene_number in (11, 12)
                             else ["演出", "カメラ", "演技"])
        self.assertTrue(template.scenes[11].continuation)
        with self.assertRaises(ValueError):
            production_inputs(text, USER_REQUEST, target_kind="演出")

    def test_guard_allows_only_camera_and_renderer_order(self):
        baseline = {"fps": 24, "shots": [
            {"prompt": ["Event Camera0 Body0"], "seed": 1},
            {"prompt": ["Event Camera1 Body1"], "seed": 2},
            {"prompt": ["Singing return"], "seed": 3}]}
        candidate = deepcopy(baseline)
        candidate["shots"][0]["prompt"] = ["Event Body0 New0"]
        candidate["shots"][1]["prompt"] = ["Event Body1 New1"]
        args = (["Camera0", "Camera1"], ["Body0", "Body1"], ["New0", "New1"])
        verify_candidate_plan(baseline, candidate, *args)
        for index, key, value in ((0, "seed", 8), (1, "prompt", ["Event OtherBody New1"]),
                                  (2, "prompt", ["Changed singing return"]),
                                  (0, "prompt", ["ChangedEvent Body0 New0"])):
            invalid = deepcopy(candidate)
            invalid["shots"][index][key] = value
            with self.assertRaises(ValueError):
                verify_candidate_plan(baseline, invalid, *args)


if __name__ == "__main__":
    unittest.main()
