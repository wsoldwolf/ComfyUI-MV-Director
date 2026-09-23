"""CPU-only contracts for the experimental dual-lane Scene probe."""

import unittest

from tools.offline_scene_event_performance_probe import (
    _audit_controls, audit_grammar, parse_audit, parse_plan, plan_grammar,
)
from tools.offline_scene_two_stage_probe import _row_grammar
from tools.offline_scene_semantic_audit_probe import grammar as matrix_grammar, parse as parse_matrix
from tools.offline_scene_two_lane_spine_probe import grammar as spine_grammar, parse as parse_spine


class SceneEventPerformanceProbeTests(unittest.TestCase):
    def test_dual_plan_keeps_event_and_body_separate(self) -> None:
        case = _audit_controls()[0]
        result = parse_plan(case["plan"], case["scene"], case["lyrics"])
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["event"]["TARGET"], "社")
        self.assertIn("胸郭", result["body"]["PATH"])

    def test_invalid_contact_point_is_rejected_structurally(self) -> None:
        case = _audit_controls()[1]
        invalid = case["plan"].replace("CONTACT_POINT=石畳", "CONTACT_POINT=なし")
        result = parse_plan(invalid, case["scene"], case["lyrics"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["validation_error"], "contact point missing")

    def test_audit_transport(self) -> None:
        self.assertEqual(parse_audit("AUDIT\t1\tOK")["verdict"], "OK")
        self.assertEqual(
            parse_audit("AUDIT\t1\tREJECT:TARGET_MISMATCH")["verdict"],
            "REJECT:TARGET_MISMATCH",
        )
        self.assertFalse(parse_audit("AUDIT\t1\tREJECT:UNKNOWN")["valid"])

    def test_grammars_compile_without_model(self) -> None:
        from llama_cpp import LlamaGrammar

        LlamaGrammar.from_string(plan_grammar(11), verbose=False)
        LlamaGrammar.from_string(audit_grammar(), verbose=False)
        LlamaGrammar.from_string(_row_grammar("EVENT", 11), verbose=False)
        LlamaGrammar.from_string(_row_grammar("BODY", 11), verbose=False)
        LlamaGrammar.from_string(matrix_grammar(), verbose=False)
        LlamaGrammar.from_string(spine_grammar(), verbose=False)

    def test_matrix_and_two_lane_spine_transport(self) -> None:
        matrix = (
            "CHECK\t1\tTARGET_ACTION=FAIL｜CONTACT_POINT=FAIL"
            "｜EXTERNAL_EFFECT=PASS｜SYNC=PASS"
        )
        self.assertTrue(parse_matrix(matrix)["valid"])
        self.assertEqual(parse_matrix(matrix)["flags"]["CONTACT_POINT"], "FAIL")
        spine = (
            "STEP\t1\tPHASE=event｜FROM=両足支持｜EVENT_STEP=狐火が昇る"
            "｜BODY_STEP=顔を上げる｜TO=腕を低く保つ｜SHOW=lyric_target\n"
            "STEP\t2\tPHASE=response｜FROM=腕を低く保つ｜EVENT_STEP=なし"
            "｜BODY_STEP=目を閉じる｜TO=両足支持｜SHOW=face_eyes_mouth"
        )
        self.assertTrue(parse_spine(spine)["valid"])
        self.assertEqual(parse_spine(spine)["rows"]["2"]["EVENT_STEP"], "なし")


if __name__ == "__main__":
    unittest.main()
