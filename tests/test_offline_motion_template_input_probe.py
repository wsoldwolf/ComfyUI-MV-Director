"""Transport tests for the proposed Planner-only motion-template fragment."""

import unittest

from core.inference.cache import build_cache_key
from tools.offline_motion_template_input_probe import parse_motion_templates


class MotionTemplateInputProbeTests(unittest.TestCase):
    def test_missing_and_header_only_are_empty(self) -> None:
        self.assertEqual(parse_motion_templates(""), ())
        self.assertEqual(parse_motion_templates("  \n\t"), ())
        self.assertEqual(parse_motion_templates("# モーションテンプレート\n"), ())

    def test_one_line_per_candidate_keeps_order_and_prose(self) -> None:
        text = "\ufeff# モーションテンプレート\r\n* 第一の動き。\r\n\r\n* 第二の動き。\r\n"
        self.assertEqual(parse_motion_templates(text), ("第一の動き。", "第二の動き。"))
        self.assertEqual(parse_motion_templates("# モーションテンプレート\n* 一つだけ"), ("一つだけ",))

    def test_nonempty_malformed_fragment_is_rejected(self) -> None:
        for text in (
            "* 見出しがない", "# モーションテンプレート\n* ",
            "# モーションテンプレート\n継続行", "# モーションテンプレート\n- 記号が違う",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_motion_templates(text)

    def test_template_content_changes_cache_key_without_whitespace_noise(self) -> None:
        def key(raw: str) -> str:
            return build_cache_key(
                task="timeline-planner", algorithm_version="motion-template-probe-v1",
                inputs={"motion_templates": list(parse_motion_templates(raw))},
            )

        self.assertNotEqual(key("# モーションテンプレート\n* A"), key("# モーションテンプレート\n* B"))
        self.assertEqual(key("# モーションテンプレート\r\n* A\r\n"), key("# モーションテンプレート\n* A\n"))
        self.assertEqual(key(""), key("# モーションテンプレート\n"))


if __name__ == "__main__":
    unittest.main()
