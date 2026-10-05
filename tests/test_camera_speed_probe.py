import unittest
from copy import deepcopy

from core.emd import parse_emd
from core.lyrics import format_emd_time
from tools.debug_camera_speed import replace_camera_speed, verify_camera_only
from tools.debug_beat_motion import CAMERA


EMD = "# サブジェクト\n* `画像1` 剣を持つ人物。\n"
for scene in range(1, 12):
    start, end = format_emd_time((scene - 1) * 10125), format_emd_time(scene * 10125)
    camera = CAMERA if scene == 11 else "正面から捉える。"
    EMD += (f"\n> `シーン` {scene}\n# シーン {start} --> {end}\n* `H3長` 243\n"
            f"## ショット {start}\n* `演出` 紅葉が舞う。\n* `カメラ` {camera}\n"
            "* `演技` 深く膝を曲げて半回転する。\n")


class CameraSpeedProbeTests(unittest.TestCase):
    def test_only_camera_speed_changes_in_emd(self):
        result, old, new = replace_camera_speed(EMD)
        self.assertEqual(result, EMD.replace("ゆっくり後方へ引き", "通常速度で後方へ引き"))
        self.assertEqual(old, CAMERA)
        self.assertIn("通常速度で後方へ引き", new)
        before, after = parse_emd(EMD), parse_emd(result)
        self.assertEqual(before.scenes[10].shots[0].directives[2], after.scenes[10].shots[0].directives[2])

    def test_rejects_wrong_camera_or_scene(self):
        for invalid in (EMD.replace("ゆっくり後方へ引き", "静止する"), EMD.replace("`シーン` 11", "`シーン` 10")):
            with self.assertRaises(ValueError):
                replace_camera_speed(invalid)

    def test_guard_rejects_performance_order_seed_or_length_changes(self):
        baseline = {"shots": [{"prompt": ["Event old Camera Performance"], "seed": 8, "length": 243}]}
        candidate = {"shots": [{"prompt": ["Event new Camera Performance"], "seed": 8, "length": 243}]}
        verify_camera_only(baseline, candidate, "old Camera", "new Camera")
        for key, value in (("seed", 9), ("length", 238), ("prompt", ["Event new Camera changed Performance"]),
                           ("prompt", ["Event Performance new Camera"])):
            invalid = deepcopy(candidate)
            invalid["shots"][0][key] = value
            with self.assertRaises(ValueError):
                verify_camera_only(baseline, invalid, "old Camera", "new Camera")

    def test_guard_rejects_empty_or_duplicate_camera(self):
        with self.assertRaises(ValueError):
            verify_camera_only({"shots": [{"prompt": ["Camera Camera"]}]}, {}, "Camera", "New Camera")
        with self.assertRaises(ValueError):
            verify_camera_only({"shots": [{"prompt": ["Camera"]}]}, {}, "Camera", "")


if __name__ == "__main__":
    unittest.main()
