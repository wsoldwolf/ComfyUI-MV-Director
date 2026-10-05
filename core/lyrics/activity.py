"""Diagnostic vocal activity on the source sample clock (no Planner control).

Energy VAD detects candidates, not semantic proof of singing or accompaniment.
Lyric/VAD disagreement is retained as unknown, never a generation blocker.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Iterable

from ..artifacts import TimelineArtifact
from ..audio.pad_pair import AudioShape, SceneAudioWindow, scene_audio_placements
from .vad import VoicedInterval


ACTIVITY_SCHEMA = "MVD_AUDIO_ACTIVITY_DIAGNOSTIC_V1"
VAD_SETTINGS = {
    "hop_ms": 20, "threshold_dbfs": -45.0, "min_voiced_ms": 120,
    "min_silence_ms": 300, "padding_ms": 80,
}


def _ranges(intervals: Iterable[VoicedInterval], total: int) -> list[tuple[int, int]]:
    result = []
    for item in intervals:
        start, end = item.start_sample, item.end_sample
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, int) or not isinstance(end, int)
                or not 0 <= start < end <= total):
            raise ValueError("activity interval is outside source PCM")
        if result and start < result[-1][1]:
            raise ValueError("activity intervals must be ordered and non-overlapping")
        result.append((start, end))
    return result


def build_activity_diagnostic(
    voiced: Iterable[VoicedInterval], *, sample_rate: int, total_samples: int,
    audio_sha256: str, timeline: TimelineArtifact | None = None,
    fullmix_active: Iterable[VoicedInterval] | None = None,
    fullmix_observed_samples: int | None = None,
    long_gap_ms: int = 2000, fps: int = 24,
) -> dict[str, object]:
    """Persist raw VAD, all source intervals, and optional aligned-reference clock.

    Full mix ranges must use this source clock. Missing tail samples are unknown,
    not observed silence; no resampling or fabricated PCM evidence is performed.
    No interval is inferred merely from the absence of a lyric annotation.
    """
    AudioShape(sample_rate, total_samples).validate()
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise ValueError("fps must be a positive integer")
    if isinstance(long_gap_ms, bool) or not isinstance(long_gap_ms, int) or long_gap_ms < 1:
        raise ValueError("long_gap_ms must be a positive integer")
    if len(audio_sha256) != 64 or any(c not in "0123456789abcdef" for c in audio_sha256):
        raise ValueError("audio_sha256 must be a lowercase SHA-256 fingerprint")
    voices = _ranges(voiced, total_samples)
    mix = None if fullmix_active is None else _ranges(fullmix_active, total_samples)
    mix_samples = total_samples if fullmix_observed_samples is None else fullmix_observed_samples
    if isinstance(mix_samples, bool) or not isinstance(mix_samples, int) or mix_samples < 1:
        raise ValueError("fullmix_observed_samples must be a positive integer")
    mix_samples = min(mix_samples, total_samples)
    if mix is not None and any(end > mix_samples for _, end in mix):
        raise ValueError("fullmix activity exceeds observed PCM coverage")
    lyrics = []
    if timeline is not None:
        timeline.validate()
        if abs(timeline.source_audio_duration_ms * sample_rate - total_samples * 1000) >= sample_rate:
            raise ValueError("timeline duration does not match the source PCM")
        for lyric in timeline.lyrics:
            start = max(0, min(total_samples, round(Fraction(lyric.start_ms * sample_rate, 1000))))
            end = max(start, min(total_samples, round(Fraction(lyric.end_ms * sample_rate, 1000))))
            if end > start:
                lyrics.append((start, end, lyric.segment_id))

    boundaries = {0, total_samples}
    if mix is not None:
        boundaries.add(mix_samples)
    for start, end in [*voices, *(mix or [])]:
        boundaries.update((start, end))
    for start, end, _ in lyrics:
        boundaries.update((start, end))
    points = sorted(boundaries)
    intervals = []
    for start, end in zip(points, points[1:]):
        active = any(a <= start < b for a, b in voices)
        lyric_ids = [identifier for a, b, identifier in lyrics if a <= start < b]
        mix_active = None if mix is None or start >= mix_samples else any(a <= start < b for a, b in mix)
        state = "vocal_candidate" if active else "no_vocal_candidate"
        if not active and lyric_ids:
            state = "unknown"
        elif not active and mix is not None and mix_active is None:
            state = "unknown"
        elif not active and mix_active is not None:
            state = "instrumental_candidate" if mix_active else "fullmix_silence_candidate"
        intervals.append({
            "start_sample": start, "end_sample": end, "state": state,
            "lyric_ids": lyric_ids, "fullmix_active": mix_active,
        })

    # Long gaps are complements of the VAD, not of the lyric annotation list.
    gaps = []
    cursor = 0
    for index, (start, end) in enumerate([*voices, (total_samples, total_samples)]):
        if (start - cursor) * 1000 >= long_gap_ms * sample_rate:
            conflicts = [identifier for a, b, identifier in lyrics if a < start and b > cursor]
            gaps.append({
                "start_sample": cursor, "end_sample": start,
                "position": "whole_source" if not voices else (
                    "intro" if index == 0 else "outro" if index == len(voices) else "internal"),
                "previous_vocal_end_sample": None if index == 0 else cursor,
                "next_vocal_start_sample": None if index == len(voices) else start,
                "lyric_conflict_ids": conflicts,
                "eligible": not conflicts,
            })
        cursor = end

    result: dict[str, object] = {
        "schema": ACTIVITY_SCHEMA, "audio_sha256": audio_sha256,
        "sample_rate": sample_rate, "source_samples": total_samples,
        "detector": {"method": "energy_vad_sample_refined", **VAD_SETTINGS},
        "long_gap_ms": long_gap_ms, "fullmix_checked": mix is not None,
        "lyrics_checked": timeline is not None,
        "fullmix_coverage_samples": None if mix is None else mix_samples,
        "raw_vad": [{"start_sample": a, "end_sample": b} for a, b in voices],
        "lyrics": [{"start_sample": a, "end_sample": b, "segment_id": i} for a, b, i in lyrics],
        "source_intervals": intervals, "long_gaps": gaps,
        "warning_count": sum(item["state"] == "unknown" for item in intervals),
    }
    if timeline is None:
        return result

    frames = sum(scene.delivered_frames for scene in timeline.scenes)
    target = max(total_samples, -(-(frames * sample_rate) // fps),
                 -(-(timeline.plan_duration_ms * sample_rate) // 1000))
    placements = scene_audio_placements(
        AudioShape(sample_rate, total_samples), tuple(
            SceneAudioWindow(scene.source_start_ms, scene.source_end_ms, scene.delivered_frames)
            for scene in timeline.scenes
        ), target_samples=target, fps=fps,
    )
    mapped = []
    padding = []
    copy_rows = []
    for index, placement in enumerate(placements, 1):
        p = placement
        copy_rows.append({"scene_number": index, **{
            name: getattr(p, name) for name in p.__dataclass_fields__
        }})
        for item in intervals:
            start = max(item["start_sample"], p.source_start_sample)
            end = min(item["end_sample"], p.source_end_sample)
            if end <= start:
                continue
            offset = p.destination_start_sample - p.source_start_sample
            mapped.append({**item, "start_sample": start + offset, "end_sample": end + offset,
                           "source_start_sample": start, "source_end_sample": end,
                           "source_scene_number": index})
        next_start = placements[index].destination_start_sample if index < len(placements) else target
        if next_start > p.destination_end_sample:
            padding.append({"start_sample": p.destination_end_sample, "end_sample": next_start,
                            "state": "padding"})
    result["aligned_reference"] = {
        "mode": "source_scenes_to_plan", "fps": fps, "target_samples": target,
        "placements": copy_rows, "intervals": mapped, "padding": padding,
        "note": "Audio Pad Pair reference_audio_b clock; not Context Loop source clock",
    }
    return result
