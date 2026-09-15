"""Ordered exact alignment of atomic lyrics against Whisper word timestamps."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .errors import LyricSegmentationError
from .plain import SourceLyricSegment, normalize_match_text
from .vad import VoicedInterval


@dataclass(frozen=True, slots=True)
class WhisperWord:
    text: str
    normalized: str
    start_ms: int
    end_ms: int
    source_order: int


@dataclass(frozen=True, slots=True)
class AlignedLyric:
    source: SourceLyricSegment
    start_ms: int
    end_ms: int
    word_boundaries: tuple[tuple[int, int], ...] = ()


def extract_whisper_words(
    result: dict[str, Any], *, audio_duration_ms: int
) -> tuple[WhisperWord, ...]:
    segments = result.get("segments")
    if not isinstance(segments, list):
        raise LyricSegmentationError("Whisper result has no segments array")
    words: list[WhisperWord] = []
    order = 0
    missing = False
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        raw_words = segment.get("words")
        if not isinstance(raw_words, list):
            if str(segment.get("text", "")).strip():
                missing = True
            continue
        for raw in raw_words:
            order += 1
            if not isinstance(raw, dict):
                continue
            text = raw.get("word")
            start = raw.get("start")
            end = raw.get("end")
            if (
                not isinstance(text, str)
                or not isinstance(start, (int, float))
                or isinstance(start, bool)
                or not isinstance(end, (int, float))
                or isinstance(end, bool)
                or not math.isfinite(float(start))
                or not math.isfinite(float(end))
            ):
                continue
            start_ms = round(float(start) * 1000)
            end_ms = round(float(end) * 1000)
            normalized = normalize_match_text(text)
            if normalized and 0 <= start_ms < end_ms <= audio_duration_ms:
                words.append(WhisperWord(text, normalized, start_ms, end_ms, order))
    if missing or (any(str(item.get("text", "")).strip() for item in segments if isinstance(item, dict)) and not words):
        raise LyricSegmentationError(
            "Whisper returned text without usable word_timestamps"
        )
    return tuple(sorted(words, key=lambda item: (item.start_ms, item.source_order)))


def _position_ms(
    words: tuple[WhisperWord, ...],
    offsets: list[int],
    position: int,
    *,
    end_boundary: bool,
) -> int:
    for index, word in enumerate(words):
        start = offsets[index]
        end = offsets[index + 1]
        if end_boundary and position == end:
            return word.end_ms
        if position < end or (position == end and index == len(words) - 1):
            fraction = min(max(position - start, 0), end - start) / (end - start)
            return round(word.start_ms + fraction * (word.end_ms - word.start_ms))
    return words[-1].end_ms


def _bind_to_vad(
    start_ms: int,
    end_ms: int,
    intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
    audio_duration_ms: int,
) -> tuple[int, int]:
    if not intervals:
        return start_ms, end_ms
    start_sample = round(start_ms * sample_rate / 1000)
    end_sample = round(end_ms * sample_rate / 1000)
    overlaps = [
        interval
        for interval in intervals
        if interval.end_sample > start_sample and interval.start_sample < end_sample
    ]
    if not overlaps:
        return start_ms, end_ms
    start_sample = max(start_sample, overlaps[0].start_sample)
    end_sample = min(end_sample, overlaps[-1].end_sample)
    bound_start = round(start_sample * 1000 / sample_rate)
    bound_end = round(end_sample * 1000 / sample_rate)
    bound_start = min(max(0, bound_start), audio_duration_ms - 1)
    bound_end = min(max(bound_start + 1, bound_end), audio_duration_ms)
    return bound_start, bound_end


def align_lyrics(
    lyrics: tuple[SourceLyricSegment, ...],
    words: tuple[WhisperWord, ...],
    *,
    voiced_intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
    audio_duration_ms: int,
) -> tuple[tuple[AlignedLyric, ...], tuple[SourceLyricSegment, ...]]:
    if not words:
        return (), lyrics
    offsets = [0]
    parts: list[str] = []
    for word in words:
        parts.append(word.normalized)
        offsets.append(offsets[-1] + len(word.normalized))
    stream = "".join(parts)
    cursor = 0
    resolved: list[AlignedLyric] = []
    unplaced: list[SourceLyricSegment] = []
    for lyric in lyrics:
        found = stream.find(lyric.normalized, cursor)
        if found < 0:
            unplaced.append(lyric)
            continue
        match_end = found + len(lyric.normalized)
        start_ms = _position_ms(words, offsets, found, end_boundary=False)
        end_ms = _position_ms(words, offsets, match_end, end_boundary=True)
        start_ms, end_ms = _bind_to_vad(
            start_ms,
            end_ms,
            voiced_intervals,
            sample_rate,
            audio_duration_ms,
        )
        if end_ms <= start_ms:
            if start_ms < audio_duration_ms:
                end_ms = start_ms + 1
            else:
                unplaced.append(lyric)
                continue
        normalized_to_source_end: list[int] = []
        for source_index, character in enumerate(lyric.text):
            normalized_to_source_end.extend(
                [source_index + 1] * len(normalize_match_text(character))
            )
        word_boundaries: list[tuple[int, int]] = []
        for stream_boundary in offsets[1:-1]:
            if not found < stream_boundary < match_end:
                continue
            local_boundary = stream_boundary - found
            if not 0 < local_boundary <= len(normalized_to_source_end):
                continue
            text_index = normalized_to_source_end[local_boundary - 1]
            if not 0 < text_index < len(lyric.text):
                continue
            boundary_ms = _position_ms(
                words, offsets, stream_boundary, end_boundary=True
            )
            candidate = (text_index, boundary_ms)
            if not word_boundaries or candidate != word_boundaries[-1]:
                word_boundaries.append(candidate)
        resolved.append(
            AlignedLyric(lyric, start_ms, end_ms, tuple(word_boundaries))
        )
        cursor = match_end
    return tuple(resolved), tuple(unplaced)
