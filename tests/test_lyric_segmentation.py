from __future__ import annotations

import unittest

from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.lyrics import (
    AlignedLyric,
    LyricSegmentationError,
    VoicedInterval,
    WhisperWord,
    align_lyrics,
    build_timeline,
    coarse_voiced_ranges,
    extract_whisper_words,
    parse_plain_lyrics,
    refine_voiced_ranges,
    render_srt,
    render_template_emd,
)


class PlainLyricsTests(unittest.TestCase):
    def test_sections_repeat_and_spaces_make_atomic_segments(self) -> None:
        segments = parse_plain_lyrics(
            "[VERSE1]\nほげほげ  ふがふが\n\n[VERSE1]\n月\t光　道\n"
        )
        self.assertEqual(
            [(item.segment_id, item.text, item.section) for item in segments],
            [
                ("lyric_0001", "ほげほげ", "VERSE1"),
                ("lyric_0002", "ふがふが", "VERSE1"),
                ("lyric_0003", "月", "VERSE1"),
                ("lyric_0004", "光", "VERSE1"),
                ("lyric_0005", "道", "VERSE1"),
            ],
        )
        self.assertEqual((segments[1].source_start, segments[1].source_end), (6, 10))

    def test_empty_sections_are_valid(self) -> None:
        self.assertEqual(parse_plain_lyrics("[INTRO]\n\n[VERSE1]\n"), ())

    def test_section_headings_are_case_insensitive_and_canonicalized(self) -> None:
        segments = parse_plain_lyrics("[Chorus]\n千年鳥居\n[bridge_A]\n月明かり\n")
        self.assertEqual(
            [(item.text, item.section) for item in segments],
            [("千年鳥居", "CHORUS"), ("月明かり", "BRIDGE_A")],
        )

    def test_section_headings_allow_and_normalize_inner_whitespace(self) -> None:
        segments = parse_plain_lyrics(
            "[ Verse 1 ]\n千年鳥居\n[Chorus　]\n月明かり\n"
        )
        self.assertEqual(
            [(item.text, item.section) for item in segments],
            [("千年鳥居", "VERSE_1"), ("月明かり", "CHORUS")],
        )

    def test_rejects_non_plain_metadata(self) -> None:
        invalid = (
            "歌詞\n[VERSE1]\n歌詞",
            " [VERSE1]\n歌詞",
            "[VERSE1] \n歌詞",
            "[VERSE1]\n[00:01.00]歌詞",
            "[VERSE1]\n00:00:01,000 --> 00:00:02,000",
            "[VERSE1]\n// comment",
            "[ＣHORUS]\n歌詞",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(LyricSegmentationError):
                parse_plain_lyrics(value)


class AlignmentTests(unittest.TestCase):
    def test_ordered_alignment_preserves_word_end_not_next_word_start(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE1]\nほげ ふが\n")
        words = (
            WhisperWord("ほげ", "ほげ", 100, 500, 1),
            WhisperWord("ふが", "ふが", 700, 1000, 2),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(VoicedInterval(0, 16000),),
            sample_rate=16000,
            audio_duration_ms=2000,
        )
        self.assertFalse(unplaced)
        self.assertEqual([(item.start_ms, item.end_ms) for item in resolved], [(100, 500), (700, 1000)])

    def test_unmatched_lyrics_are_not_given_invented_times(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE1]\n一致 不一致\n")
        resolved, unplaced = align_lyrics(
            lyrics,
            (WhisperWord("一致", "一致", 100, 400, 1),),
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=1000,
        )
        self.assertEqual([item.source.text for item in resolved], ["一致"])
        self.assertEqual([item.text for item in unplaced], ["不一致"])

    def test_whisper_requires_word_timestamps(self) -> None:
        with self.assertRaisesRegex(LyricSegmentationError, "word_timestamps"):
            extract_whisper_words(
                {"segments": [{"text": "歌詞"}]}, audio_duration_ms=1000
            )


class VadAndTimelineTests(unittest.TestCase):
    def test_coarse_vad_fills_short_internal_silence_and_drops_short_voice(self) -> None:
        voiced = coarse_voiced_ranges(
            [-10, -10, -80, -10, -10, -80, -80, -80],
            total_samples=800,
            sample_rate=1000,
            window_samples=100,
            min_voiced_ms=150,
            min_silence_ms=150,
        )
        self.assertEqual(voiced, (VoicedInterval(0, 500),))

    def test_sample_refinement_does_not_return_to_twenty_ms_grid(self) -> None:
        envelope = [0.0] * 100
        envelope[13:77] = [0.1] * 64
        refined = refine_voiced_ranges(
            envelope,
            (VoicedInterval(0, 100),),
            total_samples=100,
            sample_rate=1000,
            window_samples=20,
            padding_ms=0,
        )
        self.assertEqual(refined, (VoicedInterval(13, 77),))

    def test_cumulative_h3_grid_matches_contract_example(self) -> None:
        source = parse_plain_lyrics("[VERSE1]\n朝 夜\n")
        resolved = (
            AlignedLyric(source[0], 2300, 2800),
            AlignedLyric(source[1], 12300, 15800),
        )
        timeline = build_timeline(
            resolved,
            (),
            source_audio_duration_ms=20000,
            max_scene_duration_ms=10000,
            timing_profile=DEFAULT_H3_TIMING_PROFILE,
        )
        self.assertEqual(
            [(scene.raw_length, scene.delivered_frames) for scene in timeline.scenes],
            [(243, 243), (260, 238)],
        )
        self.assertEqual(timeline.plan_duration_ms, 20042)
        self.assertEqual(timeline.lyrics[1].section, "VERSE1")

    def test_template_and_srt_share_canonical_segments(self) -> None:
        source = parse_plain_lyrics("[CHORUS]\n千年鳥居 月明かり\n")
        timeline = build_timeline(
            (
                AlignedLyric(source[0], 2300, 5800),
                AlignedLyric(source[1], 6200, 8500),
            ),
            (),
            source_audio_duration_ms=10000,
            max_scene_duration_ms=10000,
            timing_profile=DEFAULT_H3_TIMING_PROFILE,
        )
        template = render_template_emd(timeline).text
        srt = render_srt(timeline)
        self.assertIn("> `シーン` 1\n# シーン 00:00.000 --> 00:10.125", template)
        self.assertIn("> `セクション` CHORUS", template)
        self.assertEqual(template.count("> `歌詞`"), 2)
        self.assertIn("00:00:02,300 --> 00:00:05,800\n千年鳥居", srt)
        self.assertNotIn("CHORUS", srt)

    def test_long_atomic_segment_splits_only_at_aligned_word_boundary(self) -> None:
        source = parse_plain_lyrics("[VERSE1]\n長い歌詞\n")
        resolved, unplaced = align_lyrics(
            source,
            (
                WhisperWord("長い", "長い", 0, 6000, 1),
                WhisperWord("歌詞", "歌詞", 6000, 12000, 2),
            ),
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=13000,
        )
        self.assertFalse(unplaced)
        timeline = build_timeline(
            resolved,
            (),
            source_audio_duration_ms=13000,
            max_scene_duration_ms=10000,
            timing_profile=DEFAULT_H3_TIMING_PROFILE,
        )
        self.assertEqual(
            [(item.segment_id, item.text, item.start_ms, item.end_ms) for item in timeline.lyrics],
            [
                ("lyric_0001_01", "長い", 0, 6000),
                ("lyric_0001_02", "歌詞", 6000, 12000),
            ],
        )


class PublicNodeTests(unittest.TestCase):
    def test_public_mapping_and_socket_surface(self) -> None:
        from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

        cls = NODE_CLASS_MAPPINGS["MVDirectorLyricSegmentation"]
        self.assertEqual(
            NODE_DISPLAY_NAME_MAPPINGS["MVDirectorLyricSegmentation"],
            "MV Director - Lyric Segmentation",
        )
        self.assertEqual(cls.CATEGORY, "MV Director/Input")
        self.assertEqual(
            cls.RETURN_TYPES,
            ("STRING", "STRING", "MV_DIRECTOR_TIMELINE", "STRING"),
        )


if __name__ == "__main__":
    unittest.main()
