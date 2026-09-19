"""Conservative monotonic alignment against real Whisper word timestamps."""

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


@dataclass(frozen=True, slots=True)
class _WordCandidate:
    score: float
    start_index: int
    end_index: int


def build_whisper_initial_prompt(
    lyrics: tuple[SourceLyricSegment, ...],
    *,
    max_lines: int = 12,
    max_characters: int = 160,
) -> str:
    """Build a bounded opening hint without treating it as transcript truth."""

    if max_lines < 1 or max_characters < 1:
        raise ValueError("Whisper initial-prompt limits must be positive")
    grouped: list[str] = []
    current_line: int | None = None
    current_parts: list[str] = []
    for lyric in lyrics:
        if current_line is not None and lyric.source_line != current_line:
            grouped.append("\u3000".join(current_parts))
            current_parts = []
        current_line = lyric.source_line
        current_parts.append(lyric.text)
    if current_parts:
        grouped.append("\u3000".join(current_parts))

    selected: list[str] = []
    for line in grouped[:max_lines]:
        candidate = "\n".join((*selected, line))
        if len(candidate) <= max_characters:
            selected.append(line)
            continue
        if not selected:
            selected.append(line[:max_characters])
        break
    return "\n".join(selected)


def extract_whisper_words(
    result: dict[str, Any],
    *,
    audio_duration_ms: int,
    allow_partial_word_timestamps: bool = False,
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
    has_text = any(
        str(item.get("text", "")).strip()
        for item in segments
        if isinstance(item, dict)
    )
    if (missing and not allow_partial_word_timestamps) or (has_text and not words):
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


def levenshtein_distance(left: str, right: str) -> int:
    """Return the exact edit distance used by the japanese2json prototype."""

    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def match_similarity(left: str, right: str) -> float:
    denominator = max(len(left), len(right))
    if denominator == 0:
        return 1.0
    return 1.0 - levenshtein_distance(left, right) / denominator


def _word_candidates(
    lyric: str,
    words: tuple[WhisperWord, ...],
    *,
    start_index: int,
    end_index: int,
    maximum_start_ms: int,
    maximum_span_ms: int,
) -> tuple[_WordCandidate, ...]:
    if start_index >= end_index or start_index >= len(words):
        return ()
    end_index = min(end_index, len(words))
    lyric_length = len(lyric)
    minimum_chars = max(1, math.floor(lyric_length * 0.4))
    maximum_chars = math.ceil(lyric_length * 2.5) + 8
    candidates: list[_WordCandidate] = []
    for word_start in range(start_index, end_index):
        first = words[word_start]
        if first.start_ms > maximum_start_ms:
            break
        candidate_text = ""
        for word_end in range(word_start, end_index):
            word = words[word_end]
            if word.end_ms - first.start_ms > maximum_span_ms:
                break
            candidate_text += word.normalized
            candidate_length = len(candidate_text)
            if candidate_length < minimum_chars:
                continue
            if candidate_length > maximum_chars:
                break
            candidates.append(
                _WordCandidate(
                    match_similarity(lyric, candidate_text),
                    word_start,
                    word_end,
                )
            )
    return tuple(candidates)


def _best_word_candidate(
    lyric: str,
    words: tuple[WhisperWord, ...],
    *,
    start_index: int,
    end_index: int,
    maximum_start_ms: int,
    maximum_span_ms: int,
) -> _WordCandidate | None:
    best: _WordCandidate | None = None
    for proposal in _word_candidates(
        lyric,
        words,
        start_index=start_index,
        end_index=end_index,
        maximum_start_ms=maximum_start_ms,
        maximum_span_ms=maximum_span_ms,
    ):
        if best is None or proposal.score > best.score + 1e-12:
            best = proposal
            continue
        if abs(proposal.score - best.score) > 1e-12:
            continue
        best_word_count = best.end_index - best.start_index + 1
        proposal_word_count = proposal.end_index - proposal.start_index + 1
        if proposal.start_index < best.start_index or (
            proposal.start_index == best.start_index
            and proposal_word_count < best_word_count
        ):
            best = proposal
    return best


def _best_supported_repeated_candidate(
    lyrics: tuple[SourceLyricSegment, ...],
    lyric_index: int,
    words: tuple[WhisperWord, ...],
    *,
    start_index: int,
    end_index: int,
    maximum_start_ms: int,
    maximum_span_ms: int,
    match_threshold: float,
) -> _WordCandidate | None:
    following = lyrics[lyric_index + 1 : lyric_index + 5]
    if not following:
        return _best_word_candidate(
            lyrics[lyric_index].normalized,
            words,
            start_index=start_index,
            end_index=end_index,
            maximum_start_ms=maximum_start_ms,
            maximum_span_ms=maximum_span_ms,
        )
    best: _WordCandidate | None = None
    best_rank: tuple[int, float, int, float] | None = None
    for candidate in _word_candidates(
        lyrics[lyric_index].normalized,
        words,
        start_index=start_index,
        end_index=end_index,
        maximum_start_ms=maximum_start_ms,
        maximum_span_ms=maximum_span_ms,
    ):
        if candidate.score < match_threshold:
            continue
        support_cursor = candidate.end_index + 1
        support_count = 0
        support_score = 0.0
        support_anchor_ms = words[candidate.end_index].end_ms
        for following_offset, next_lyric in enumerate(following):
            support = _best_word_candidate(
                next_lyric.normalized,
                words,
                start_index=support_cursor,
                end_index=end_index,
                maximum_start_ms=support_anchor_ms + 20_000,
                maximum_span_ms=20_000,
            )
            if support is None or support.score < match_threshold:
                if following_offset == 0:
                    break
                continue
            support_count += 1
            support_score += support.score
            support_cursor = support.end_index + 1
            support_anchor_ms = words[support.end_index].end_ms
        if support_count == 0:
            continue
        rank = (
            support_count,
            support_score,
            -candidate.start_index,
            candidate.score,
        )
        if best_rank is None or rank > best_rank:
            best = candidate
            best_rank = rank
    return best


def _candidate_better_fits_following(
    lyrics: tuple[SourceLyricSegment, ...],
    lyric_index: int,
    candidate: _WordCandidate,
    words: tuple[WhisperWord, ...],
) -> bool:
    if lyric_index + 1 >= len(lyrics):
        return False
    current = lyrics[lyric_index]
    following = lyrics[lyric_index + 1]
    if current.normalized == following.normalized:
        return False
    text = "".join(
        word.normalized
        for word in words[candidate.start_index : candidate.end_index + 1]
    )
    return match_similarity(following.normalized, text) >= candidate.score + 0.15


def _has_resync_support(
    lyrics: tuple[SourceLyricSegment, ...],
    lyric_index: int,
    candidate: _WordCandidate,
    words: tuple[WhisperWord, ...],
    *,
    match_threshold: float,
) -> bool:
    support_start = candidate.end_index + 1
    if support_start >= len(words):
        return False
    anchor_ms = words[candidate.end_index].end_ms
    for next_lyric in lyrics[lyric_index + 1 : lyric_index + 4]:
        support = _best_word_candidate(
            next_lyric.normalized,
            words,
            start_index=support_start,
            end_index=len(words),
            maximum_start_ms=anchor_ms + 20_000,
            maximum_span_ms=20_000,
        )
        if support is not None and support.score >= match_threshold:
            return True
    return False


def _contains_voiced_midpoint(
    word: WhisperWord,
    intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
) -> bool:
    midpoint = round((word.start_ms + word.end_ms) * sample_rate / 2000)
    return any(
        interval.start_sample <= midpoint < interval.end_sample
        for interval in intervals
    )


def _word_boundaries(
    lyric: SourceLyricSegment,
    candidate: _WordCandidate,
    words: tuple[WhisperWord, ...],
) -> tuple[tuple[int, int], ...]:
    selected = words[candidate.start_index : candidate.end_index + 1]
    if len(selected) < 2:
        return ()
    normalized_to_source_end: list[int] = []
    for source_index, character in enumerate(lyric.text):
        normalized_to_source_end.extend(
            [source_index + 1] * len(normalize_match_text(character))
        )
    candidate_length = sum(len(word.normalized) for word in selected)
    if not normalized_to_source_end or candidate_length < 1:
        return ()
    consumed = 0
    boundaries: list[tuple[int, int]] = []
    for word in selected[:-1]:
        consumed += len(word.normalized)
        normalized_position = round(
            consumed * len(normalized_to_source_end) / candidate_length
        )
        if not 0 < normalized_position <= len(normalized_to_source_end):
            continue
        text_index = normalized_to_source_end[normalized_position - 1]
        candidate_boundary = (text_index, word.end_ms)
        if (
            0 < text_index < len(lyric.text)
            and (not boundaries or candidate_boundary != boundaries[-1])
        ):
            boundaries.append(candidate_boundary)
    return tuple(boundaries)


def _resolve_candidate(
    lyric: SourceLyricSegment,
    candidate: _WordCandidate,
    words: tuple[WhisperWord, ...],
    *,
    previous_end_ms: int,
    maximum_end_ms: int,
    voiced_intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
    audio_duration_ms: int,
) -> AlignedLyric | None:
    start_ms = max(previous_end_ms, words[candidate.start_index].start_ms)
    end_ms = min(maximum_end_ms, words[candidate.end_index].end_ms)
    start_ms, end_ms = _bind_to_vad(
        start_ms,
        end_ms,
        voiced_intervals,
        sample_rate,
        audio_duration_ms,
    )
    if end_ms <= start_ms:
        return None
    return AlignedLyric(
        lyric,
        start_ms,
        end_ms,
        _word_boundaries(lyric, candidate, words),
    )


def _source_line_groups(
    lyrics: tuple[SourceLyricSegment, ...],
) -> tuple[tuple[int, int], ...]:
    """Return half-open ranges for atomic segments from the same source line."""

    if not lyrics:
        return ()
    groups: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(lyrics)):
        if lyrics[index].source_line != lyrics[start].source_line:
            groups.append((start, index))
            start = index
    groups.append((start, len(lyrics)))
    return tuple(groups)


def _source_line_proxy(
    lyrics: tuple[SourceLyricSegment, ...], start: int, end: int
) -> SourceLyricSegment:
    parts = lyrics[start:end]
    first = parts[0]
    last = parts[-1]
    return SourceLyricSegment(
        segment_id=first.segment_id,
        text="\u3000".join(part.text for part in parts),
        section=first.section,
        source_line=first.source_line,
        source_start=first.source_start,
        source_end=last.source_end,
        normalized="".join(part.normalized for part in parts),
    )


def _normalized_source_ends(text: str) -> list[int]:
    result: list[int] = []
    for source_index, character in enumerate(text):
        result.extend([source_index + 1] * len(normalize_match_text(character)))
    return result


def _split_source_line_candidate(
    lyrics: tuple[SourceLyricSegment, ...],
    start: int,
    end: int,
    candidate: _WordCandidate,
    words: tuple[WhisperWord, ...],
    line_alignment: AlignedLyric,
) -> tuple[AlignedLyric, ...] | None:
    """Split one securely aligned physical line back into its atomic segments."""

    parts = lyrics[start:end]
    selected = words[candidate.start_index : candidate.end_index + 1]
    source_length = sum(len(part.normalized) for part in parts)
    candidate_offsets = [0]
    for word in selected:
        candidate_offsets.append(candidate_offsets[-1] + len(word.normalized))
    candidate_length = candidate_offsets[-1]
    if source_length < 1 or candidate_length < 1:
        return None

    source_offsets = [0]
    for part in parts:
        source_offsets.append(source_offsets[-1] + len(part.normalized))

    result: list[AlignedLyric] = []
    previous_end = line_alignment.start_ms
    for part_index, part in enumerate(parts):
        source_start = source_offsets[part_index]
        source_end = source_offsets[part_index + 1]
        candidate_start = round(source_start * candidate_length / source_length)
        candidate_end = round(source_end * candidate_length / source_length)
        if part_index == 0:
            start_ms = line_alignment.start_ms
        else:
            start_ms = max(
                line_alignment.start_ms,
                _position_ms(
                    selected,
                    candidate_offsets,
                    candidate_start,
                    end_boundary=False,
                ),
            )
        if part_index == len(parts) - 1:
            end_ms = line_alignment.end_ms
        else:
            end_ms = min(
                line_alignment.end_ms,
                _position_ms(
                    selected,
                    candidate_offsets,
                    candidate_end,
                    end_boundary=True,
                ),
            )
        start_ms = max(start_ms, previous_end)
        if end_ms <= start_ms:
            return None

        normalized_to_source_end = _normalized_source_ends(part.text)
        boundaries: list[tuple[int, int]] = []
        for word_index, word_end in enumerate(candidate_offsets[1:-1]):
            source_position = round(word_end * source_length / candidate_length)
            if not source_start < source_position < source_end:
                continue
            local_position = source_position - source_start
            if not 0 < local_position <= len(normalized_to_source_end):
                continue
            text_index = normalized_to_source_end[local_position - 1]
            boundary_ms = selected[word_index].end_ms
            boundary = (text_index, boundary_ms)
            if (
                0 < text_index < len(part.text)
                and start_ms < boundary_ms < end_ms
                and (not boundaries or boundary != boundaries[-1])
            ):
                boundaries.append(boundary)
        result.append(AlignedLyric(part, start_ms, end_ms, tuple(boundaries)))
        previous_end = end_ms
    return tuple(result)


def _recover_atomic_segments_from_source_lines(
    lyrics: tuple[SourceLyricSegment, ...],
    words: tuple[WhisperWord, ...],
    results: list[AlignedLyric | None],
    spans: list[tuple[int, int] | None],
    *,
    match_threshold: float,
    neighbor_match_threshold: float,
    initial_search_ms: int,
    anchored_search_ms: int,
    voiced_intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
    audio_duration_ms: int,
) -> None:
    """Recover split lyrics by matching their complete physical source line.

    Whisper frequently emits a complete sung line as one timestamped word.  An
    atomic half-line can then score below the fuzzy threshold even though the
    complete source line is an exact match.  We only replace a partially
    resolved multi-segment line, and bound the rescue by resolved neighboring
    lines, so missing lyrics are never assigned fabricated times.
    """

    for start, end in _source_line_groups(lyrics):
        if end - start < 2 or all(
            results[index] is not None for index in range(start, end)
        ):
            continue

        previous_index = next(
            (index for index in range(start - 1, -1, -1) if spans[index] is not None),
            None,
        )
        next_index = next(
            (index for index in range(end, len(lyrics)) if spans[index] is not None),
            None,
        )
        word_start = spans[previous_index][1] + 1 if previous_index is not None else 0
        word_end = spans[next_index][0] if next_index is not None else len(words)
        if word_start >= word_end:
            continue
        previous_end_ms = (
            results[previous_index].end_ms if previous_index is not None else 0
        )
        maximum_end_ms = (
            results[next_index].start_ms
            if next_index is not None
            else audio_duration_ms
        )
        search_ms = anchored_search_ms if previous_index is not None else initial_search_ms
        maximum_start_ms = min(audio_duration_ms, previous_end_ms + search_ms)
        if next_index is not None:
            maximum_start_ms = min(maximum_start_ms, maximum_end_ms)

        proxy = _source_line_proxy(lyrics, start, end)
        candidate = _best_word_candidate(
            proxy.normalized,
            words,
            start_index=word_start,
            end_index=word_end,
            maximum_start_ms=maximum_start_ms,
            maximum_span_ms=anchored_search_ms,
        )
        recovery_threshold = (
            neighbor_match_threshold
            if previous_index is not None and next_index is not None
            else match_threshold
        )
        if candidate is None or candidate.score < recovery_threshold:
            continue
        existing_spans = [
            spans[index]
            for index in range(start, end)
            if spans[index] is not None
        ]
        if existing_spans and (
            candidate.start_index > min(span[0] for span in existing_spans)
            or candidate.end_index < max(span[1] for span in existing_spans)
        ):
            continue
        line_alignment = _resolve_candidate(
            proxy,
            candidate,
            words,
            previous_end_ms=previous_end_ms,
            maximum_end_ms=maximum_end_ms,
            voiced_intervals=voiced_intervals,
            sample_rate=sample_rate,
            audio_duration_ms=audio_duration_ms,
        )
        if line_alignment is None:
            continue
        recovered = _split_source_line_candidate(
            lyrics,
            start,
            end,
            candidate,
            words,
            line_alignment,
        )
        if recovered is None:
            continue
        for offset, item in enumerate(recovered):
            results[start + offset] = item
            spans[start + offset] = (candidate.start_index, candidate.end_index)


def align_lyrics(
    lyrics: tuple[SourceLyricSegment, ...],
    words: tuple[WhisperWord, ...],
    *,
    voiced_intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
    audio_duration_ms: int,
    match_threshold: float = 0.55,
    neighbor_match_threshold: float = 0.45,
    initial_search_ms: int = 60_000,
    anchored_search_ms: int = 20_000,
) -> tuple[tuple[AlignedLyric, ...], tuple[SourceLyricSegment, ...]]:
    if not 0.0 <= match_threshold <= 1.0:
        raise ValueError("match_threshold must be in 0.0..1.0")
    if not 0.0 <= neighbor_match_threshold <= match_threshold:
        raise ValueError(
            "neighbor_match_threshold must be in 0.0..match_threshold"
        )
    if initial_search_ms < 1 or anchored_search_ms < 1:
        raise ValueError("alignment search windows must be positive")
    if not words:
        return (), lyrics
    usable_words = (
        tuple(
            word
            for word in words
            if _contains_voiced_midpoint(word, voiced_intervals, sample_rate)
        )
        if voiced_intervals
        else words
    )
    if not usable_words:
        return (), lyrics
    cursor = 0
    anchor_ms = 0
    previous_end_ms = 0
    has_primary_anchor = False
    results: list[AlignedLyric | None] = []
    spans: list[tuple[int, int] | None] = []
    occurrences: dict[str, int] = {}
    for lyric in lyrics:
        occurrences[lyric.normalized] = occurrences.get(lyric.normalized, 0) + 1

    for lyric_index, lyric in enumerate(lyrics):
        search_ms = (
            anchored_search_ms if has_primary_anchor else initial_search_ms
        )
        best = _best_word_candidate(
            lyric.normalized,
            usable_words,
            start_index=cursor,
            end_index=len(usable_words),
            maximum_start_ms=anchor_ms + search_ms,
            maximum_span_ms=search_ms,
        )
        if occurrences[lyric.normalized] > 1:
            supported = _best_supported_repeated_candidate(
                lyrics,
                lyric_index,
                usable_words,
                start_index=cursor,
                end_index=len(usable_words),
                maximum_start_ms=anchor_ms + search_ms,
                maximum_span_ms=search_ms,
                match_threshold=match_threshold,
            )
            if supported is not None:
                best = supported
            elif best is not None and best.score >= match_threshold:
                results.append(None)
                spans.append(None)
                continue
        if (
            best is not None
            and best.score >= match_threshold
            and _candidate_better_fits_following(
                lyrics, lyric_index, best, usable_words
            )
        ):
            results.append(None)
            spans.append(None)
            continue
        if (
            has_primary_anchor
            and (best is None or best.score < match_threshold)
            and occurrences[lyric.normalized] == 1
            and len(lyric.normalized) >= 8
            and initial_search_ms > anchored_search_ms
        ):
            broad = _best_word_candidate(
                lyric.normalized,
                usable_words,
                start_index=cursor,
                end_index=len(usable_words),
                maximum_start_ms=anchor_ms + initial_search_ms,
                maximum_span_ms=initial_search_ms,
            )
            if (
                broad is not None
                and broad.score >= max(match_threshold, 0.8)
                and _has_resync_support(
                    lyrics,
                    lyric_index,
                    broad,
                    usable_words,
                    match_threshold=match_threshold,
                )
            ):
                best = broad
        if best is None or best.score < match_threshold:
            results.append(None)
            spans.append(None)
            continue
        resolved_item = _resolve_candidate(
            lyric,
            best,
            usable_words,
            previous_end_ms=previous_end_ms,
            maximum_end_ms=audio_duration_ms,
            voiced_intervals=voiced_intervals,
            sample_rate=sample_rate,
            audio_duration_ms=audio_duration_ms,
        )
        if resolved_item is None:
            results.append(None)
            spans.append(None)
            continue
        results.append(resolved_item)
        spans.append((best.start_index, best.end_index))
        cursor = best.end_index + 1
        previous_end_ms = resolved_item.end_ms
        anchor_ms = resolved_item.end_ms
        has_primary_anchor = True

    previous_anchor: int | None = None
    for next_anchor, item in enumerate(results):
        if item is None:
            continue
        if previous_anchor is not None and next_anchor > previous_anchor + 1:
            previous_span = spans[previous_anchor]
            next_span = spans[next_anchor]
            if previous_span is None or next_span is None:
                raise LyricSegmentationError(
                    "resolved lyric alignment has no Whisper word span"
                )
            gap_cursor = previous_span[1] + 1
            gap_end = next_span[0]
            neighbor_previous_end = results[previous_anchor].end_ms
            neighbor_maximum_end = item.start_ms
            for pending_index in range(previous_anchor + 1, next_anchor):
                pending = lyrics[pending_index]
                candidate = _best_word_candidate(
                    pending.normalized,
                    usable_words,
                    start_index=gap_cursor,
                    end_index=gap_end,
                    maximum_start_ms=neighbor_maximum_end,
                    maximum_span_ms=initial_search_ms,
                )
                if (
                    candidate is None
                    or candidate.score < neighbor_match_threshold
                ):
                    continue
                recovered = _resolve_candidate(
                    pending,
                    candidate,
                    usable_words,
                    previous_end_ms=neighbor_previous_end,
                    maximum_end_ms=neighbor_maximum_end,
                    voiced_intervals=voiced_intervals,
                    sample_rate=sample_rate,
                    audio_duration_ms=audio_duration_ms,
                )
                if recovered is None:
                    continue
                results[pending_index] = recovered
                spans[pending_index] = (
                    candidate.start_index,
                    candidate.end_index,
                )
                gap_cursor = candidate.end_index + 1
                neighbor_previous_end = recovered.end_ms
        previous_anchor = next_anchor

    _recover_atomic_segments_from_source_lines(
        lyrics,
        usable_words,
        results,
        spans,
        match_threshold=match_threshold,
        neighbor_match_threshold=neighbor_match_threshold,
        initial_search_ms=initial_search_ms,
        anchored_search_ms=anchored_search_ms,
        voiced_intervals=voiced_intervals,
        sample_rate=sample_rate,
        audio_duration_ms=audio_duration_ms,
    )

    resolved = tuple(item for item in results if item is not None)
    unplaced = tuple(
        lyric for lyric, item in zip(lyrics, results) if item is None
    )
    return resolved, unplaced
