"""Bounded window perturbations retain all existing acceptance checks."""
import unittest

from core.lyrics import AlignedLyric, parse_plain_lyrics, recover_unplaced_lyrics


def result(*words):
    return {"segments": [{"text": "".join(w[0] for w in words), "words": [
        {"word": text, "start": start, "end": end} for text, start, end in words
    ]}]}


class ShiftedRecoveryTests(unittest.TestCase):
    def run_case(self, *, evidence=True, following=True, outside=False,
                 normal_success=False, wrong_anchor=False):
        prior_end = 46520
        lyrics = parse_plain_lyrics("[VERSE]\n前の歌詞\n失われた歌詞\n次の歌詞\n")
        resolved = (AlignedLyric(lyrics[0], 40000, prior_end),
                    AlignedLyric(lyrics[2], 48240, 49740))
        calls = []

        class Backend:
            def transcribe(self, audio, **kwargs):
                start = audio[0] // 16
                calls.append((start, len(audio), kwargs))
                guided = kwargs['initial_prompt'] == '失われた歌詞'
                if start == prior_end - 2000:
                    if normal_success:
                        return result(('失われた歌詞', 2.52, 3.70),
                                      ('次の歌詞', 3.94, 5.38))
                    if guided:
                        # Target-only repetition omits the known next anchor.
                        return result(('失われた歌詞', 2.52, 3.70),
                                      ('失われた歌詞', 5.70, 6.06))
                    return result(('雑音', 2.52, 3.70), ('次の歌詞', 3.94, 5.38))
                if not guided:
                    return result(('雑音', 0.20 if outside or not evidence else 2.38,
                                           2.00 if outside else (3.56 if evidence else 0.40)),
                                  ('次の歌詞', 3.80, 5.24))
                words = [('失われた歌詞', 0.20 if outside else 2.38,
                                           2.00 if outside else 3.56)]
                if following:
                    words.append(('次の歌詞', 5.60 if wrong_anchor else 3.80,
                                           5.90 if wrong_anchor else 5.24))
                return result(*words)

        recovered, unplaced, stats = recover_unplaced_lyrics(
            lyrics, resolved, range(55000 * 16), Backend(), language='ja',
            device='cpu', voiced_intervals=(), sample_rate=16000,
            audio_duration_ms=55000,
        )
        return recovered, unplaced, stats, calls, resolved

    def test_shifted_pair_recovers_and_restores_absolute_source_clock(self):
        recovered, unplaced, stats, calls, resolved = self.run_case()
        self.assertFalse(unplaced)
        self.assertEqual(stats.recovered_segments, 1)
        self.assertEqual([c[0] for c in calls], [44520, 44520, 44660, 44660])
        self.assertEqual([c[2]['initial_prompt'] for c in calls],
                         ['前の歌詞', '失われた歌詞', '前の歌詞', '失われた歌詞'])
        self.assertEqual((recovered[1].start_ms, recovered[1].end_ms), (47040, 48220))
        self.assertIs(recovered[0], resolved[0])
        self.assertIs(recovered[2], resolved[1])
        self.assertTrue(all(not c[2]['condition_on_previous_text'] for c in calls))

    def test_shifted_guided_result_still_needs_unguided_evidence(self):
        recovered, unplaced, stats, calls, _ = self.run_case(evidence=False)
        self.assertEqual([s.text for s in unplaced], ['失われた歌詞'])
        self.assertEqual(stats.recovered_segments, 0)
        self.assertEqual(len(calls), 4)

    def test_shifted_result_still_requires_following_anchor(self):
        _, unplaced, stats, calls, _ = self.run_case(following=False)
        self.assertTrue(unplaced)
        self.assertEqual(stats.recovered_segments, 0)
        self.assertEqual(len(calls), 4)

    def test_shifted_result_cannot_cross_previous_anchor(self):
        _, unplaced, stats, _, _ = self.run_case(outside=True)
        self.assertTrue(unplaced)
        self.assertEqual(stats.recovered_segments, 0)

    def test_shifted_following_lyric_must_overlap_its_original_anchor(self):
        _, unplaced, stats, _, _ = self.run_case(wrong_anchor=True)
        self.assertTrue(unplaced)
        self.assertEqual(stats.recovered_segments, 0)

    def test_successful_original_decode_adds_no_work(self):
        _, unplaced, _, calls, _ = self.run_case(normal_success=True)
        self.assertFalse(unplaced)
        self.assertEqual(len(calls), 1)

    def test_shift_does_not_trim_unresolved_audio_without_preceding_context(self):
        lyrics = parse_plain_lyrics('[VERSE]\n前\n失われた歌詞\n次の歌詞\n')
        anchors = (AlignedLyric(lyrics[0], 0, 100), AlignedLyric(lyrics[2], 800, 900))
        calls = []

        class Backend:
            def transcribe(self, audio, **kwargs):
                calls.append(audio[0])
                return result(('次の歌詞', 0.8, 0.9))

        _, unplaced, stats = recover_unplaced_lyrics(
            lyrics, anchors, range(1100 * 16), Backend(), language='ja', device='cpu',
            voiced_intervals=(), sample_rate=16000, audio_duration_ms=1100,
        )
        self.assertEqual([s.text for s in unplaced], ['失われた歌詞'])
        self.assertEqual(stats.recovered_segments, 0)
        self.assertEqual(calls, [0, 0])


if __name__ == '__main__':
    unittest.main()
