"""Planner-owned visual mouth intentions from known PCM intervals.

The Compiler consumes the result, never the detector's advisory states.
No prose is inspected or repaired, and no additional LLM calls are needed.
"""

from __future__ import annotations

import logging
import math

from ..emd import MouthPerformance, Scene
from .errors import TimelinePlannerError
from .template import PlannerTemplate


_LOGGER = logging.getLogger("mv_director.nodes")
LONG_GAP_MS = 2000
VOICE_MARGIN_MS = 200
_REST_STATES = frozenset({
    "no_vocal_candidate", "instrumental_candidate", "fullmix_silence_candidate",
})


def _subtract(start: int, end: int, blocked: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces = [(start, end)]
    for left, right in blocked:
        pieces = [part for a, b in pieces for part in (
            (a, min(b, left)), (max(a, right), b),
        ) if part[1] > part[0]]
    return pieces


def _authored_shot_ranges(scene: Scene) -> list[tuple[int, int]]:
    return [
        (shot.start_ms, scene.shots[index + 1].start_ms
         if index + 1 < len(scene.shots) else scene.end_ms)
        for index, shot in enumerate(scene.shots)
        if any(d.kind == "演技" for d in shot.directives)
        or shot.lyric_lip_sync
        or any(text != "未計画" and not text.startswith(
            ("`演出` ", "`演技` ", "`カメラ` ")) for text in shot.body)
    ]


def plan_mouth_performances(
    template: PlannerTemplate, *, lip_sync_mode: str, lip_sync_target: str,
    subject_count: int,
) -> dict[int, tuple[MouthPerformance, ...]]:
    """Resolve author priority before authoring Performance and Camera.

    Intervals are in delivered PCM time, not Shot time. Long gaps are measured
    before Scene clipping. Unknowns, padding and unmapped inputs add no policy.
    """
    subjects = {f"サブジェクト{i}" for i in range(1, subject_count + 1)}
    for scene in template.scenes:
        for item in scene.mouth_performances:
            if item.target_concept_id not in subjects:
                raise TimelinePlannerError("mouth performance references undefined concept ID")
    result = {scene.scene_number: scene.mouth_performances for scene in template.scenes}
    activity = template.audio_activity
    if activity is None or lip_sync_mode == "off":
        return result
    if lip_sync_target not in subjects:
        raise TimelinePlannerError("lip-sync target references undefined concept ID")
    # Reuse the same source/reference-copy mapping as Scene authorship. Read
    # the whole timeline first so a Scene split does not shorten a long gap.
    last_sample = activity.source_samples
    if lip_sync_mode == "audio_reference" and activity.reference_copies:
        last = activity.reference_copies[-1]
        last_sample = last.destination_start_sample + last.source_end_sample - last.source_start_sample
    payload = activity.scene_payload(
        start_ms=0, end_ms=math.ceil(last_sample * 1000 / activity.sample_rate),
        audio_mode=lip_sync_mode,
    )
    intervals = payload["intervals"]
    if not intervals:
        _LOGGER.info("[MV Director - Timeline Planner] mouth planning skipped; reason=unmapped_audio")
        return result
    voices = [(math.floor(i["start_ms"]), math.ceil(i["end_ms"]))
              for i in intervals if i["state"] == "vocal_candidate"]
    protected_voice = [(a - VOICE_MARGIN_MS, b + VOICE_MARGIN_MS) for a, b in voices]
    runs: list[tuple[float, float]] = []
    for item in intervals:
        if item["state"] in _REST_STATES:
            a, b = item["start_ms"], item["end_ms"]
            if runs and runs[-1][1] == a:
                runs[-1] = (runs[-1][0], b)
            else:
                runs.append((a, b))
    rests = [part for a, b in runs if b - a >= LONG_GAP_MS
             for part in _subtract(math.ceil(a), math.floor(b), protected_voice)]
    candidates = [(a, b, "閉口") for a, b in rests] + [(a, b, "歌唱") for a, b in voices]
    for scene in template.scenes:
        authored = list(scene.mouth_performances)
        blocked = _authored_shot_ranges(scene) + [
            (i.start_ms, i.end_ms) for i in authored if i.target_concept_id == lip_sync_target
        ]
        generated = [
            MouthPerformance(lip_sync_target, start, end, state)
            for a, b, state in candidates
            for start, end in _subtract(max(scene.start_ms, a), min(scene.end_ms, b), blocked)
            if end > start
        ]
        combined = sorted(authored + generated, key=lambda i: (i.start_ms, i.target_concept_id))
        result[scene.scene_number] = tuple(combined)
        if combined:
            _LOGGER.info(
                "[MV Director - Timeline Planner] mouth plan; scene=%d; author=%d; "
                "generated=%d; closed=%d; singing=%d; free=%d; voice_margin_ms=%d",
                scene.scene_number, len(authored), len(generated),
                sum(i.state == "閉口" for i in combined),
                sum(i.state == "歌唱" for i in combined),
                sum(i.state == "自由" for i in combined), VOICE_MARGIN_MS,
            )
    return result


def mouth_scene_payload(scene: Scene, intervals: tuple[MouthPerformance, ...]) -> dict:
    return {
        "timebase": "delivered_pcm", "author_performance_has_priority": True,
        "intervals": [{
            "subject": i.target_concept_id, "start_ms": i.start_ms, "end_ms": i.end_ms,
            "local_start_ms": i.start_ms - scene.start_ms,
            "local_end_ms": i.end_ms - scene.start_ms, "state": i.state,
        } for i in intervals],
    }
