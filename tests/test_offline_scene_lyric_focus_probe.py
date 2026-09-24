"""CPU contracts for the lyric-only source selection experiment."""

import json
import unittest

from tools.offline_scene_event_source_probe import (
    BASE_PROMPT, DEFAULT_SOURCE, event_requests,
)
from tools.offline_scene_lyric_focus_probe import (
    focus_grammar, focus_ids, lyric_only_payload, parse_focus_response,
    selected_event_prompt, selected_event_request,
)


class LyricFocusProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = event_requests(
            json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8")), (4,),
        )[4]

    def test_focus_sees_only_current_lyrics(self):
        payload = lyric_only_payload(self.request)
        self.assertEqual(set(payload), {"scene_number", "original_lyrics"})
        self.assertNotIn("scene_environment", json.dumps(payload))
        self.assertNotIn("staging_candidates_optional", json.dumps(payload))
        self.assertEqual(
            [line["id"] for row in payload["original_lyrics"]
             for line in row["lyrics"] if "花" in line["text"]],
            ["LYRIC:shot2:line84"],
        )

    def test_selected_id_must_exist_in_current_scene(self):
        self.assertIn("LYRIC:shot2:line84", focus_ids(self.request))
        self.assertEqual(
            parse_focus_response("SOURCE\t1\tLYRIC:shot2:line84\n", self.request),
            {"id": "LYRIC:shot2:line84", "shot": 2,
             "source_line": 84, "text": "人は花より"},
        )
        with self.assertRaises(ValueError):
            parse_focus_response("SOURCE\t1\tCANDIDATE:1\n", self.request)
        with self.assertRaises(ValueError):
            parse_focus_response("SOURCE\t1\tLYRIC:shot2:line999\n", self.request)

    def test_focus_grammar_compiles(self):
        from llama_cpp import LlamaGrammar

        grammar = focus_grammar(self.request)
        reverse = focus_grammar(self.request, reverse_choices=True)
        self.assertNotIn("CANDIDATE:", grammar)
        self.assertIsNotNone(LlamaGrammar.from_string(grammar, verbose=False))
        self.assertIsNotNone(LlamaGrammar.from_string(reverse, verbose=False))
        self.assertNotEqual(grammar, reverse)

    def test_event_prompt_retains_frozen_instructions(self):
        original = BASE_PROMPT.read_text(encoding="utf-8")
        changed = selected_event_prompt(original)
        self.assertTrue(changed.startswith(original.partition("一行のみ、EVENT")[0]))
        self.assertIn("selected_lyric_source", changed)
        self.assertIn("EVENT<TAB>1<TAB>SHOT=番号", changed)

    def test_event_request_only_adds_selected_source(self):
        selected = parse_focus_response(
            "SOURCE\t1\tLYRIC:shot2:line84\n", self.request,
        )
        changed = selected_event_request(self.request, selected)
        self.assertEqual(changed["selected_lyric_source"], selected)
        self.assertEqual(
            {key: value for key, value in changed.items()
             if key != "selected_lyric_source"},
            self.request,
        )
        with self.assertRaises(ValueError):
            selected_event_request(self.request, {"id": "CANDIDATE:1"})


if __name__ == "__main__":
    unittest.main()
