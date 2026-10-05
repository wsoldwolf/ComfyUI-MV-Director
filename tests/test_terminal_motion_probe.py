import unittest
from copy import deepcopy

from core.emd import parse_emd
from core.lyrics import format_emd_time
from tools.debug_terminal_motion import OLD_JAPANESE, NEW_JAPANESE, OLD_ENGLISH, replace_terminal_emd, replace_terminal_plan

EMD = "# サブジェクト\n* `画像1` 剣を持つ人物。\n"
for scene in range(1, 12):
    start, end = format_emd_time((scene - 1) * 10125), format_emd_time(scene * 10125)
    ending = OLD_JAPANESE if scene == 11 else "踊る。"
    EMD += (f"\n> `シーン` {scene}\n# シーン {start} --> {end}\n* `H3長` 243\n"
            f"## ショット {start}\n* `演出` 紅葉が舞う。\n* `カメラ` 後退する。\n"
            f"* `演技` 深く膝を曲げて半回転する。{ending}\n")


class TerminalMotionProbeTests(unittest.TestCase):
    def test_only_terminal_japanese_changes(self):
        result, old, new = replace_terminal_emd(EMD)
        self.assertEqual(result, EMD.replace(OLD_JAPANESE, NEW_JAPANESE))
        self.assertEqual(old[:-len(OLD_JAPANESE)], new[:-len(NEW_JAPANESE)])
        self.assertEqual(parse_emd(result).scenes[10].shots[0].directives[:2],
                         parse_emd(EMD).scenes[10].shots[0].directives[:2])

    def test_wrong_or_duplicated_ending_is_rejected(self):
        for text in (EMD.replace(OLD_JAPANESE, "止まる。"), EMD.replace(OLD_JAPANESE, OLD_JAPANESE * 2)):
            with self.assertRaises(ValueError):
                replace_terminal_emd(text)

    def test_plan_preserves_prefix_order_clock_and_seed(self):
        old = "Prepared turn, " + OLD_ENGLISH
        baseline = {"shots": [{"prompt": ["Subject", "Event Camera " + old], "seed": 20261014,
                               "length": 243, "context_length": 0}], "metadata": "fixed"}
        saved = deepcopy(baseline)
        result, new = replace_terminal_plan(baseline, old, "The character keeps dancing.")
        self.assertEqual(baseline, saved)
        self.assertEqual(new, "Prepared turn, The character keeps dancing.")
        expected = deepcopy(baseline)
        expected["shots"][0]["prompt"][1] = "Event Camera " + new
        self.assertEqual(result, expected)

    def test_empty_duplicate_or_full_song_plan_is_rejected(self):
        old = "Prefix " + OLD_ENGLISH
        for plan, ending in (({"shots": [{"prompt": [old]}]}, ""),
                             ({"shots": [{"prompt": [old, old]}]}, "New."),
                             ({"shots": [{"prompt": [old]}, {"prompt": [old]}]}, "New.")):
            with self.assertRaises(ValueError):
                replace_terminal_plan(plan, old, ending)


if __name__ == "__main__":
    unittest.main()
