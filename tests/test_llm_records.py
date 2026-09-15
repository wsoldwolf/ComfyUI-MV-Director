from __future__ import annotations

import unittest
from pathlib import Path

from core.protocols import ProtocolError, parse_llm_records


FIXTURES = Path(__file__).parent / "fixtures"


class LLMRecordProtocolTests(unittest.TestCase):
    def test_mixed_response_partially_recovers_valid_records(self) -> None:
        response = (FIXTURES / "protocol" / "llm_actions_mixed.txt").read_text(
            encoding="utf-8"
        )
        result = parse_llm_records(
            response,
            allowed_slots={"ACTION": {1, 2, 3}},
            required={("ACTION", 1), ("ACTION", 2), ("ACTION", 3)},
        )

        self.assertEqual(
            [(record.record_type, record.slot) for record in result.records],
            [("ACTION", 1), ("ACTION", 2)],
        )
        self.assertEqual(
            result.records[1].text,
            "人物は手を胸元へ戻す。 髪が遅れて追従する。",
        )
        self.assertEqual(result.missing, (("ACTION", 3),))
        self.assertEqual(
            [issue.reason for issue in result.issues],
            [
                "field_count",
                "duplicate",
                "unknown_type",
                "invalid_slot",
                "unknown_slot",
                "empty_text",
            ],
        )
        self.assertTrue(all(len(issue.raw_sha256) == 64 for issue in result.issues))

    def test_crlf_and_fences_are_ignored(self) -> None:
        result = parse_llm_records(
            "```\r\nDIRECTION\t1\t短い方向性。\r\n```\r\n",
            allowed_slots={"DIRECTION": {1}},
            required={("DIRECTION", 1)},
        )
        self.assertEqual(len(result.records), 1)
        self.assertFalse(result.issues)
        self.assertFalse(result.missing)

    def test_first_valid_duplicate_wins(self) -> None:
        result = parse_llm_records(
            "STYLE\t1\tfirst\nSTYLE\t1\tsecond",
            allowed_slots={"STYLE": {1}},
            required={("STYLE", 1)},
        )
        self.assertEqual(result.records[0].text, "first")
        self.assertEqual(result.issues[0].reason, "duplicate")

    def test_nul_is_a_protocol_error(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_llm_records(
                "ACTION\t1\tbad\x00text",
                allowed_slots={"ACTION": {1}},
                required={("ACTION", 1)},
            )

    def test_required_keys_must_be_allowed(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_llm_records(
                "",
                allowed_slots={"ACTION": {1}},
                required={("ACTION", 2)},
            )


if __name__ == "__main__":
    unittest.main()

