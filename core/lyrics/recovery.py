"""Bounded Whisper retries for lyric ranges missed by the full-track decode."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Any, Protocol

from .alignment import AlignedLyric, WhisperWord, align_lyrics, extract_whisper_words
from .errors import LyricSegmentationError
from .plain import SourceLyricSegment
from .vad import VoicedInterval


_WHISPER_SAMPLE_RATE = 16_000
_WINDOW_MS = 12_000
_WINDOW_OVERLAP_MS = 2_000
_CONTEXT_BEFORE_MS = 2_000
_CONTEXT_AFTER_MS = 1_000
_ADAPTIVE_PREFIX_LEAD_MS = 3_000
_DUPLICATE_CENTER_MS = 350
_MIN_ANCHOR_OVERLAP_RATIO = 0.5
_MAX_REFINEMENT_PASSES = 8
_PROMPT_MAX_LINES = 12
_PROMPT_MAX_CHARACTERS = 160
_LOGGER = logging.getLogger("mv_director.lyrics")


class _Transcriber(Protocol):
    def transcribe(
        self,
        audio: Any,
        *,
        language: str,
        device: str,
        initial_prompt: str = "",
        condition_on_previous_text: bool = False,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class TargetedRetryStats:
    attempted_runs: int = 0
    recovered_segments: int = 0


def _unresolved_runs(
    slots: list[AlignedLyric | None],
) -> tuple[tuple[int, int], ...]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(len(slots) + 1):
        unresolved = index < len(slots) and slots[index] is None
        if unresolved and start is None:
            start = index
        elif not unresolved and start is not None:
            runs.append((start, index))
            start = None
    return tuple(runs)


def _windows(duration_ms: int) -> tuple[tuple[int, int], ...]:
    if duration_ms <= _WINDOW_MS:
        return ((0, duration_ms),)
    result: list[tuple[int, int]] = []
    start = 0
    while start < duration_ms:
        end = min(start + _WINDOW_MS, duration_ms)
        result.append((start, end))
        if end >= duration_ms:
            break
        start = end - _WINDOW_OVERLAP_MS
    return tuple(result)


def _line_texts(
    lyrics: tuple[SourceLyricSegment, ...],
) -> dict[int, str]:
    grouped: dict[int, list[str]] = {}
    for lyric in lyrics:
        grouped.setdefault(lyric.source_line, []).append(lyric.text)
    return {
        source_line: "\u3000".join(parts)
        for source_line, parts in grouped.items()
    }


def _run_line_texts(
    lyrics: tuple[SourceLyricSegment, ...],
    line_texts: dict[int, str],
) -> list[str]:
    result: list[str] = []
    seen: set[int] = set()
    for lyric in lyrics:
        if lyric.source_line in seen:
            continue
        seen.add(lyric.source_line)
        result.append(line_texts[lyric.source_line])
    return result


def _bounded_prompt(lines: list[str]) -> str:
    selected: list[str] = []
    for line in reversed(lines):
        candidate = "\n".join([line, *selected])
        if (
            len(selected) < _PROMPT_MAX_LINES
            and len(candidate) <= _PROMPT_MAX_CHARACTERS
        ):
            selected.insert(0, line)
            continue
        break
    if selected:
        return "\n".join(selected)
    return lines[-1][-_PROMPT_MAX_CHARACTERS:] if lines else ""


def _window_prompt(
    run_lines: list[str],
    *,
    preceding_line: str,
    window_start_ms: int,
    duration_ms: int,
    guided: bool,
) -> str:
    prefix = [preceding_line] if preceding_line else []
    if guided:
        complete = [*prefix, *run_lines]
        complete_prompt = "\n".join(complete)
        if (
            len(complete) <= _PROMPT_MAX_LINES
            and len(complete_prompt) <= _PROMPT_MAX_CHARACTERS
        ):
            return complete_prompt
    fraction = min(1.0, max(0.0, window_start_ms / max(duration_ms, 1)))
    if guided:
        approximate = min(
            len(run_lines) - 1,
            math.floor(fraction * len(run_lines)),
        )
        context = [*prefix, *run_lines[: approximate + 1]]
    else:
        approximate = min(len(run_lines), math.floor(fraction * len(run_lines)))
        context = [*prefix, *run_lines[:approximate]]
    return _bounded_prompt(context)


def _merge_words(words: list[WhisperWord]) -> tuple[WhisperWord, ...]:
    ordered = sorted(words, key=lambda item: (item.start_ms, item.source_order))
    merged: list[WhisperWord] = []
    for candidate in ordered:
        center = (candidate.start_ms + candidate.end_ms) / 2
        duplicate: int | None = None
        for index in range(len(merged) - 1, -1, -1):
            existing = merged[index]
            existing_center = (existing.start_ms + existing.end_ms) / 2
            if center - existing_center > _DUPLICATE_CENTER_MS:
                break
            if (
                candidate.normalized == existing.normalized
                and abs(center - existing_center) <= _DUPLICATE_CENTER_MS
            ):
                duplicate = index
                break
        if duplicate is None:
            merged.append(candidate)
        elif (
            candidate.end_ms - candidate.start_ms
            < merged[duplicate].end_ms - merged[duplicate].start_ms
        ):
            merged[duplicate] = candidate
    merged.sort(key=lambda item: (item.start_ms, item.source_order))
    return tuple(
        WhisperWord(
            item.text,
            item.normalized,
            item.start_ms,
            item.end_ms,
            index,
        )
        for index, item in enumerate(merged, 1)
    )


def _local_voiced_intervals(
    intervals: tuple[VoicedInterval, ...],
    *,
    sample_rate: int,
    slice_start_ms: int,
    slice_end_ms: int,
) -> tuple[VoicedInterval, ...]:
    first_sample = round(slice_start_ms * sample_rate / 1000)
    final_sample = round(slice_end_ms * sample_rate / 1000)
    result: list[VoicedInterval] = []
    for interval in intervals:
        start = max(interval.start_sample, first_sample)
        end = min(interval.end_sample, final_sample)
        if end > start:
            result.append(VoicedInterval(start - first_sample, end - first_sample))
    return tuple(result)


def _to_absolute(item: AlignedLyric, offset_ms: int) -> AlignedLyric:
    return AlignedLyric(
        item.source,
        item.start_ms + offset_ms,
        item.end_ms + offset_ms,
        tuple((index, value + offset_ms) for index, value in item.word_boundaries),
    )


def _clip_to_anchor_bounds(
    item: AlignedLyric,
    *,
    start_ms: int,
    end_ms: int,
) -> AlignedLyric | None:
    """Clip small Whisper timestamp spill without accepting another anchor.

    Whisper word timestamps can overlap the end of the preceding lyric or the
    start of the following lyric by a few frames. The textual match remains
    acoustic evidence, but a recovered lyric must occupy mostly its own
    anchor-bounded interval before it is accepted.
    """

    duration_ms = item.end_ms - item.start_ms
    clipped_start_ms = max(start_ms, item.start_ms)
    clipped_end_ms = min(end_ms, item.end_ms)
    overlap_ms = clipped_end_ms - clipped_start_ms
    if (
        duration_ms <= 0
        or overlap_ms <= 0
        or overlap_ms / duration_ms < _MIN_ANCHOR_OVERLAP_RATIO
    ):
        return None
    return AlignedLyric(
        item.source,
        clipped_start_ms,
        clipped_end_ms,
        tuple(
            (index, timestamp)
            for index, timestamp in item.word_boundaries
            if clipped_start_ms < timestamp < clipped_end_ms
        ),
    )


def recover_unplaced_lyrics(
    lyrics: tuple[SourceLyricSegment, ...],
    resolved: tuple[AlignedLyric, ...],
    whisper_audio: Any,
    transcriber: _Transcriber,
    *,
    language: str,
    device: str,
    voiced_intervals: tuple[VoicedInterval, ...],
    sample_rate: int,
    audio_duration_ms: int,
    _refinement_pass: int = 1,
) -> tuple[
    tuple[AlignedLyric, ...],
    tuple[SourceLyricSegment, ...],
    TargetedRetryStats,
]:
    """Retry only unresolved ranges bounded by real aligned timestamps.

    An unguided short-window decode supplies acoustic evidence. A lyric-guided
    decode is accepted only when each proposed interval overlaps that evidence
    and a following lyric anchor remains in place.
    """

    by_id = {item.source.segment_id: item for item in resolved}
    slots: list[AlignedLyric | None] = [
        by_id.get(lyric.segment_id) for lyric in lyrics
    ]
    line_texts = _line_texts(lyrics)
    attempted = 0
    recovered_count = 0

    for run_start, run_end in _unresolved_runs(slots):
        previous = slots[run_start - 1] if run_start > 0 else None
        following = slots[run_end] if run_end < len(slots) else None
        if run_start > 0 and previous is None:
            continue
        anchor_start_ms = previous.end_ms if previous is not None else 0
        anchor_end_ms = following.start_ms if following is not None else audio_duration_ms
        if anchor_end_ms <= anchor_start_ms:
            continue
        slice_start_ms = max(0, anchor_start_ms - _CONTEXT_BEFORE_MS)
        slice_end_ms = min(
            audio_duration_ms,
            following.end_ms + _CONTEXT_AFTER_MS
            if following is not None
            else audio_duration_ms,
        )
        if slice_end_ms <= slice_start_ms:
            continue
        first_sample = math.floor(slice_start_ms * _WHISPER_SAMPLE_RATE / 1000)
        final_sample = min(
            len(whisper_audio),
            math.ceil(slice_end_ms * _WHISPER_SAMPLE_RATE / 1000),
        )
        if final_sample <= first_sample:
            continue

        attempted += 1
        run_lyrics = lyrics[run_start:run_end]
        run_lines = _run_line_texts(run_lyrics, line_texts)
        guided_lines = [lyric.text for lyric in run_lyrics]
        preceding_line = (
            line_texts[lyrics[run_start - 1].source_line]
            if (
                run_start > 0
                and lyrics[run_start - 1].source_line != run_lyrics[0].source_line
            )
            else ""
        )
        slice_duration_ms = math.ceil(
            (final_sample - first_sample) * 1000 / _WHISPER_SAMPLE_RATE
        )
        windows = _windows(slice_duration_ms)
        _LOGGER.info(
            "[MV Director - Lyric Segmentation] targeted retry %d; "
            "segments=%s..%s; source=%d..%dms; windows=%d",
            attempted,
            run_lyrics[0].segment_id,
            run_lyrics[-1].segment_id,
            slice_start_ms,
            slice_end_ms,
            len(windows),
        )

        def decode(
            *,
            guided: bool,
            guided_prefix: str = "",
            decode_windows: tuple[tuple[int, int], ...] = windows,
        ) -> tuple[WhisperWord, ...]:
            decoded: list[WhisperWord] = []
            source_order = 0
            failed_windows: list[tuple[int, int, str]] = []
            for window_start_ms, window_end_ms in decode_windows:
                window_first = first_sample + math.floor(
                    window_start_ms * _WHISPER_SAMPLE_RATE / 1000
                )
                window_final = min(
                    final_sample,
                    first_sample
                    + math.ceil(window_end_ms * _WHISPER_SAMPLE_RATE / 1000),
                )
                if window_final <= window_first:
                    continue
                result = transcriber.transcribe(
                    whisper_audio[window_first:window_final],
                    language=language,
                    device=device,
                    initial_prompt=_window_prompt(
                        guided_lines if guided else run_lines,
                        preceding_line=guided_prefix if guided else preceding_line,
                        window_start_ms=window_start_ms,
                        duration_ms=slice_duration_ms,
                        guided=guided,
                    ),
                    condition_on_previous_text=False,
                )
                window_duration_ms = math.ceil(
                    (window_final - window_first)
                    * 1000
                    / _WHISPER_SAMPLE_RATE
                )
                try:
                    local_words = extract_whisper_words(
                        result,
                        audio_duration_ms=window_duration_ms,
                        allow_partial_word_timestamps=True,
                    )
                except LyricSegmentationError as exc:
                    failed_windows.append(
                        (window_start_ms, window_end_ms, str(exc))
                    )
                    continue
                window_offset_ms = math.floor(
                    (window_first - first_sample)
                    * 1000
                    / _WHISPER_SAMPLE_RATE
                )
                for word in local_words:
                    source_order += 1
                    decoded.append(
                        WhisperWord(
                            word.text,
                            word.normalized,
                            word.start_ms + window_offset_ms,
                            word.end_ms + window_offset_ms,
                            source_order,
                        )
                    )
            if failed_windows:
                first_failed = failed_windows[0]
                if not decoded:
                    raise LyricSegmentationError(
                        "all targeted decode windows lacked usable "
                        "word_timestamps; "
                        f"failed={len(failed_windows)}/{len(decode_windows)}; "
                        f"first={first_failed[0]}..{first_failed[1]}ms"
                    )
                _LOGGER.warning(
                    "[MV Director - Lyric Segmentation] targeted decode "
                    "skipped %d/%d window(s) without usable word_timestamps; "
                    "segments=%s..%s; first=%d..%dms",
                    len(failed_windows),
                    len(decode_windows),
                    run_lyrics[0].segment_id,
                    run_lyrics[-1].segment_id,
                    first_failed[0],
                    first_failed[1],
                )
            return _merge_words(decoded)

        local_voiced = _local_voiced_intervals(
            voiced_intervals,
            sample_rate=sample_rate,
            slice_start_ms=slice_start_ms,
            slice_end_ms=slice_end_ms,
        )

        try:
            unguided_words = decode(guided=False)
        except LyricSegmentationError as exc:
            _LOGGER.warning(
                "[MV Director - Lyric Segmentation] targeted unguided retry "
                "failed for %s..%s: %s",
                run_lyrics[0].segment_id,
                run_lyrics[-1].segment_id,
                exc,
            )
            continue
        if not unguided_words:
            continue
        unguided_resolved, _ = align_lyrics(
            run_lyrics,
            unguided_words,
            voiced_intervals=local_voiced,
            sample_rate=sample_rate,
            audio_duration_ms=slice_duration_ms,
            initial_search_ms=max(1, slice_duration_ms),
            anchored_search_ms=max(1, slice_duration_ms),
        )
        proposals: dict[str, AlignedLyric] = {}
        for item in unguided_resolved:
            absolute = _to_absolute(item, slice_start_ms)
            bounded = _clip_to_anchor_bounds(
                absolute,
                start_ms=anchor_start_ms,
                end_ms=anchor_end_ms,
            )
            if bounded is not None:
                proposals[item.source.segment_id] = bounded

        # Whisper can omit a line near a decode-window edge even though the
        # next lines in the same window are recognized. If the recovered
        # suffix leaves a missing prefix, add one unguided window beginning
        # three seconds before the first recovered timestamp. This is still
        # evidence-only decoding: no guided text is accepted from this pass.
        proposal_indices = [
            index
            for index, source in enumerate(run_lyrics)
            if source.segment_id in proposals
        ]
        if (
            len(proposals) < len(run_lyrics)
            and proposal_indices
            and min(proposal_indices) > 0
        ):
            first_proposal = min(
                proposals.values(), key=lambda item: item.start_ms
            )
            adaptive_start_ms = max(
                0,
                (
                    (
                        first_proposal.start_ms
                        - slice_start_ms
                        - _ADAPTIVE_PREFIX_LEAD_MS
                    )
                    // 1000
                )
                * 1000,
            )
            adaptive_end_ms = min(
                slice_duration_ms,
                adaptive_start_ms + _WINDOW_MS,
            )
            adaptive_window = ((adaptive_start_ms, adaptive_end_ms),)
            if adaptive_end_ms > adaptive_start_ms and adaptive_window[0] not in windows:
                try:
                    _LOGGER.info(
                        "[MV Director - Lyric Segmentation] adaptive unguided "
                        "window; relative=%d..%dms; missing_prefix=%d",
                        adaptive_start_ms,
                        adaptive_end_ms,
                        min(proposal_indices),
                    )
                    extra_words = decode(
                        guided=False,
                        decode_windows=adaptive_window,
                    )
                    unguided_words = _merge_words(
                        [*unguided_words, *extra_words]
                    )
                    unguided_resolved, _ = align_lyrics(
                        run_lyrics,
                        unguided_words,
                        voiced_intervals=local_voiced,
                        sample_rate=sample_rate,
                        audio_duration_ms=slice_duration_ms,
                        initial_search_ms=max(1, slice_duration_ms),
                        anchored_search_ms=max(1, slice_duration_ms),
                    )
                    proposals = {}
                    for item in unguided_resolved:
                        absolute = _to_absolute(item, slice_start_ms)
                        bounded = _clip_to_anchor_bounds(
                            absolute,
                            start_ms=anchor_start_ms,
                            end_ms=anchor_end_ms,
                        )
                        if bounded is not None:
                            proposals[item.source.segment_id] = bounded
                    _LOGGER.info(
                        "[MV Director - Lyric Segmentation] adaptive unguided "
                        "window aligned %d/%d segment(s)",
                        len(proposals),
                        len(run_lyrics),
                    )
                except LyricSegmentationError as exc:
                    _LOGGER.warning(
                        "[MV Director - Lyric Segmentation] adaptive unguided "
                        "window failed for %s..%s: %s",
                        run_lyrics[0].segment_id,
                        run_lyrics[-1].segment_id,
                        exc,
                    )

        if len(proposals) < len(run_lyrics):
            guided_prefixes = ("",)
            if (
                run_start > 0
                and lyrics[run_start - 1].source_line == run_lyrics[0].source_line
            ):
                # A previous segment from the same physical line may help
                # Whisper disambiguate the missing phrase. Try it only after
                # the target-only prompt, without repeating the whole line.
                guided_prefixes += (lyrics[run_start - 1].text,)
            last_guided_error: LyricSegmentationError | None = None
            for guided_prefix in guided_prefixes:
                try:
                    guided_words = decode(
                        guided=True,
                        guided_prefix=guided_prefix,
                    )
                    guided_lyrics = (
                        (*run_lyrics, following.source)
                        if following is not None
                        else run_lyrics
                    )
                    guided_resolved, guided_unplaced = align_lyrics(
                        tuple(guided_lyrics),
                        guided_words,
                        voiced_intervals=local_voiced,
                        sample_rate=sample_rate,
                        audio_duration_ms=slice_duration_ms,
                        initial_search_ms=max(1, slice_duration_ms),
                        anchored_search_ms=max(1, slice_duration_ms),
                    )
                    guided_by_id = {
                        item.source.segment_id: item for item in guided_resolved
                    }
                    required = [item.segment_id for item in run_lyrics]
                    if following is not None:
                        required.append(following.source.segment_id)
                    if guided_unplaced or any(item not in guided_by_id for item in required):
                        raise LyricSegmentationError(
                            "guided retry did not preserve every target and following anchor"
                        )
                    if following is not None:
                        guided_following = _to_absolute(
                            guided_by_id[following.source.segment_id],
                            slice_start_ms,
                        )
                        if not (
                            guided_following.start_ms < following.end_ms
                            and guided_following.end_ms > following.start_ms
                        ):
                            raise LyricSegmentationError(
                                "guided retry did not reproduce the following anchor"
                            )
                    guided_proposals: dict[str, AlignedLyric] = {}
                    previous_end_ms = anchor_start_ms
                    for source in run_lyrics:
                        local = guided_by_id[source.segment_id]
                        if not any(
                            word.start_ms < local.end_ms
                            and word.end_ms > local.start_ms
                            for word in unguided_words
                        ):
                            raise LyricSegmentationError(
                                f"guided retry lacks acoustic evidence for {source.segment_id}"
                            )
                        absolute = _to_absolute(local, slice_start_ms)
                        bounded = _clip_to_anchor_bounds(
                            absolute,
                            start_ms=previous_end_ms,
                            end_ms=anchor_end_ms,
                        )
                        if bounded is None:
                            raise LyricSegmentationError(
                                f"guided retry crossed an anchor for {source.segment_id}"
                            )
                        guided_proposals[source.segment_id] = bounded
                        previous_end_ms = bounded.end_ms
                    proposals = guided_proposals
                    if guided_prefix:
                        _LOGGER.info(
                            "[MV Director - Lyric Segmentation] guided retry "
                            "recovered with preceding segment context; segments=%s..%s",
                            run_lyrics[0].segment_id,
                            run_lyrics[-1].segment_id,
                        )
                    break
                except LyricSegmentationError as exc:
                    last_guided_error = exc
            else:
                _LOGGER.warning(
                    "[MV Director - Lyric Segmentation] evidence-gated guided "
                    "retry was not accepted for %s..%s: %s",
                    run_lyrics[0].segment_id,
                    run_lyrics[-1].segment_id,
                    last_guided_error,
                )

        for index in range(run_start, run_end):
            proposal = proposals.get(lyrics[index].segment_id)
            if proposal is not None:
                slots[index] = proposal
                recovered_count += 1
        _LOGGER.info(
            "[MV Director - Lyric Segmentation] targeted retry recovered %d/%d "
            "segment(s) for %s..%s",
            len(proposals),
            len(run_lyrics),
            run_lyrics[0].segment_id,
            run_lyrics[-1].segment_id,
        )

    final_resolved = tuple(item for item in slots if item is not None)
    final_unplaced = tuple(
        lyric for lyric, item in zip(lyrics, slots) if item is None
    )
    if (
        final_unplaced
        and recovered_count > 0
        and _refinement_pass < _MAX_REFINEMENT_PASSES
    ):
        _LOGGER.info(
            "[MV Director - Lyric Segmentation] targeted refinement pass %d; "
            "new_anchors=%d; remaining=%d",
            _refinement_pass + 1,
            recovered_count,
            len(final_unplaced),
        )
        refined_resolved, refined_unplaced, refined_stats = recover_unplaced_lyrics(
            lyrics,
            final_resolved,
            whisper_audio,
            transcriber,
            language=language,
            device=device,
            voiced_intervals=voiced_intervals,
            sample_rate=sample_rate,
            audio_duration_ms=audio_duration_ms,
            _refinement_pass=_refinement_pass + 1,
        )
        return (
            refined_resolved,
            refined_unplaced,
            TargetedRetryStats(
                attempted + refined_stats.attempted_runs,
                recovered_count + refined_stats.recovered_segments,
            ),
        )
    return (
        final_resolved,
        final_unplaced,
        TargetedRetryStats(attempted, recovered_count),
    )
