import unittest
from tools.instrumental_candidate_routing import ScopedCandidate, route_candidates


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [ScopedCandidate("author general"), ScopedCandidate("intro", "intro"),
            ScopedCandidate("interlude", "interlude"), ScopedCandidate("outro", "outro"),
            ScopedCandidate("return", "vocal_return")]

    def route(self, segments, position="internal", **kwargs):
        return route_candidates(self.candidates, {"timebase": "end_padded_source_pcm",
            "song_position": position, "intervals": [dict(start_ms=a, end_ms=b, state=s)
            for a, b, s in segments]}, start_ms=0, end_ms=10000, **kwargs)

    def test_internal_not_intro_or_outro(self):
        self.assertEqual(self.route([(0, 10000, "instrumental_candidate")])["texts"], ["author general", "interlude"])

    def test_intro_and_outro(self):
        for position in ("intro", "outro"):
            self.assertEqual(self.route([(0, 10000, "instrumental_candidate")], position)["texts"], ["author general", position])

    def test_return_requires_ordered_actual_transition(self):
        self.assertIn("return", self.route([(0, 6000, "instrumental_candidate"), (6000, 10000, "vocal_candidate")])["texts"])
        self.assertNotIn("return", self.route([(0, 6000, "vocal_candidate"), (6000, 10000, "instrumental_candidate")])["texts"])

    def test_unknown_or_missing_mapping_falls_back_without_blocking(self):
        self.assertTrue(self.route([(0, 10000, "unknown")])["fallback"])
        self.assertTrue(self.route([(0, 10000, "no_vocal_candidate")])["fallback"])
        self.assertTrue(self.route([(0, 10000, "unrecognized_future_state")])["fallback"])
        self.assertTrue(self.route([(0, 9999, "instrumental_candidate")])["fallback"])
        self.assertTrue(route_candidates(self.candidates, None, start_ms=0, end_ms=10000)["fallback"])

    def test_voiced_and_padding_do_not_imply_interlude(self):
        for state in ("vocal_candidate", "padding", "fullmix_silence_candidate"):
            self.assertEqual(self.route([(0, 10000, state)])["texts"], ["author general"])

    def test_brief_gap_not_full_interlude(self):
        result = self.route([(0, 9000, "vocal_candidate"), (9000, 10000, "instrumental_candidate")])
        self.assertNotIn("interlude", result["texts"])

    def test_no_lexical_classification_of_user_text(self):
        candidates = [ScopedCandidate("Intro 間奏 狐火を自由に表現する")]
        self.assertEqual(route_candidates(candidates, None, start_ms=0, end_ms=10000)["texts"], [candidates[0].text])

    def test_invalid_scope(self):
        with self.assertRaises(ValueError):
            ScopedCandidate("body", "keyword_guess")


if __name__ == "__main__":
    unittest.main()
