import unittest
from copy import deepcopy

from core.emd import parse_emd
from core.lyrics import format_emd_time
from tools.debug_shot_duration import short_clock, verify_duration_only, isolated_emd

EMD = "# サブジェクト\n* `画像1` 剣を持つ人物。\n"
for scene in range(1, 12):
    start = format_emd_time((scene - 1) * 10125)
    end = format_emd_time(scene * 10125)
    EMD += (f"\n> `シーン` {scene}\n# シーン {start} --> {end}\n* `H3長` 243\n"
            f"## ショット {start}\n* `演出` 紅葉が舞う。\n* `カメラ` 後退する。\n"
            "* `演技` 深く膝を曲げて半回転する。\n")


class ShotDurationProbeTests(unittest.TestCase):
    def setUp(self):
        self.clock = {"sample_rate": 48000, "source_start_sample": 4294000, "source_end_sample": 4770000}
        self.plan = {"shots": [{"length": 243, "context_length": 0, "audio_context_length": 0,
                               "seed": 20261014, "prompt": ["Event Camera Performance"]}]}

    def test_five_seconds_ceil_to_actual_h3_grid(self):
        result = short_clock(self.clock)
        self.assertEqual(result["render_frames"], 124)
        self.assertEqual(result["content_frames"], 120)
        self.assertEqual(result["source_end_sample"], 4534000)
        self.assertEqual(result["tail_silence_samples"], 8000)
        self.assertEqual(result["source_start_sample"], self.clock["source_start_sample"])

    def test_rejects_invalid_clock_or_duration(self):
        for duration in (0, -1, 41, 10000):
            with self.assertRaises(ValueError):
                short_clock(self.clock, duration)

    def test_guard_allows_only_length_change(self):
        candidate = deepcopy(self.plan)
        candidate["shots"][0]["length"] = 124
        verify_duration_only(self.plan, candidate, 124)
        for key, value in (("seed", 1), ("prompt", ["Other Camera Performance"]), ("context_length", 22)):
            changed = deepcopy(candidate)
            changed["shots"][0][key] = value
            with self.assertRaises(ValueError):
                verify_duration_only(self.plan, changed, 124)
        with self.assertRaises(ValueError):
            verify_duration_only(self.plan, candidate, 120)

    def test_local_documentary_emd_preserves_body(self):
        result = parse_emd(isolated_emd(EMD, 5000, 124))
        original = parse_emd(EMD)
        self.assertEqual(len(result.scenes), 1)
        self.assertEqual(result.scenes[0].start_ms, 0)
        self.assertEqual(result.scenes[0].end_ms, 5000)
        self.assertEqual(result.scenes[0].h3_length, 124)
        self.assertEqual(result.scenes[0].shots[0].body, original.scenes[10].shots[0].body)

    def test_context_loop_audio_directive_is_preserved(self):
        text = EMD + "## 音響\n* `リップシンク` `Context Loop` `サブジェクト1`\n"
        result = parse_emd(isolated_emd(text, 5000, 124))
        self.assertEqual(result.scenes[0].audio_directives[0].mode, "context_loop")
        self.assertEqual(result.scenes[0].audio_directives[0].target_concept_id, "サブジェクト1")


if __name__ == "__main__":
    unittest.main()
