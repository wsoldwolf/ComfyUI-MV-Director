"""CPU contracts for the frozen Event-source comparison."""

import json
from pathlib import Path
import unittest

from tools.offline_scene_event_source_probe import (
    BASE_PROMPT, DEFAULT_SOURCE, event_requests, parse_source_response,
    source_grammar, source_ids, source_prompt,
)


class EventSourceProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        summary = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
        cls.requests = event_requests(summary, (3, 4, 5, 6))

    def test_p0_flower_is_in_shot_two_with_existing_line_id(self):
        request = self.requests[4]
        selected = [
            (shot["shot"], line["source_line"], line["text"])
            for shot in request["original_lyrics"] for line in shot["lyrics"]
            if "花" in line["text"]
        ]
        self.assertEqual(selected, [(2, 84, "人は花より")])
        self.assertIn("LYRIC:shot2:line84", source_ids(request))
        self.assertEqual(len(request["staging_candidates_optional"]), 7)

    def test_prompt_keeps_baseline_selection_instructions(self):
        baseline = BASE_PROMPT.read_text(encoding="utf-8")
        changed = source_prompt(baseline)
        self.assertTrue(changed.startswith(baseline.partition("一行のみ、EVENT")[0]))
        self.assertIn("原歌詞の具体物", changed)
        self.assertIn("SOURCE=許可されたID", changed)

    def test_source_response_accepts_only_real_source_and_shot(self):
        request = self.requests[4]
        line = (
            "EVENT\t1\tSOURCE=LYRIC:shot2:line84｜FOCUS=花｜SHOT=2｜"
            "参道脇の花びらが人物の前を横切る\n"
        )
        self.assertEqual(parse_source_response(line, request)["source"],
                         "LYRIC:shot2:line84")
        with self.assertRaises(ValueError):
            parse_source_response(line.replace("line84", "line999"), request)
        with self.assertRaises(ValueError):
            parse_source_response(line.replace("SHOT=2", "SHOT=9"), request)
        with self.assertRaises(ValueError):
            parse_source_response(line.replace("LYRIC:shot2:line84", "NONE"), request)

    def test_grammar_compiles_and_only_allows_existing_source_ids(self):
        from llama_cpp import LlamaGrammar

        request = self.requests[4]
        grammar = source_grammar(request)
        self.assertIn('"LYRIC:shot2:line84"', grammar)
        self.assertNotIn('"LYRIC:shot2:line999"', grammar)
        self.assertIsNotNone(LlamaGrammar.from_string(grammar, verbose=False))


if __name__ == "__main__":
    unittest.main()
