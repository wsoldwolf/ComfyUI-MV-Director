import unittest
from tools.offline_section_performance_probe import reading_context, FixedSeedBackend


class SectionProbeTests(unittest.TestCase):
    def test_original_heading_occurrences_remain_separate(self):
        lyrics = "[Chorus]\n前半\n[Chorus]\n後半\n"
        payload = {"original_lyrics": [{"lyrics": [{"section": "CHORUS", "text": "後半"}]}]}
        context = reading_context(lyrics, payload)
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]["occurrence"], 2)
        self.assertEqual(context[0]["lines"][0]["text"], "後半")

    def test_ambiguous_source_span_is_rejected(self):
        payload = {"original_lyrics": [{"lyrics": [{"section": "CHORUS", "text": "同じ"}]}]}
        with self.assertRaisesRegex(ValueError, "unique"):
            reading_context("[Chorus]\n同じ\n[Chorus]\n同じ\n", payload)

    def test_effective_seed_does_not_depend_on_payload(self):
        self.assertEqual(FixedSeedBackend._call_seed(2, "x", 1, "a"), 2)
        self.assertEqual(FixedSeedBackend._call_seed(2, "x", 9, "b"), 2)
