import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.artifacts import LyricSegment, TimelineArtifact, TimelineScene, TimelineShot
from core.artifacts.base import canonical_json
from core.audio.pad_pair import AudioShape, SceneAudioWindow, align_audio_to_plan_scenes, scene_audio_placements
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.inference import SuccessCache
from core.lyrics import VoicedInterval, build_timeline, render_template_emd
from core.lyrics.activity import ACTIVITY_SCHEMA, build_activity_diagnostic
from nodes.node_lyric_segmentation import node


DIGEST = "a" * 64


def diagnostic(voices=(), **kwargs):
    return build_activity_diagnostic(voices, sample_rate=1000, total_samples=6000,
                                     audio_sha256=DIGEST, **kwargs)


class ActivityTests(unittest.TestCase):
    def test_no_lyrics_does_not_mean_no_voice(self):
        value = diagnostic((VoicedInterval(2500, 4000),))
        self.assertEqual([i["state"] for i in value["source_intervals"]],
                         ["no_vocal_candidate", "vocal_candidate", "no_vocal_candidate"])
        self.assertEqual([(i["position"], i["start_sample"], i["end_sample"])
                          for i in value["long_gaps"]], [("intro", 0, 2500), ("outro", 4000, 6000)])
        self.assertIsNone(value["long_gaps"][0]["previous_vocal_end_sample"])
        self.assertEqual(value["long_gaps"][0]["next_vocal_start_sample"], 2500)
        self.assertIsNone(value["long_gaps"][1]["next_vocal_start_sample"])
        self.assertEqual(json.loads(canonical_json(value)), value)

    def test_fullmix_silence_is_not_instrumental_or_padding(self):
        value = diagnostic(fullmix_active=(VoicedInterval(1000, 5000),))
        self.assertEqual([i["state"] for i in value["source_intervals"]],
                         ["fullmix_silence_candidate", "instrumental_candidate", "fullmix_silence_candidate"])
        self.assertNotIn("padding", [i["state"] for i in value["source_intervals"]])
        self.assertEqual(value["long_gaps"][0]["position"], "whole_source")

    def test_lyric_vad_conflict_retained_as_unknown(self):
        timeline = build_timeline((), (), source_audio_duration_ms=6000,
                                  max_scene_duration_ms=10000, timing_profile=DEFAULT_H3_TIMING_PROFILE)
        from dataclasses import replace
        timeline = replace(timeline, lyrics=(LyricSegment("one", "歌", "VERSE", 1, 0, 1, 1000, 3000, 1, 1),))
        value = diagnostic((VoicedInterval(2000, 4000),), timeline=timeline)
        self.assertEqual([i["state"] for i in value["source_intervals"]],
                         ["no_vocal_candidate", "unknown", "vocal_candidate", "vocal_candidate", "no_vocal_candidate"])
        self.assertEqual(value["warning_count"], 1)
        self.assertFalse(value["long_gaps"][0]["eligible"])
        self.assertEqual(value["long_gaps"][0]["lyric_conflict_ids"], ["one"])

    def test_short_breathing_not_long_gap(self):
        value = diagnostic((VoicedInterval(0, 3000), VoicedInterval(3300, 6000)))
        self.assertEqual(value["long_gaps"], [])
        self.assertEqual(value["source_intervals"][1]["state"], "no_vocal_candidate")

    def test_missing_fullmix_tail_is_unknown_not_silence(self):
        value = diagnostic(fullmix_active=(), fullmix_observed_samples=5999)
        self.assertEqual(value["source_intervals"], [
            {"start_sample": 0, "end_sample": 5999, "state": "fullmix_silence_candidate",
             "lyric_ids": [], "fullmix_active": False},
            {"start_sample": 5999, "end_sample": 6000, "state": "unknown",
             "lyric_ids": [], "fullmix_active": None},
        ])
        self.assertEqual(value["fullmix_coverage_samples"], 5999)
        with self.assertRaisesRegex(ValueError, "observed PCM coverage"):
            diagnostic(fullmix_active=(VoicedInterval(0, 6000),), fullmix_observed_samples=5999)

    def test_intervals_cover_source_once(self):
        value = diagnostic((VoicedInterval(500, 2000), VoicedInterval(4300, 5500)),
                           fullmix_active=(VoicedInterval(0, 6000),))
        rows = value["source_intervals"]
        self.assertEqual(rows[0]["start_sample"], 0)
        self.assertEqual(rows[-1]["end_sample"], 6000)
        self.assertTrue(all(a["end_sample"] == b["start_sample"] for a, b in zip(rows, rows[1:])))
        self.assertEqual(sum(i["end_sample"] - i["start_sample"] for i in rows), 6000)

    def test_malformed_observations_rejected(self):
        for voices in [(VoicedInterval(-1, 4),), (VoicedInterval(0, 6001),),
                       (VoicedInterval(20, 30), VoicedInterval(10, 20)),
                       (VoicedInterval(False, 30),), (VoicedInterval(1.5, 30),)]:
            with self.subTest(voices=voices), self.assertRaises(ValueError):
                diagnostic(voices)

    def test_deferred_padding_and_voice_crossing_scene_boundary(self):
        timeline = TimelineArtifact(20, 1, "test", 29680, 29958, "test", (), (
            TimelineScene(1, 0, 10125, 0, 10000, 243, 243, 0, (TimelineShot(0, 10125),)),
            TimelineScene(2, 10125, 20750, 10000, 20000, 277, 255, 22, (TimelineShot(10125, 20750),)),
            TimelineScene(3, 20750, 29958, 20000, 29680, 243, 221, 22, (TimelineShot(20750, 29958),)),
        ))
        value = build_activity_diagnostic((VoicedInterval(19900, 20200),), sample_rate=1000,
                                          total_samples=29680, audio_sha256=DIGEST, timeline=timeline)
        reference = value["aligned_reference"]
        voices = [i for i in reference["intervals"] if i["state"] == "vocal_candidate"]
        self.assertEqual([(i["start_sample"], i["end_sample"]) for i in voices],
                         [(20025, 20125), (20278, 20478)])
        # Scene 3 PCM starts BEFORE its Plan Scene, disproving a naive Scene offset.
        self.assertEqual(reference["placements"][2]["destination_start_sample"], 20278)
        self.assertEqual(reference["placements"][2]["plan_start_sample"], 20750)
        self.assertEqual([(i["start_sample"], i["end_sample"]) for i in reference["padding"]],
                         [(10000, 10125), (20125, 20278), (29958, 29959)])

    def test_submillisecond_tail_and_stereo_samples_preserved(self):
        import torch
        waveform = torch.arange(384002).reshape(1, 2, 192001)
        window = (SceneAudioWindow(0, 4000, 101),)
        placements = scene_audio_placements(AudioShape(48000, 192001), window,
                                            target_samples=202000)
        self.assertEqual(placements[0].source_end_sample, 192001)
        output, _ = align_audio_to_plan_scenes({"waveform": waveform, "sample_rate": 48000},
                                               window, target_samples=202000)
        self.assertTrue(torch.equal(output["waveform"][..., :192001], waveform))
        self.assertEqual(torch.count_nonzero(output["waveform"][..., 192001:]).item(), 0)


class ActivityNodeTests(unittest.TestCase):
    def test_optional_diagnostic_failure_does_not_raise(self):
        with patch.object(node, "build_activity_diagnostic", side_effect=ValueError("bad mapping")), \
                self.assertLogs("mv_director.lyrics", level="WARNING"):
            self.assertIsNone(node._activity_diagnostic(None, sample_rate=1000, total_samples=6000,
                              timeline=None, audio_sha256=DIGEST, fps=24, voiced=()))

    def test_new_and_legacy_cache_preserve_four_outputs_without_whisper(self):
        import torch
        waveform = torch.zeros((1, 1, 6000))
        timeline = build_timeline((), (), source_audio_duration_ms=6000,
                                  max_scene_duration_ms=10000, timing_profile=DEFAULT_H3_TIMING_PROFILE)
        template = render_template_emd(timeline).text
        model = SimpleNamespace(selection_id="test", size=1, mtime_ns=1)
        with tempfile.TemporaryDirectory() as directory:
            cache = SuccessCache(directory)
            with patch.object(node, "_cache", return_value=cache), \
                    patch.object(node, "resolve_comfy_whisper_model", return_value=model):
                instance = node.MVDirectorLyricSegmentation()
                with patch.object(instance._whisper, "ensure_loaded", side_effect=AssertionError("GPU forbidden")):
                    kwargs = dict(vocal_audio={"waveform": waveform, "sample_rate": 1000}, lyrics_text="[INTRO]\n",
                                  whisper_model="test", language="ja", max_scene_duration_ms=10000,
                                  srt_time_offset_ms=0, cache_mode="refresh", keep_whisper_loaded=False)
                    first = instance.segment(**kwargs)
                    from core.emd import parse_emd
                    self.assertEqual(first[1:3], ("", timeline))
                    prefix = "# サブジェクト\n* 歌手。\n"
                    self.assertEqual(first[0].split("> `シーン`", 1)[1], template.split("> `シーン`", 1)[1])
                    self.assertIsNotNone(parse_emd(prefix + first[0]).audio_activity)
                    path = next(Path(directory).rglob("*.json"))
                    payload = cache.get(path.stem)
                    self.assertEqual(payload["audio_activity"]["schema"], ACTIVITY_SCHEMA)
                    self.assertNotIn("audio_activity", timeline.to_dict())
                    # Legacy cache enrichment runs VAD on CPU but not Whisper.
                    del payload["audio_activity"]
                    payload["template_emd"] = template
                    cache.put_success(path.stem, payload)
                    legacy = instance.segment(**{**kwargs, "cache_mode": "reuse"})
                    self.assertEqual(legacy[:3], first[:3])
                    self.assertIn("cache=hit", legacy[3])
                    self.assertIn("audio_activity", cache.get(path.stem))
                    with patch.object(node, "analyze_waveform", side_effect=AssertionError("VAD repeated")):
                        hit = instance.segment(**{**kwargs, "cache_mode": "reuse"})
                    self.assertEqual(hit, legacy)


if __name__ == "__main__":
    unittest.main()
