"""CPU-only checks for the pre-labelled target/change audit study."""

import json
import unittest

from tools.offline_scene_target_event_alignment_probe import (
    CASES,
    binary_grammar,
    grammar,
    parse,
    parse_binary,
)


class SceneTargetEventAlignmentProbeTests(unittest.TestCase):
    def test_case_ids_and_hand_origin_gold_are_explicit(self) -> None:
        cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(by_id["foxfire_hand_origin_orbit"]["event"], "yes")
        self.assertEqual(by_id["foxfire_hand_origin_rise"]["event"], "yes")
        self.assertEqual(by_id["shrine_substring_trap"]["event"], "no")

    def test_grammar_compiles_without_loading_model(self) -> None:
        from llama_cpp import LlamaGrammar

        LlamaGrammar.from_string(grammar(), verbose=False)
        LlamaGrammar.from_string(binary_grammar(), verbose=False)

    def test_binary_format(self) -> None:
        self.assertEqual(
            parse_binary("ALIGN\t1\tSOURCE=yes｜EVENT=no\n"),
            {"valid": True, "fields": {"SOURCE": "yes", "EVENT": "no"}},
        )
        self.assertFalse(parse_binary("ALIGN\t1\tSOURCE=yes｜EVENT=maybe")["valid"])

    def test_quote_must_be_in_change(self) -> None:
        change = "人物の掌に狐火が灯り、周囲を巡る"
        good = parse("ALIGN\t1\tSOURCE=yes｜EVENT=yes｜QUOTE=狐火が灯り", change)
        self.assertTrue(good["valid"])
        self.assertTrue(good["quote_valid"])
        bad = parse("ALIGN\t1\tSOURCE=yes｜EVENT=yes｜QUOTE=社の柱", change)
        self.assertTrue(bad["valid"])
        self.assertFalse(bad["quote_valid"])
        absent = parse("ALIGN\t1\tSOURCE=yes｜EVENT=no｜QUOTE=なし", change)
        self.assertTrue(absent["quote_valid"])


if __name__ == "__main__":
    unittest.main()
