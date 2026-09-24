"""CPU contracts for the per-Shot continuous-phrase experiment."""

import json
import unittest

from tools.offline_scene_event_source_probe import (
    BASE_PROMPT, DEFAULT_SOURCE, event_requests,
)
from tools.offline_scene_phrase_focus_probe import (
    focus_grammar, focus_payload, parse_focus_response, phrase_candidates,
    selected_event_prompt, selected_event_request,
)


class ScenePhraseFocusProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
        cls.request = event_requests(source, (4,))[4]

    def test_consecutive_flower_phrase_and_lyrics_only(self):
        groups = {item["id"]: item for item in phrase_candidates(self.request)}
        self.assertEqual(
            [line["text"] for line in groups["SHOT:2"]["lines"]],
            ["わらわだけ", "人は花より", "短く咲いて"],
        )
        payload = focus_payload(self.request)
        self.assertEqual(set(payload), {"scene_number", "shot_lyrics", "phrase_candidates"})
        self.assertNotIn("scene_environment", json.dumps(payload))
        self.assertNotIn("staging_candidates_optional", json.dumps(payload))

    def test_grammar_and_parser(self):
        from llama_cpp import LlamaGrammar

        self.assertIsNotNone(LlamaGrammar.from_string(
            focus_grammar(self.request), verbose=False,
        ))
        response = (
            "EVAL\t1\tNO\n"
            "EVAL\t2\tYES\n"
            "EVAL\t3\tNO\n"
            "SELECT\t1\tSHOT:2\n"
        )
        selected = parse_focus_response(response, self.request)["selected"]
        self.assertEqual(selected["id"], "SHOT:2")
        with self.assertRaises(ValueError):
            parse_focus_response(response.replace("SHOT:2", "SHOT:99"), self.request)
        with self.assertRaises(ValueError):
            parse_focus_response(response.replace("EVAL\t2", "EVAL\t9"), self.request)

    def test_foxfire_cross_shot_boundary_is_available(self):
        from pathlib import Path

        source = Path(
            "docs/assets/research/scene-composition-full-sequence-2026-09-23/"
            "no-previous-state-full-seed2/summary.json"
        )
        request = event_requests(json.loads(source.read_text(encoding="utf-8")), (9,))[9]
        bridge = {item["id"]: item for item in phrase_candidates(request)}["BRIDGE:2-3"]
        self.assertEqual(
            [line["text"] for line in bridge["lines"]],
            ["朱の空に舞う", "狐火へ問う"],
        )

    def test_event_request_preserves_original(self):
        selected = phrase_candidates(self.request)[2]
        changed = selected_event_request(self.request, selected)
        self.assertEqual(changed["selected_lyric_phrase"], selected)
        self.assertEqual(
            {key: value for key, value in changed.items()
             if key != "selected_lyric_phrase"}, self.request,
        )
        prompt = selected_event_prompt(BASE_PROMPT.read_text(encoding="utf-8"))
        self.assertIn("selected_lyric_phrase", prompt)
        with self.assertRaises(ValueError):
            selected_event_request(self.request, {"id": "SHOT:99"})


if __name__ == "__main__":
    unittest.main()
