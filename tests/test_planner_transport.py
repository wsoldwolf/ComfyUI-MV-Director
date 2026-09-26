"""Model-independent line-protocol recovery regressions."""

import json
import unittest

from core.planner.requests import _recover_unframed_records, _strip_redundant_record_envelope


class PlannerTransportTests(unittest.TestCase):
    def test_duplicate_record_envelope_is_removed_without_rewriting_text(self) -> None:
        cases = (
            ("ACTION 1 胸郭を起こす。", "ACTION", 1, "胸郭を起こす。"),
            ("ACTION 14 1 視線を上げる。", "ACTION", 1, "視線を上げる。"),
            ("1 タブ　肩を引く。", "ACTION", 1, "肩を引く。"),
            ("AUDIT 2 PASS", "AUDIT", 2, "PASS"),
        )
        for text, record_type, slot, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    _strip_redundant_record_envelope(text, record_type, slot),
                    (expected, True),
                )
        self.assertEqual(
            _strip_redundant_record_envelope(
                "御神木を見上げ、胸郭を起こす。",
                "ACTION",
                1,
            ),
            ("御神木を見上げ、胸郭を起こす。", False),
        )

    def test_unframed_camera_lines_are_recovered_without_rewriting_text(self) -> None:
        response = (
            "Arc Shot with large amplitude at fast speed で側面を通る。\n"
            "Tracking Shot at fast speed で走る人物を追う。"
        )
        self.assertEqual(
            _recover_unframed_records(response, "CAMERA", [4, 5]),
            {
                4: "Arc Shot with large amplitude at fast speed で側面を通る。",
                5: "Tracking Shot at fast speed で走る人物を追う。",
            },
        )

    def test_numbered_protocol_wrapper_is_removed_but_text_is_unchanged(self) -> None:
        response = (
            "1. Arc Shot で人物の右側へ回る。\n"
            "2: Static Shot で顔を保持する。"
        )
        self.assertEqual(
            _recover_unframed_records(response, "CAMERA", [1, 2]),
            {
                1: "Arc Shot で人物の右側へ回る。",
                2: "Static Shot で顔を保持する。",
            },
        )

    def test_single_unlabelled_line_is_not_guessed(self) -> None:
        self.assertEqual(
            _recover_unframed_records(
                "Arc Shot で人物の側面を通る。", "CAMERA", [1]
            ),
            {},
        )

    def test_isolated_single_unlabelled_line_has_unique_side_table_mapping(self) -> None:
        self.assertEqual(
            _recover_unframed_records(
                "Static Shot で両目と口全体を大きく写す。",
                "CAMERA",
                [7],
                allow_single_positional=True,
            ),
            {7: "Static Shot で両目と口全体を大きく写す。"},
        )

    def test_isolated_json_wrapper_recovers_text_without_rewriting_it(self) -> None:
        text = "袖を胸元へ引き寄せ、歌詞の余韻に合わせて視線を上げる。"
        response = json.dumps(
            {"record_type": "ACTION", "slot": 1, "text": text},
            ensure_ascii=False,
        )
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {1: text},
        )

    def test_isolated_markdown_table_recovers_text_without_rewriting_it(self) -> None:
        text = "肩越しに振り返り、右手を胸の前で静止させる。"
        response = "| ACTION | 1 | " + text + " |"
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {1: text},
        )

    def test_isolated_label_wrapper_requires_matching_slot(self) -> None:
        response = "type: ACTION\nslot: 2\ntext: この値は別slotである。"
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {},
        )

    def test_isolated_multiline_prose_uses_unique_side_table_mapping(self) -> None:
        response = (
            "ACTION\nslot: 1\n"
            "袖を胸元へ引き寄せる。\n"
            "続けて視線を鳥居の奥へ移す。"
        )
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {1: "袖を胸元へ引き寄せる。 続けて視線を鳥居の奥へ移す。"},
        )
