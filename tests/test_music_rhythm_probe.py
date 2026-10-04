import unittest

import numpy as np

from tools.debug_music_rhythm import click_overlay, pulse_summary, source_sample, window_beats


class MusicRhythmProbeTests(unittest.TestCase):
    def test_window_is_half_open_and_retains_original_clock(self):
        self.assertEqual(window_beats([0, 0.5, 1, 1.5], 0.5, 1.5), [0.5, 1])

    def test_invalid_times_are_not_silently_sorted_or_clamped(self):
        for beats in ([1, 0], [1, 1], [-1], [float("nan")], [float("inf")]):
            with self.subTest(beats=beats), self.assertRaises(ValueError):
                window_beats(beats, 0, 2)

    def test_source_sample_uses_original_rate(self):
        self.assertEqual(source_sample(85.68, 48000, 13017600), 4112640)
        self.assertEqual(source_sample(0.5, 48000, 10000), 10000)

    def test_preview_does_not_change_length_channels_or_source(self):
        original = np.zeros((2000, 2), dtype=np.float32)
        preview, scale = click_overlay(original, 1000, [10.1, 11.9], 10)
        self.assertEqual(preview.shape, original.shape)
        self.assertTrue(np.array_equal(original, np.zeros_like(original)))
        self.assertEqual(scale, 1)
        self.assertTrue(np.array_equal(preview[:100], original[:100]))
        self.assertGreater(np.max(np.abs(preview[100:125])), 0)

    def test_preview_silence_has_no_fake_beats(self):
        original = np.zeros((1000, 1), dtype=np.float32)
        preview, _ = click_overlay(original, 1000, [])
        self.assertTrue(np.array_equal(preview, original))

    def test_diagnostic_is_not_labeled_confidence(self):
        self.assertEqual(pulse_summary([0, 0.5, 1]), {"median_interval_s": 0.5, "interval_cv": 0})
        self.assertEqual(pulse_summary([]), {"median_interval_s": None, "interval_cv": None})


if __name__ == "__main__":
    unittest.main()
