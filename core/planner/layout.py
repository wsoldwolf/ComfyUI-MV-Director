"""Candidate-based Shot layout owned by Python and selected by line protocol."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from ..emd.ast import Scene, Shot
from ..h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
from .errors import TimelinePlannerError
from .template import PlannerTemplate


MIN_SHOT_DURATION_MS = 1500
MAX_SHOTS_PER_SCENE = 4
_FPS = 24


@dataclass(frozen=True, slots=True)
class ShotBoundaryCandidate:
    candidate_id: str
    start_ms: int
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.candidate_id,
            "start_ms": self.start_ms,
            "source": self.source,
        }


def _frame_snap(value_ms: int) -> int:
    return round(round(value_ms * _FPS / 1000) * 1000 / _FPS)


def build_layout_candidates(scene: Scene) -> tuple[ShotBoundaryCandidate, ...]:
    """Return mutually compatible boundary choices without asking the LLM for time."""

    duration = scene.end_ms - scene.start_ms
    proposed: dict[int, str] = {}
    for shot in scene.shots[1:]:
        proposed[shot.start_ms] = "existing_shot"
    for numerator, denominator in ((1, 4), (1, 3), (1, 2), (2, 3), (3, 4)):
        start = _frame_snap(scene.start_ms + duration * numerator // denominator)
        if (
            start - scene.start_ms >= MIN_SHOT_DURATION_MS
            and scene.end_ms - start >= MIN_SHOT_DURATION_MS
        ):
            proposed.setdefault(start, "balanced")

    rows: list[tuple[int, str]] = [(scene.start_ms, "scene_start")]
    for start, source in sorted(
        proposed.items(),
        key=lambda item: (0 if item[1] == "existing_shot" else 1, item[0]),
    ):
        if (
            scene.end_ms - start >= MIN_SHOT_DURATION_MS
            and all(
                abs(start - accepted_start) >= MIN_SHOT_DURATION_MS
                for accepted_start, _ in rows
            )
        ):
            rows.append((start, source))
    rows.sort()
    return tuple(
        ShotBoundaryCandidate(f"B{index}", start, source)
        for index, (start, source) in enumerate(rows)
    )


def parse_layout_selection(
    text: str,
    candidates: tuple[ShotBoundaryCandidate, ...],
    *,
    scene_end_ms: int,
) -> tuple[int, ...]:
    by_id = {item.candidate_id: item.start_ms for item in candidates}
    ids = tuple(part.strip() for part in text.split(",") if part.strip())
    if not ids or ids[0] != "B0":
        raise TimelinePlannerError("Shot layout must start with B0")
    if len(ids) > MAX_SHOTS_PER_SCENE:
        raise TimelinePlannerError(
            f"Shot layout supports at most {MAX_SHOTS_PER_SCENE} Shots"
        )
    if len(set(ids)) != len(ids) or any(item not in by_id for item in ids):
        raise TimelinePlannerError("Shot layout contains an invalid candidate ID")
    starts = tuple(by_id[item] for item in ids)
    if tuple(sorted(starts)) != starts:
        raise TimelinePlannerError("Shot layout candidates must be in timeline order")
    if len(starts) > 1 and any(
        right - left < MIN_SHOT_DURATION_MS
        for left, right in zip(starts, (*starts[1:], scene_end_ms))
    ):
        raise TimelinePlannerError("Shot layout creates a Shot shorter than 1500 ms")
    return starts


def parse_scene_layout_selection(
    text: str,
    candidates: tuple[ShotBoundaryCandidate, ...],
    *,
    scene_end_ms: int,
    first_scene: bool,
) -> tuple[bool, tuple[int, ...]]:
    """Parse a Scene cut/continuation flag and Python-owned Shot boundaries."""

    parts = tuple(part.strip() for part in text.split(",") if part.strip())
    if not parts or parts[0] not in {"CUT", "CONTINUE"}:
        raise TimelinePlannerError("Shot layout must start with CUT or CONTINUE")
    continuation = parts[0] == "CONTINUE"
    if first_scene and continuation:
        raise TimelinePlannerError("first Scene cannot continue")
    starts = parse_layout_selection(
        ",".join(parts[1:]), candidates, scene_end_ms=scene_end_ms
    )
    return continuation, starts


def repair_scene_layout_selection(
    text: str,
    candidates: tuple[ShotBoundaryCandidate, ...],
    *,
    scene_end_ms: int,
    first_scene: bool,
) -> tuple[bool, tuple[int, ...]]:
    """Mechanically repair a recognizable LAYOUT without inventing intent."""

    tokens = re.findall(
        r"(?<![A-Z0-9_])(?:CUT|CONTINUE|B[0-9]+)(?![A-Z0-9_])",
        text.upper(),
    )
    mode = next(
        (token for token in tokens if token in {"CUT", "CONTINUE"}),
        None,
    )
    if mode is None:
        raise TimelinePlannerError("Shot layout has no recognizable boundary mode")
    continuation = mode == "CONTINUE" and not first_scene
    by_id = {item.candidate_id: item.start_ms for item in candidates}
    selected_ids = {
        token for token in tokens
        if token.startswith("B") and token in by_id
    }
    selected_ids.add("B0")
    ordered_ids = sorted(selected_ids, key=by_id.__getitem__)[
        :MAX_SHOTS_PER_SCENE
    ]
    starts = parse_layout_selection(
        ",".join(ordered_ids),
        candidates,
        scene_end_ms=scene_end_ms,
    )
    return continuation, starts


def _destination_index(starts: tuple[int, ...], original_start: int) -> int:
    return max(
        index
        for index, selected_start in enumerate(starts)
        if selected_start <= original_start
    )


def apply_shot_layouts(
    template: PlannerTemplate,
    layouts: dict[int, tuple[int, ...]],
) -> PlannerTemplate:
    scenes: list[Scene] = []
    for scene in template.scenes:
        starts = layouts.get(scene.scene_number, (scene.start_ms,))
        if not starts or starts[0] != scene.start_ms:
            raise TimelinePlannerError("Shot layout must retain the Scene start")
        if len(starts) > MAX_SHOTS_PER_SCENE:
            raise TimelinePlannerError("Shot layout has too many Shots")
        ends = (*starts[1:], scene.end_ms)
        if len(starts) > 1 and any(
            end - start < MIN_SHOT_DURATION_MS
            for start, end in zip(starts, ends)
        ):
            raise TimelinePlannerError("Shot layout creates a Shot shorter than 1500 ms")

        bodies: list[list[str]] = [[] for _ in starts]
        lyrics: list[list[object]] = [[] for _ in starts]
        line_numbers = [scene.line_number for _ in starts]
        for original in scene.shots:
            destination = _destination_index(starts, original.start_ms)
            line_numbers[destination] = original.line_number
            bodies[destination].extend(
                value for value in original.body if value != "未計画"
            )
            lyrics[destination].extend(original.lyric_annotations)
        shots = tuple(
            Shot(
                start_ms=start,
                body=tuple(bodies[index]) or ("未計画",),
                lyric_annotations=tuple(lyrics[index]),
                lyric_lip_sync=(),
                line_number=line_numbers[index],
            )
            for index, start in enumerate(starts)
        )
        scenes.append(
            Scene(
                scene_number=scene.scene_number,
                start_ms=scene.start_ms,
                end_ms=scene.end_ms,
                h3_length=scene.h3_length,
                descriptions=scene.descriptions,
                shots=shots,
                audio_directives=scene.audio_directives,
                line_number=scene.line_number,
                continuation=scene.continuation,
            )
        )
    return PlannerTemplate(tuple(scenes))


def _valid_raw_at_or_above(
    profile: H3TimingProfile, value: float, minimum: int
) -> int:
    k = max(
        0,
        math.ceil(
            (max(value, minimum) - profile.length_remainder)
            / profile.length_modulus
        ),
    )
    result = k * profile.length_modulus + profile.length_remainder
    while result < max(profile.min_raw_length, minimum):
        result += profile.length_modulus
    profile.validate_raw_length(result)
    return result


def _nearest_valid_raw(
    profile: H3TimingProfile, value: float, minimum: int
) -> int:
    upper = _valid_raw_at_or_above(profile, value, minimum)
    lower = upper - profile.length_modulus
    if lower < max(profile.min_raw_length, minimum):
        return upper
    return lower if abs(value - lower) < abs(upper - value) else upper


def apply_scene_continuations(
    template: PlannerTemplate,
    continuations: dict[int, bool],
    *,
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> PlannerTemplate:
    """Apply Scene boundary modes and reassign H3 lengths cumulatively.

    Continued Scenes lose the visual head overlap; cut Scenes do not. The raw
    17k+5 lengths and absolute Plan timestamps therefore have to be reassigned
    together when Planner changes a boundary mode.
    """

    timing_profile.validate()
    scenes = template.scenes
    if not scenes:
        return template
    modes = [False]
    modes.extend(
        bool(continuations.get(scene.scene_number, scene.continuation))
        for scene in scenes[1:]
    )
    target_end_frames = [
        round(scene.end_ms * timing_profile.fps / 1000) for scene in scenes
    ]
    delivered_cumulative = 0
    result: list[Scene] = []
    for index, scene in enumerate(scenes):
        continuation = modes[index]
        overlap = (
            timing_profile.continuation_context_length if continuation else 0
        )
        next_context = (
            timing_profile.continuation_context_length
            if index + 1 < len(scenes) and modes[index + 1]
            else 1
        )
        minimum_raw = overlap + max(1, next_context)
        ideal_raw = target_end_frames[index] - delivered_cumulative + overlap
        raw_length = (
            _valid_raw_at_or_above(timing_profile, ideal_raw, minimum_raw)
            if index + 1 == len(scenes)
            else _nearest_valid_raw(timing_profile, ideal_raw, minimum_raw)
        )
        delivered = raw_length - overlap
        start_frame = delivered_cumulative
        end_frame = start_frame + delivered
        start_ms = round(start_frame * 1000 / timing_profile.fps)
        end_ms = round(end_frame * 1000 / timing_profile.fps)
        old_duration = scene.end_ms - scene.start_ms
        new_duration = end_ms - start_ms
        shot_starts = [start_ms]
        shot_count = len(scene.shots)
        for shot_index, shot in enumerate(scene.shots[1:], 1):
            relative = (shot.start_ms - scene.start_ms) / old_duration
            candidate_frame = round(
                (start_ms + relative * new_duration) * timing_profile.fps / 1000
            )
            candidate = round(candidate_frame * 1000 / timing_profile.fps)
            candidate = max(shot_starts[-1] + MIN_SHOT_DURATION_MS, candidate)
            remaining_shots = shot_count - shot_index
            candidate = min(
                end_ms - remaining_shots * MIN_SHOT_DURATION_MS,
                candidate,
            )
            if candidate <= shot_starts[-1] or candidate >= end_ms:
                raise TimelinePlannerError(
                    "retimed Shot boundary is not representable"
                )
            shot_starts.append(candidate)
        shots = tuple(
            Shot(
                start_ms=shot_starts[shot_index],
                body=shot.body,
                lyric_annotations=shot.lyric_annotations,
                lyric_lip_sync=shot.lyric_lip_sync,
                line_number=shot.line_number,
            )
            for shot_index, shot in enumerate(scene.shots)
        )
        result.append(
            Scene(
                scene_number=scene.scene_number,
                start_ms=start_ms,
                end_ms=end_ms,
                h3_length=raw_length,
                descriptions=scene.descriptions,
                shots=shots,
                audio_directives=scene.audio_directives,
                line_number=scene.line_number,
                continuation=continuation,
            )
        )
        delivered_cumulative = end_frame
    return PlannerTemplate(tuple(result))
