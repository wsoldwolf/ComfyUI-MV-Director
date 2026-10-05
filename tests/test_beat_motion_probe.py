import unittest

from tools.debug_beat_motion import rhythm_packet, verify_pair


class BeatMotionProbeTests(unittest.TestCase):
    def test_thinning_retains_original_clock_and_is_not_downbeat_inference(self):
        packet = rhythm_packet({"beat_source_seconds": [10 + i * 0.5 for i in range(12)],
                                "bpm_candidate": 120}, 10000, 15000, 1000, every=3, first=1)
        self.assertEqual(packet["detected_pulse_count"], 10)
        self.assertEqual([c["scene_elapsed_s"] for c in packet["optional_accent_candidates"]], [0.5, 2, 3.5])
        self.assertIsNone(packet["downbeats"])

    def test_pair_does_not_allow_hand_camera_or_candidate_changes(self):
        baseline = {"camera": "fixed", "candidate": "fixed", "held_hand": "right"}
        verify_pair(baseline, {**baseline, "music_rhythm_optional": {"bpm": 167}})
        with self.assertRaises(ValueError):
            verify_pair(baseline, {**baseline, "camera": "changed", "music_rhythm_optional": {}})

    def test_sparse_or_empty_detection_does_not_invent_accents(self):
        packet = rhythm_packet({"beat_source_seconds": [], "bpm_candidate": 167}, 100, 200, 1000)
        self.assertEqual(packet["optional_accent_candidates"], [])

    def test_negative_elapsed_or_invalid_thinning_is_rejected(self):
        with self.assertRaises(ValueError):
            rhythm_packet({"beat_source_seconds": [], "bpm_candidate": 167}, -1, 100, 1000)
        with self.assertRaises(ValueError):
            rhythm_packet({"beat_source_seconds": [], "bpm_candidate": 167}, 0, 100, 1000, every=0)


if __name__ == "__main__":
    unittest.main()
