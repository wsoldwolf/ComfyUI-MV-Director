"""A focused evidence-only retry must not bypass guided anchor validation."""
import unittest

from core.lyrics import AlignedLyric, parse_plain_lyrics, recover_unplaced_lyrics


def transcript(*rows):
    return {"segments": [{"text": "".join(text for text, _, _ in rows),
                          "words": [{"word": text, "start": start, "end": end}
                                    for text, start, end in rows]}]}


class Transcriber:
    def __init__(self, *results):
        self.results = results
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({**kwargs, "samples": len(audio)})
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def recover(lyrics, resolved, backend, duration=10000):
    return recover_unplaced_lyrics(
        lyrics, resolved, [0.0] * (duration * 16), backend,
        language="ja", device="cpu", voiced_intervals=(), sample_rate=16000,
        audio_duration_ms=duration,
    )


class FocusedRecoveryTests(unittest.TestCase):
    def test_skipped_opening_gets_one_short_prompt_free_evidence_decode(self):
        lyrics = parse_plain_lyrics("[INTRO]\nくるり　ふわり\n次の歌詞\n")
        anchor = AlignedLyric(lyrics[2], 7000, 7500)
        backend = Transcriber(
            transcript(("次の歌詞", 7, 7.5)),
            transcript(("くるり", 2, 2.5), ("ふわり", 2.5, 3), ("次の歌詞", 7, 7.5)),
            transcript(("くるり", 1, 1.5), ("ふわり", 1.5, 2)),
        )
        resolved, missing, stats = recover(lyrics, (anchor,), backend)
        self.assertFalse(missing)
        self.assertEqual([(i.start_ms, i.end_ms) for i in resolved],
                         [(2000, 2500), (2500, 3000), (7000, 7500)])
        self.assertEqual(resolved[-1], anchor)
        self.assertEqual(stats.recovered_segments, 2)
        self.assertEqual(len(backend.calls), 3)
        self.assertEqual(backend.calls[-1]["samples"], 6500 * 16)
        self.assertEqual(backend.calls[-1]["initial_prompt"], "")
        self.assertFalse(backend.calls[-1]["condition_on_previous_text"])

    def test_internal_slice_keeps_absolute_offsets_and_omits_preceding_text(self):
        lyrics = parse_plain_lyrics("[VERSE]\n前の歌詞\n対象歌詞\n次の歌詞\n")
        before = AlignedLyric(lyrics[0], 9000, 10000)
        after = AlignedLyric(lyrics[2], 14000, 14500)
        # Existing retry slice starts at 8s; focused window starts at 9s.
        backend = Transcriber(
            transcript(("次の歌詞", 6, 6.5)),
            transcript(("対象歌詞", 2.2, 3.2), ("次の歌詞", 6, 6.5)),
            transcript(("対象歌詞", 1.2, 2.2)),
        )
        resolved, missing, _ = recover(lyrics, (before, after), backend, duration=16000)
        self.assertFalse(missing)
        self.assertEqual((resolved[1].start_ms, resolved[1].end_ms), (10200, 11200))
        self.assertEqual((resolved[0], resolved[-1]), (before, after))
        self.assertEqual(backend.calls[0]["initial_prompt"], "前の歌詞")
        self.assertEqual(backend.calls[-1]["initial_prompt"], "")
        self.assertEqual(backend.calls[-1]["samples"], 5500 * 16)

    def test_no_word_evidence_or_timestampless_decode_never_accepts_guided_text(self):
        lyrics = parse_plain_lyrics("[INTRO]\n存在しない歌詞\n次の歌詞\n")
        anchor = AlignedLyric(lyrics[1], 7000, 7500)
        for extra in (transcript(), {"segments": [{"text": "存在しない歌詞"}]},
                      transcript(("無関係", 5, 5.5))):
            with self.subTest(extra=extra):
                backend = Transcriber(
                    transcript(("次の歌詞", 7, 7.5)),
                    transcript(("存在しない歌詞", 2, 3), ("次の歌詞", 7, 7.5)),
                    extra,
                )
                with self.assertLogs("mv_director.lyrics", level="WARNING"):
                    resolved, missing, stats = recover(lyrics, (anchor,), backend)
                self.assertEqual(resolved, (anchor,))
                self.assertEqual(missing, (lyrics[0],))
                self.assertEqual(stats.recovered_segments, 0)
                self.assertEqual(len(backend.calls), 3)

    def test_missing_following_anchor_is_not_relaxed(self):
        lyrics = parse_plain_lyrics("[INTRO]\n対象歌詞\n次の歌詞\n")
        anchor = AlignedLyric(lyrics[1], 7000, 7500)
        backend = Transcriber(transcript(("次の歌詞", 7, 7.5)),
                              transcript(("対象歌詞", 2, 3)))
        with self.assertLogs("mv_director.lyrics", level="WARNING"):
            resolved, missing, _ = recover(lyrics, (anchor,), backend)
        self.assertEqual(resolved, (anchor,))
        self.assertEqual(missing, (lyrics[0],))
        self.assertEqual(len(backend.calls), 2)

    def test_no_following_anchor_does_not_enable_focused_decode(self):
        lyrics = parse_plain_lyrics("[OUTRO]\n対象歌詞\n")
        backend = Transcriber(transcript(("別の音", 7, 7.5)),
                              transcript(("対象歌詞", 2, 3)))
        with self.assertLogs("mv_director.lyrics", level="WARNING"):
            resolved, missing, _ = recover(lyrics, (), backend)
        self.assertFalse(resolved)
        self.assertEqual(missing, lyrics)
        self.assertEqual(len(backend.calls), 2)

    def test_successful_normal_retry_has_no_additional_decode(self):
        lyrics = parse_plain_lyrics("[INTRO]\n対象歌詞\n次の歌詞\n")
        backend = Transcriber(transcript(("対象歌詞", 2, 3), ("次の歌詞", 7, 7.5)))
        resolved, missing, _ = recover(lyrics, (AlignedLyric(lyrics[1], 7000, 7500),), backend)
        self.assertFalse(missing)
        self.assertEqual(len(resolved), 2)
        self.assertEqual(len(backend.calls), 1)


if __name__ == "__main__":
    unittest.main()
