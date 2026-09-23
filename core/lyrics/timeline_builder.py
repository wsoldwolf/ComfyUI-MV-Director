"""Build the canonical source/plan timeline without LLM involvement."""

from __future__ import annotations

import math

from ..artifacts import (
    LyricSegment,
    TimelineArtifact,
    TimelineScene,
    TimelineShot,
    UnplacedLyric,
)
from ..h3_contract import H3TimingProfile
from .alignment import AlignedLyric
from .errors import LyricSegmentationError
from .plain import SourceLyricSegment


ALGORITHM_VERSION = "lyric-timeline-v10"


def _split_long_lyrics(
    lyrics: tuple[AlignedLyric, ...], max_duration_ms: int
) -> tuple[AlignedLyric, ...]:
    result: list[AlignedLyric] = []
    for item in lyrics:
        if item.end_ms - item.start_ms <= max_duration_ms:
            result.append(item)
            continue
        points = [(0, item.start_ms), *item.word_boundaries, (len(item.source.text), item.end_ms)]
        selected = [points[0]]
        point_index = 1
        while points[-1][1] - selected[-1][1] > max_duration_ms:
            candidates = [
                point
                for point in points[point_index:-1]
                if selected[-1][1] < point[1] <= selected[-1][1] + max_duration_ms
            ]
            if not candidates:
                raise LyricSegmentationError(
                    f"{item.source.segment_id} exceeds max_scene_duration_ms and has no usable aligned Whisper word boundary"
                )
            chosen = candidates[-1]
            selected.append(chosen)
            point_index = points.index(chosen) + 1
        selected.append(points[-1])
        piece_count = len(selected) - 1
        for piece_index, ((text_start, time_start), (text_end, time_end)) in enumerate(
            zip(selected, selected[1:]), 1
        ):
            text = item.source.text[text_start:text_end]
            source = SourceLyricSegment(
                segment_id=f"{item.source.segment_id}_{piece_index:02d}",
                text=text,
                section=item.source.section,
                source_line=item.source.source_line,
                source_start=item.source.source_start + text_start,
                source_end=item.source.source_start + text_end,
                normalized=item.source.normalized,
            )
            inner_boundaries = tuple(
                (index - text_start, value)
                for index, value in item.word_boundaries
                if text_start < index < text_end
            )
            result.append(AlignedLyric(source, time_start, time_end, inner_boundaries))
        if piece_count < 2:  # Defensive; the duration branch must derive pieces.
            raise LyricSegmentationError("long lyric splitting made no progress")
    return tuple(result)


def _source_boundaries(
    duration_ms: int,
    max_scene_duration_ms: int,
    lyrics: tuple[AlignedLyric, ...],
) -> tuple[int, ...]:
    """Greedily cap Scene duration and never cut a resolved lyric."""

    boundaries = [0]
    cursor = 0
    while duration_ms - cursor > max_scene_duration_ms:
        target = cursor + max_scene_duration_ms
        containing = next(
            (item for item in lyrics if item.start_ms < target < item.end_ms),
            None,
        )
        if containing is None:
            boundary = target
        elif containing.start_ms > cursor:
            boundary = containing.start_ms
        elif containing.end_ms - cursor <= max_scene_duration_ms:
            boundary = containing.end_ms
        else:
            raise LyricSegmentationError(
                f"{containing.source.segment_id} exceeds max_scene_duration_ms; "
                "split the plain-lyrics phrase at an explicit space"
            )
        if boundary <= cursor:
            raise LyricSegmentationError("could not choose a forward Scene boundary")
        boundaries.append(boundary)
        cursor = boundary
    boundaries.append(duration_ms)
    return tuple(boundaries)


def _scene_for_lyric(
    item: AlignedLyric, boundaries: tuple[int, ...]
) -> int:
    for index in range(len(boundaries) - 1):
        if boundaries[index] <= item.start_ms < boundaries[index + 1]:
            if item.end_ms > boundaries[index + 1]:
                raise LyricSegmentationError(
                    f"{item.source.segment_id} crosses a selected Scene boundary"
                )
            return index + 1
    raise LyricSegmentationError(
        f"{item.source.segment_id} starts outside the source audio"
    )


def _plan_time_for_source(
    source_ms: int,
    *,
    source_scene_start_ms: int,
    plan_start_frame: int,
    fps: int,
) -> int:
    relative_frames = round((source_ms - source_scene_start_ms) * fps / 1000)
    return round((plan_start_frame + relative_frames) * 1000 / fps)


def _active_group_starts(items: list[AlignedLyric]) -> tuple[int, ...]:
    if not items:
        return ()
    ordered = sorted(items, key=lambda item: (item.start_ms, item.end_ms))
    starts: list[int] = []
    active_end = -1
    for item in ordered:
        if item.start_ms >= active_end:
            starts.append(item.start_ms)
            active_end = item.end_ms
        else:
            active_end = max(active_end, item.end_ms)
    return tuple(starts)


def build_timeline(
    resolved: tuple[AlignedLyric, ...],
    unplaced: tuple[SourceLyricSegment, ...],
    *,
    source_audio_duration_ms: int,
    max_scene_duration_ms: int,
    timing_profile: H3TimingProfile,
) -> TimelineArtifact:
    if source_audio_duration_ms < 1:
        raise LyricSegmentationError("source audio duration must be positive")
    if max_scene_duration_ms < 1000:
        raise LyricSegmentationError("max_scene_duration_ms must be at least 1000")
    timing_profile.validate()
    resolved = _split_long_lyrics(resolved, max_scene_duration_ms)
    boundaries = _source_boundaries(
        source_audio_duration_ms, max_scene_duration_ms, resolved
    )
    assigned_scene = {
        item.source.segment_id: _scene_for_lyric(item, boundaries)
        for item in resolved
    }

    scene_rows: list[TimelineScene] = []
    plan_start_frame = 0
    shot_starts_by_scene: dict[int, tuple[int, ...]] = {}
    for scene_index, (source_start, source_end) in enumerate(
        zip(boundaries, boundaries[1:]), 1
    ):
        cumulative_target_frame = math.ceil(source_end * timing_profile.fps / 1000)
        required_delivered = max(1, cumulative_target_frame - plan_start_frame)
        raw_length, delivered_frames, context_length = timing_profile.quantize_delivered_frames(
            required_delivered,
            first_scene=scene_index == 1,
        )
        plan_end_frame = plan_start_frame + delivered_frames
        plan_start_ms = round(plan_start_frame * 1000 / timing_profile.fps)
        plan_end_ms = round(plan_end_frame * 1000 / timing_profile.fps)
        scene_lyrics = [
            item
            for item in resolved
            if assigned_scene[item.source.segment_id] == scene_index
        ]
        candidates = [
            _plan_time_for_source(
                value,
                source_scene_start_ms=source_start,
                plan_start_frame=plan_start_frame,
                fps=timing_profile.fps,
            )
            for value in _active_group_starts(scene_lyrics)
        ]
        shot_starts = [plan_start_ms]
        for candidate in candidates:
            candidate = min(max(candidate, plan_start_ms), plan_end_ms - 1)
            if candidate == plan_start_ms:
                continue
            if candidate - shot_starts[-1] < 3000:
                continue
            if plan_end_ms - candidate < 2000:
                continue
            shot_starts.append(candidate)
            if len(shot_starts) == 3:
                break
        shot_starts_by_scene[scene_index] = tuple(shot_starts)
        shots = tuple(
            TimelineShot(start, end)
            for start, end in zip(shot_starts, [*shot_starts[1:], plan_end_ms])
        )
        scene_rows.append(
            TimelineScene(
                scene_number=scene_index,
                start_ms=plan_start_ms,
                end_ms=plan_end_ms,
                source_start_ms=source_start,
                source_end_ms=source_end,
                raw_length=raw_length,
                delivered_frames=delivered_frames,
                context_length=context_length,
                shots=shots,
            )
        )
        plan_start_frame = plan_end_frame

    lyric_rows: list[LyricSegment] = []
    for item in resolved:
        scene_number = assigned_scene[item.source.segment_id]
        scene = scene_rows[scene_number - 1]
        plan_position = _plan_time_for_source(
            item.start_ms,
            source_scene_start_ms=scene.source_start_ms,
            plan_start_frame=round(scene.start_ms * timing_profile.fps / 1000),
            fps=timing_profile.fps,
        )
        starts = shot_starts_by_scene[scene_number]
        shot_index = max(
            index for index, shot_start in enumerate(starts, 1) if shot_start <= plan_position
        )
        lyric_rows.append(
            LyricSegment(
                segment_id=item.source.segment_id,
                text=item.source.text,
                section=item.source.section,
                source_line=item.source.source_line,
                source_start=item.source.source_start,
                source_end=item.source.source_end,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                scene_number=scene_number,
                shot_index=shot_index,
            )
        )

    artifact = TimelineArtifact(
        vad_analysis_hop_ms=20,
        boundary_resolution_ms=1,
        boundary_method="energy_vad_sample_refined",
        source_audio_duration_ms=source_audio_duration_ms,
        plan_duration_ms=scene_rows[-1].end_ms,
        timing_profile=timing_profile.contract,
        lyrics=tuple(lyric_rows),
        scenes=tuple(scene_rows),
        unplaced_lyrics=tuple(
            UnplacedLyric(
                segment_id=item.segment_id,
                text=item.text,
                section=item.section,
                source_line=item.source_line,
                source_start=item.source_start,
                source_end=item.source_end,
                reason="no ordered exact Whisper word match",
            )
            for item in unplaced
        ),
    )
    artifact.validate()
    return artifact
