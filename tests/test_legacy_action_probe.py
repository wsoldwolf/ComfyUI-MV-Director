import unittest
from tools.offline_legacy_action_probe import GitModules, TraceLifecycle, framing


class LegacyActionProbeTests(unittest.TestCase):
    def test_only_probe_namespace_is_served(self):
        loader = object.__new__(GitModules)
        self.assertIsNone(loader.find_spec("json"))
        self.assertIsNone(loader.find_spec("_mvd_legacy_probe_other"))
        self.assertTrue(loader.find_spec("_mvd_legacy_probe.common.gguf").submodule_search_locations is not None)

    def test_framing_does_not_hide_truncation_or_thinking(self):
        text = "LYRIC_SCENE\t6\nACTION\t1\t体を動かす\nEND_LYRIC_SCENE"
        self.assertTrue(framing(text, 6)["expected_end"])
        self.assertFalse(framing(text, 9)["expected_open"])
        self.assertFalse(framing(text.removesuffix("END_LYRIC_SCENE"), 6)["expected_end"])
        self.assertFalse(framing("<think>\n\n</think>\n" + text, 6)["expected_open"])
        self.assertFalse(framing("ACTION\t1", 6)["action_columns_valid"])

    def test_trace_retains_finish_reason_and_content(self):
        lifecycle = TraceLifecycle()
        chunks = [{"choices": [{"delta": {"content": "原文"}}]},
                  {"choices": [{"delta": {}, "finish_reason": "length"}]}]
        self.assertEqual(lifecycle._collect_chat_stream(chunks, None), "原文")
        self.assertEqual(lifecycle.finish_reasons, ["length"])
        self.assertEqual(lifecycle.stream_chunks, 2)

    def test_builder_extraction_cannot_run_other_top_level_code(self):
        loader = object.__new__(GitModules)
        loader.read = lambda path: (
            "from __future__ import annotations\n"
            "raise RuntimeError('must not execute')\n"
            "def _planning_brief_payload(x): return x\n"
            "def _lyric_lines(x): return x\n"
            "def _lyric_action_request_scene(x): return _lyric_lines(x)\n")
        builders = loader.builders()
        self.assertEqual(builders["_lyric_action_request_scene"]("original"), "original")
