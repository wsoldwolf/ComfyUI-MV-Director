"""CPU safety checks for the opt-in prop experiment, not creative judging."""
from copy import deepcopy
import json
import unittest

from core.emd import parse_emd
from core.inference import LlamaRuntimeConfig
from tools.debug_prop_performance import prepare_inputs, replace_primary_performances, run_condition

SOURCE = (
    "# サブジェクト\n* `画像1` 刀と盾を持つ歌手。\n"
    "> `シーン` 1\n# シーン 00:00.000 --> 00:10.125\n* `H3長` 243\n"
    "## ショット 00:00.000\n* `演技` 右手の刀を引き寄せる。\n* `カメラ` 正面。\n"
    "## ショット 00:05.000\n* `演出` 葉が舞う。\n* `演技` 遠くを見る。\n* `カメラ` 横から追う。\n"
    "> `シーン` 2\n# シーン 00:10.125 --> 00:11.833 継続\n* `H3長` 56\n"
    "## ショット 00:10.125\n* `演技` 右手を前に伸ばす。\n"
    "* `演技` 支持足から横へ一歩進む。\n* `カメラ` 上半身。\n"
)


class PropProbeTests(unittest.TestCase):
    def test_source_boundary_camera_and_supplement_are_frozen(self):
        inputs = prepare_inputs(SOURCE, [1, 2])
        self.assertEqual(inputs[0]["shared"]["subject_emd"], "# サブジェクト\n* `画像1` 刀と盾を持つ歌手。\n")
        self.assertEqual(inputs[0]["shared"]["fixed_performances"], {"1": "右手の刀を引き寄せる。"})
        self.assertEqual([e.key for e in inputs[0]["entities"]], [(2,)])
        self.assertEqual(inputs[1]["shared"]["scheduled_motion_composition"]["text"],
                         "支持足から横へ一歩進む。")
        self.assertEqual(inputs[1]["shared"]["shot_positions"][0]["fixed_camera"], "上半身。")
        self.assertEqual(inputs[1]["shared"]["shot_positions"][0]["fixed_performance"], "")

    def test_only_selected_primary_fields_change(self):
        updated = replace_primary_performances(SOURCE, {(1, 2): "胸を開く。", (2, 1): "視線を上げる。"})
        self.assertIn("右手の刀を引き寄せる。", updated)
        self.assertIn("支持足から横へ一歩進む。", updated)
        self.assertIn("* `カメラ` 横から追う。", updated)
        self.assertNotIn("右手を前に伸ばす。", updated)
        self.assertEqual(len(parse_emd(updated).scenes), 2)
        with self.assertRaises(ValueError):
            replace_primary_performances(SOURCE, {(3, 1): "見つめる。"})

    def test_state_is_forwarded_without_interpreting_the_prop(self):
        inputs = prepare_inputs(SOURCE, [1, 2])
        original = deepcopy(inputs)
        state = "右手は刀を保持、左手は盾を保持。"

        class Backend:
            def __init__(self):
                self.calls = []
            def complete_planner(self, *, payload, **kwargs):
                request = json.loads(payload)
                self.calls.append(request)
                return "\n".join(f"PERFORMANCE\t{s['slot']}\t体幹を向ける。｜END_STATE={state}"
                                 for s in request["slots"])

        backend = Backend()
        rows, replacements = run_condition(backend, inputs, "test", LlamaRuntimeConfig())
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(backend.calls[1]["previous_scene_state"], state)
        self.assertEqual(inputs, original)
        self.assertEqual(rows[0]["terminal_states"], {"2": state})
        self.assertEqual(replacements, {(1, 2): "体幹を向ける。", (2, 1): "体幹を向ける。"})
