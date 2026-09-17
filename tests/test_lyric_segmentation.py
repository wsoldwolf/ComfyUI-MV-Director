from __future__ import annotations

import logging
import sys
import types
import unittest
from unittest.mock import patch

from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.lyrics import (
    AlignedLyric,
    LyricSegmentationError,
    VoicedInterval,
    WhisperWord,
    align_lyrics,
    build_whisper_initial_prompt,
    build_timeline,
    coarse_voiced_ranges,
    extract_whisper_words,
    parse_plain_lyrics,
    refine_voiced_ranges,
    recover_unplaced_lyrics,
    render_srt,
    render_template_emd,
    match_similarity,
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
    def test_levenshtein_similarity_matches_prototype_formula(self) -> None:
        self.assertEqual(match_similarity("kitten", "sitting"), 4 / 7)
        self.assertEqual(match_similarity("同一", "同一"), 1.0)

    def test_neighbor_bounded_alignment_recovers_near_match(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE]\n開始 abcdefghij 終了\n")
        words = (
            WhisperWord("開始", "開始", 1000, 1400, 1),
            WhisperWord("abcdeXXXXX", "abcdeXXXXX", 1500, 2000, 2),
            WhisperWord("終了", "終了", 2100, 2500, 3),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=4000,
        )
        self.assertFalse(unplaced)
        self.assertEqual(
            [(item.source.text, item.start_ms) for item in resolved],
            [("開始", 1000), ("abcdefghij", 1500), ("終了", 2100)],
        )

    def test_repeated_lyric_uses_following_lines_to_select_occurrence(self) -> None:
        lyrics = parse_plain_lyrics(
            "[CHORUS]\n開始\n繰り返し\n前半確認\n途中\n繰り返し\n後半確認\n"
        )
        words = (
            WhisperWord("開始", "開始", 1000, 1500, 1),
            WhisperWord("繰り返し", "繰り返し", 2000, 2500, 2),
            WhisperWord("前半確認", "前半確認", 2600, 3200, 3),
            WhisperWord("途中", "途中", 4000, 4500, 4),
            WhisperWord("繰り返し", "繰り返し", 10000, 10500, 5),
            WhisperWord("後半確認", "後半確認", 10600, 11200, 6),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=20000,
        )
        self.assertFalse(unplaced)
        repetitions = [
            item.start_ms for item in resolved if item.source.text == "繰り返し"
        ]
        self.assertEqual(repetitions, [2000, 10000])

    def test_candidate_that_better_matches_next_lyric_is_not_consumed(self) -> None:
        lyrics = parse_plain_lyrics(
            "[VERSE]\n開始\n灰を越える\n年を越える\n終了\n"
        )
        words = (
            WhisperWord("開始", "開始", 1000, 1500, 1),
            WhisperWord("年を越える", "年を越える", 2000, 2800, 2),
            WhisperWord("終了", "終了", 3000, 3500, 3),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=5000,
        )
        self.assertEqual([item.text for item in unplaced], ["灰を越える"])
        self.assertEqual(
            [item.source.text for item in resolved],
            ["開始", "年を越える", "終了"],
        )

    def test_unique_supported_line_can_resynchronize_after_long_gap(self) -> None:
        lyrics = parse_plain_lyrics(
            "[VERSE]\n開始\n存在しない歌詞\n唯一無二の固有帰還地点\n後続歌詞が順序を確認する\n"
        )
        words = (
            WhisperWord("開始", "開始", 1000, 2000, 1),
            WhisperWord("無関係", "無関係", 2100, 2800, 2),
            WhisperWord(
                "唯一無二の固有帰還地点",
                "唯一無二の固有帰還地点",
                30000,
                31000,
                3,
            ),
            WhisperWord(
                "後続歌詞が順序を確認する",
                "後続歌詞が順序を確認する",
                31100,
                32500,
                4,
            ),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=40000,
        )
        self.assertEqual([item.text for item in unplaced], ["存在しない歌詞"])
        self.assertEqual(
            [item.source.text for item in resolved],
            ["開始", "唯一無二の固有帰還地点", "後続歌詞が順序を確認する"],
        )
        self.assertEqual(resolved[1].start_ms, 30000)

    def test_words_outside_vad_are_not_alignment_evidence(self) -> None:
        lyrics = parse_plain_lyrics("[OUTRO]\n幻覚された歌詞\n")
        words = (
            WhisperWord(
                "幻覚された歌詞",
                "幻覚された歌詞",
                123000,
                124000,
                1,
            ),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(VoicedInterval(0, 32000),),
            sample_rate=16000,
            audio_duration_ms=125000,
        )
        self.assertFalse(resolved)
        self.assertEqual([item.text for item in unplaced], ["幻覚された歌詞"])

    def test_whisper_initial_prompt_preserves_source_lines_and_limits_size(self) -> None:
        lyrics = parse_plain_lyrics(
            "[VERSE1]\n朝 露\n森の奥へ\n月明かり\n"
        )
        prompt = build_whisper_initial_prompt(
            lyrics,
            max_lines=2,
            max_characters=20,
        )
        self.assertEqual(prompt, "朝　露\n森の奥へ")

    def test_fuzzy_alignment_uses_real_whisper_word_timestamps(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE1]\n千年鳥居をくぐる\n")
        words = (
            WhisperWord("千年", "千年", 1200, 1800, 1),
            WhisperWord("鳥居を", "鳥居を", 1900, 2600, 2),
            WhisperWord("くぐれ", "くぐれ", 2700, 3300, 3),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=5000,
        )
        self.assertFalse(unplaced)
        self.assertEqual(
            [(item.start_ms, item.end_ms) for item in resolved],
            [(1200, 3300)],
        )

    def test_physical_line_match_recovers_atomic_halves_from_one_whisper_word(self) -> None:
        lyrics = parse_plain_lyrics(
            "[INTRO]\n遠い鈴の音　暁を裂いて\n次の行\n"
        )
        words = (
            WhisperWord(
                "遠い鈴の音暁を裂いて",
                "遠い鈴の音暁を裂いて",
                1000,
                3000,
                1,
            ),
            WhisperWord("次の行", "次の行", 3200, 3800, 2),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=5000,
        )
        self.assertFalse(unplaced)
        self.assertEqual(
            [
                (item.source.text, item.start_ms, item.end_ms)
                for item in resolved
            ],
            [
                ("遠い鈴の音", 1000, 2000),
                ("暁を裂いて", 2000, 3000),
                ("次の行", 3200, 3800),
            ],
        )

    def test_neighbor_bounded_physical_line_recovers_whisper_misrecognition(self) -> None:
        lyrics = parse_plain_lyrics(
            "[PRE-CHORUS]\n前の行\n答えを問うても　御神木は\n次の行\n"
        )
        words = (
            WhisperWord("前の行", "前の行", 1000, 1600, 1),
            WhisperWord("答えを問う", "答えを問う", 1800, 2600, 2),
            WhisperWord("手戻し僕は", "手戻し僕は", 2600, 3400, 3),
            WhisperWord("次の行", "次の行", 3600, 4200, 4),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=5000,
        )
        self.assertFalse(unplaced)
        self.assertEqual(
            [item.source.text for item in resolved],
            ["前の行", "答えを問うても", "御神木は", "次の行"],
        )
        self.assertTrue(
            all(
                left.end_ms <= right.start_ms
                for left, right in zip(resolved, resolved[1:])
            )
        )

    def test_alignment_does_not_jump_beyond_anchored_search_window(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE1]\n朝 遠い歌詞\n")
        words = (
            WhisperWord("朝", "朝", 100, 400, 1),
            WhisperWord("遠い", "遠い", 25000, 25500, 2),
            WhisperWord("歌詞", "歌詞", 25600, 26200, 3),
        )
        resolved, unplaced = align_lyrics(
            lyrics,
            words,
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=30000,
            anchored_search_ms=20000,
        )
        self.assertEqual([item.source.text for item in resolved], ["朝"])
        self.assertEqual([item.text for item in unplaced], ["遠い歌詞"])

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


class TargetedRecoveryTests(unittest.TestCase):
    class _Transcriber:
        def __init__(self, result: dict[str, object]) -> None:
            self.result = result
            self.calls: list[dict[str, object]] = []

        def transcribe(self, audio, **kwargs):
            self.calls.append(kwargs)
            return self.result

    class _SequenceTranscriber:
        def __init__(self, results: list[dict[str, object]]) -> None:
            self.results = results
            self.calls: list[dict[str, object]] = []

        def transcribe(self, audio, **kwargs):
            self.calls.append(kwargs)
            return self.results[min(len(self.calls) - 1, len(self.results) - 1)]

    @staticmethod
    def _result(*words: tuple[str, float, float]) -> dict[str, object]:
        return {
            "segments": [
                {
                    "text": "".join(word for word, _, _ in words),
                    "words": [
                        {"word": word, "start": start, "end": end}
                        for word, start, end in words
                    ],
                }
            ]
        }

    def test_bounded_retry_recovers_real_timestamped_words(self) -> None:
        lyrics = parse_plain_lyrics(
            "[VERSE]\n前\n白銀の髪 黒い着物\n次\n"
        )
        resolved = (
            AlignedLyric(lyrics[0], 1000, 1500),
            AlignedLyric(lyrics[3], 7000, 7500),
        )
        backend = self._Transcriber(
            self._result(
                ("白銀の髪", 2.5, 3.2),
                ("黒い着物", 3.3, 4.0),
                ("次", 7.0, 7.5),
            )
        )
        recovered, unplaced, stats = recover_unplaced_lyrics(
            lyrics,
            resolved,
            [0.0] * (10 * 16000),
            backend,
            language="ja",
            device="cpu",
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=10000,
        )
        self.assertFalse(unplaced)
        self.assertEqual(stats.attempted_runs, 1)
        self.assertEqual(stats.recovered_segments, 2)
        self.assertEqual(
            [(item.source.text, item.start_ms, item.end_ms) for item in recovered],
            [
                ("前", 1000, 1500),
                ("白銀の髪", 2500, 3200),
                ("黒い着物", 3300, 4000),
                ("次", 7000, 7500),
            ],
        )
        self.assertTrue(
            all(
                call["condition_on_previous_text"] is False
                for call in backend.calls
            )
        )

    def test_guided_retry_cannot_invent_without_unguided_evidence(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE]\n前\n存在しない歌詞\n次\n")
        resolved = (
            AlignedLyric(lyrics[0], 1000, 1500),
            AlignedLyric(lyrics[2], 7000, 7500),
        )
        backend = self._Transcriber(
            self._result(("無関係", 3.0, 3.8), ("次", 7.0, 7.5))
        )
        recovered, unplaced, stats = recover_unplaced_lyrics(
            lyrics,
            resolved,
            [0.0] * (10 * 16000),
            backend,
            language="ja",
            device="cpu",
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=10000,
        )
        self.assertEqual(
            [item.source.text for item in recovered], ["前", "次"]
        )
        self.assertEqual([item.text for item in unplaced], ["存在しない歌詞"])
        self.assertEqual(stats.recovered_segments, 0)
        self.assertEqual(len(backend.calls), 2)

    def test_adaptive_unguided_window_recovers_prefix_missed_at_window_edge(self) -> None:
        lyrics = parse_plain_lyrics("[VERSE]\n前\n先頭歌詞 後半歌詞\n次\n")
        resolved = (
            AlignedLyric(lyrics[0], 1000, 1500),
            AlignedLyric(lyrics[3], 7000, 7500),
        )
        backend = self._SequenceTranscriber(
            [
                self._result(("後半歌詞", 4.0, 4.5), ("次", 7.0, 7.5)),
                self._result(
                    ("先頭歌詞", 1.5, 2.0),
                    ("後半歌詞", 3.0, 3.5),
                    ("次", 6.0, 6.5),
                ),
            ]
        )
        recovered, unplaced, stats = recover_unplaced_lyrics(
            lyrics,
            resolved,
            [0.0] * (10 * 16000),
            backend,
            language="ja",
            device="cpu",
            voiced_intervals=(),
            sample_rate=16000,
            audio_duration_ms=10000,
        )
        self.assertFalse(unplaced)
        self.assertEqual(stats.recovered_segments, 2)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(
            [(item.source.text, item.start_ms, item.end_ms) for item in recovered],
            [
                ("前", 1000, 1500),
                ("先頭歌詞", 2500, 3000),
                ("後半歌詞", 4000, 4500),
                ("次", 7000, 7500),
            ],
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
        template = render_template_emd(timeline).text
        self.assertIn(
            "> `シーン` 2\n# シーン 00:10.125 --> 00:20.042 継続",
            template,
        )

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

    def test_unplaced_lyrics_emit_error_and_block_all_data_outputs(self) -> None:
        from nodes.node_lyric_segmentation.node import _block_unplaced

        source = parse_plain_lyrics("[BRIDGE]\n音源にない歌詞\n")
        timeline = build_timeline(
            (),
            source,
            source_audio_duration_ms=1000,
            max_scene_duration_ms=10000,
            timing_profile=DEFAULT_H3_TIMING_PROFILE,
        )

        class FakeExecutionBlocker:
            def __init__(self, message: str) -> None:
                self.message = message

        package = types.ModuleType("comfy_execution")
        graph = types.ModuleType("comfy_execution.graph")
        graph.ExecutionBlocker = FakeExecutionBlocker
        package.graph = graph
        with (
            patch.dict(
                sys.modules,
                {
                    "comfy_execution": package,
                    "comfy_execution.graph": graph,
                },
            ),
            self.assertLogs("mv_director.lyrics", level=logging.ERROR) as captured,
        ):
            result = _block_unplaced(timeline, cache="miss")

        self.assertEqual(
            result["ui"]["status"][0],
            "complete=no; reason=unplaced_lyrics; "
            "unplaced_sections=BRIDGE:1; resolved=0; unplaced=1; "
            "source_ms=1000; plan_ms=1625; scenes=1; cache=miss",
        )
        self.assertTrue(
            all(isinstance(item, FakeExecutionBlocker) for item in result["result"][:3])
        )
        self.assertIn("音源にない歌詞", result["result"][0].message)
        self.assertIn("MV Director - Lyric Segmentation", captured.output[0])


if __name__ == "__main__":
    unittest.main()
