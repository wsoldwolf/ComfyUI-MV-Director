"""Candidate-based Shot layout owned by Python and selected by line protocol."""

from __future__ import annotations

from dataclasses import dataclass

from ..emd.ast import Scene, Shot
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
            )
        )
    return PlannerTemplate(tuple(scenes))
