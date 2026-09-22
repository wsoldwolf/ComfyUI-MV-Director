import unittest

from tools.offline_generated_performance_brief import brief_input, parse_brief


class GeneratedPerformanceBriefTests(unittest.TestCase):
    def test_line_protocol_is_not_rewritten(self):
        raw = "BRIEF\t1\t開始=胸前で立つ｜変化=腕を外へ差し出す｜終端=腕を伸ばして止まる"
        self.assertEqual(
            parse_brief(raw),
            "開始=胸前で立つ｜変化=腕を外へ差し出す｜終端=腕を伸ばして止まる",
        )
        with self.assertRaises(ValueError):
            parse_brief("BRIEF\t1\t開始=胸前で立つ\n説明")

    def test_request_excludes_original_action(self):
        scene = {
            "scene_number": 1, "lyrics": ["希望"], "cue": "希望を託す",
            "shots": [{"original_action": "漏洩させない"}], "continuation": False,
        }
        request = brief_input(scene, "")
        self.assertEqual(request["shot_count"], 1)
        self.assertNotIn("漏洩させない", str(request))


if __name__ == "__main__":
    unittest.main()
