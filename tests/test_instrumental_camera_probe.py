import unittest
from copy import deepcopy
from core.lyrics import format_emd_time

from tools.debug_instrumental_camera import (CAMERA, replace_middle_camera, verify_middle_camera,
                                             verify_opening_and_middle_cameras)


class InstrumentalCameraProbeTests(unittest.TestCase):
    def test_emd_changes_only_scene12_camera(self):
        text = "# サブジェクト\n* `画像1` 人物。\n"
        for n in range(1, 14):
            start, end = format_emd_time((n - 1) * 10125), format_emd_time(n * 10125)
            text += (f"\n> `シーン` {n}\n# シーン {start} --> {end}\n"
                     f"* `H3長` 243\n## ショット {start}\n"
                     "* `演出` 水しぶき。\n* `カメラ` 固定。\n* `演技` 身体を捻る。\n")
        result = replace_middle_camera(text, "固定。")
        self.assertEqual(result.count(CAMERA), 1)
        self.assertEqual(result.count("* `カメラ` 固定。"), 12)
        self.assertEqual(result.replace(CAMERA, "固定。"), text)
        with self.assertRaises(ValueError):
            replace_middle_camera(text, "別の文。")
        stronger = "正面から側面へ速いArcで回り込み、腰上の構図へ接近する。"
        changed = replace_middle_camera(text, "固定。", stronger)
        self.assertEqual(changed.replace(stronger, "固定。"), text)
        for invalid in ("", "固定。", "別の文。\n新しい行。"):
            with self.assertRaises(ValueError):
                replace_middle_camera(text, "固定。", invalid)

    def test_plan_protects_all_but_middle_camera(self):
        baseline = {"fps": 24, "shots": [
            {"id": f"s{i}", "seed": i, "prompt": ["Event OldCamera Body"]} for i in range(3)]}
        candidate = deepcopy(baseline)
        candidate["shots"][1]["prompt"] = ["Event NewCamera Body"]
        verify_middle_camera(baseline, candidate, "OldCamera", "NewCamera")
        for index, key, value in ((0, "seed", 5), (2, "prompt", ["changed"]),
                                  (1, "prompt", ["Event NewCamera OtherBody"])):
            changed = deepcopy(candidate)
            changed["shots"][index][key] = value
            with self.assertRaises(ValueError):
                verify_middle_camera(baseline, changed, "OldCamera", "NewCamera")
        for old, new in (("", "new"), ("OldCamera", "OldCamera")):
            with self.assertRaises(ValueError):
                verify_middle_camera(baseline, candidate, old, new)

    def test_two_scene_emd_changes_remain_camera_only(self):
        text = "# サブジェクト\n* `画像1` 人物。\n"
        for n in range(1, 14):
            start, end = format_emd_time((n - 1) * 10125), format_emd_time(n * 10125)
            text += (f"\n> `シーン` {n}\n# シーン {start} --> {end}\n"
                     f"* `H3長` 243\n## ショット {start}\n"
                     "* `演出` 水しぶき。\n* `カメラ` 固定。\n* `演技` 身体を捻る。\n")
        first = replace_middle_camera(text, "固定。", "序盤のArc。", scene_number=11)
        both = replace_middle_camera(first, "固定。", "継続のArc。")
        self.assertEqual(both.replace("序盤のArc。", "固定。").replace("継続のArc。", "固定。"), text)
        self.assertEqual(both.count("* `カメラ` 固定。"), 11)

    def test_two_camera_plan_guards_other_content(self):
        baseline = {"fps": 24, "shots": [
            {"id": f"s{i}", "seed": i, "prompt": [f"Event OldCamera{i} Body"]} for i in range(3)]}
        candidate = deepcopy(baseline)
        candidate["shots"][0]["prompt"] = ["Event NewCamera0 Body"]
        candidate["shots"][1]["prompt"] = ["Event NewCamera1 Body"]
        old, new = ["OldCamera0", "OldCamera1"], ["NewCamera0", "NewCamera1"]
        verify_opening_and_middle_cameras(baseline, candidate, old, new)
        for index, key, value in ((0, "seed", 5), (2, "prompt", ["changed"]),
                                  (1, "prompt", ["Event NewCamera1 OtherBody"])):
            invalid = deepcopy(candidate)
            invalid["shots"][index][key] = value
            with self.assertRaises(ValueError):
                verify_opening_and_middle_cameras(baseline, invalid, old, new)
        with self.assertRaises(ValueError):
            verify_opening_and_middle_cameras(baseline, candidate, old[:1], new)
        with self.assertRaises(ValueError):
            verify_opening_and_middle_cameras(baseline, candidate, old, [old[0], new[1]])


if __name__ == "__main__":
    unittest.main()
