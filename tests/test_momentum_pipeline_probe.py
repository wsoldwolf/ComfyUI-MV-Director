import unittest
from copy import deepcopy

from tools.debug_momentum_pipeline import production_inputs, verify_single_body_plan, USER_REQUEST, SPEED_REQUEST
from tools.debug_simple_dance import MOMENTUM_ENGLISH
from core.lyrics import format_emd_time


EMD = """# サブジェクト
* `画像1` 袴を着て剣を持つ人物。

# シーン設定
## 環境
* 滝と紅葉。

# 共通プロンプト
## モーション
* 身体演技を行う。

"""
for scene in range(1, 12):
    start, end = format_emd_time((scene - 1) * 10125), format_emd_time(scene * 10125)
    EMD += (f"\n> `シーン` {scene}\n# シーン {start} --> {end}\n* `H3長` 243\n"
            f"## ショット {start}\n* `演出` 紅葉が舞う。\n* `演技` 旧演技。\n* `カメラ` 正面から引く。\n")


class MomentumPipelineProbeTests(unittest.TestCase):
    def test_only_performance_opened_and_candidate_filtered(self):
        template, direction, _, _ = production_inputs(EMD, USER_REQUEST)
        shot = template.scenes[10].shots[0]
        self.assertEqual([d.kind for d in shot.directives], ["演出", "カメラ"])
        self.assertEqual(shot.body, ("`演出` 紅葉が舞う。", "`カメラ` 正面から引く。"))
        self.assertEqual(len(direction.staging_candidates), 1)
        self.assertTrue(direction.staging_candidates[0].startswith("歌詞のない伴奏"))
        self.assertEqual(direction.motion_templates, ())

    def test_extra_common_conditions_rejected(self):
        with self.assertRaises(ValueError):
            production_inputs(EMD, "# 共通プロンプト\n* 新条件\n\n" + USER_REQUEST)

    def test_speed_is_one_sentence_in_same_candidate(self):
        self.assertTrue(SPEED_REQUEST.startswith(USER_REQUEST.rstrip("\n")))
        _, direction, _, _ = production_inputs(EMD, SPEED_REQUEST)
        self.assertEqual(len(direction.staging_candidates), 1)
        self.assertIn("通常速度", direction.staging_candidates[0])

    def test_production_baseline_guard_disallows_order_or_settings_change(self):
        baseline = {"shots": [{"prompt": ["Event Camera old performance"], "seed": 9}]}
        candidate = {"shots": [{"prompt": ["Event Camera faster performance"], "seed": 9}]}
        verify_single_body_plan(baseline, candidate, "faster performance", "Camera", baseline_english="old performance")
        candidate["shots"][0]["seed"] = 10
        with self.assertRaises(ValueError):
            verify_single_body_plan(baseline, candidate, "faster performance", "Camera", baseline_english="old performance")
        candidate["shots"][0]["seed"] = 9
        candidate["shots"][0]["prompt"] = ["Event faster performance Camera"]
        with self.assertRaises(ValueError):
            verify_single_body_plan(baseline, candidate, "faster performance", "Camera", baseline_english="old performance")

    def test_plan_guard_detects_camera_or_seed_changes(self):
        baseline = {"shots": [{"prompt": [f"Event {MOMENTUM_ENGLISH} Camera"], "seed": 9}]}
        candidate = deepcopy(baseline)
        candidate["shots"][0]["prompt"] = ["Event translated performance Camera"]
        verify_single_body_plan(baseline, candidate, "translated performance")
        candidate["shots"][0]["seed"] = 10
        with self.assertRaises(ValueError):
            verify_single_body_plan(baseline, candidate, "translated performance")

    def test_normal_renderer_order_allowed_without_other_mutations(self):
        baseline = {"shots": [{"prompt": [f"Event {MOMENTUM_ENGLISH} Camera"], "seed": 9}]}
        candidate = {"shots": [{"prompt": ["Event Camera translated performance"], "seed": 9}]}
        verify_single_body_plan(baseline, candidate, "translated performance", "Camera")
        candidate["shots"][0]["prompt"] = ["Event other Camera translated performance"]
        with self.assertRaises(ValueError):
            verify_single_body_plan(baseline, candidate, "translated performance", "Camera")


if __name__ == "__main__":
    unittest.main()
