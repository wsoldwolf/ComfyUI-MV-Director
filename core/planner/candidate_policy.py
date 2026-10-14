"""Advisory selection strength; never an output-validation gate."""

import math
from typing import Mapping, Sequence

from .mouth_performance import LONG_GAP_MS

STAGING_CANDIDATE_POLICIES = ("optional", "prefer_matched")


def validate_staging_candidate_policy(value: str) -> None:
    if value not in STAGING_CANDIDATE_POLICIES:
        raise ValueError("staging_candidate_policy must be optional or prefer_matched")


def performance_candidate_preference_enabled(
    policy: str, candidates: Sequence[str], audio_activity: object,
    pending_positions: Sequence[Mapping[str, object]],
) -> bool:
    """Scope an advisory prompt to known long rests in unowned Shots.

    Only inspect timing/state metadata, never candidate prose or generated
    actions. The LLM still decides which (if any) candidate fits. Unknown,
    padding and full-mix silence do not establish accompaniment.
    """
    if policy != "prefer_matched" or not any(c.strip() for c in candidates):
        return False
    if not isinstance(audio_activity, Mapping):
        return False
    intervals = audio_activity.get("intervals")
    if not isinstance(intervals, (list, tuple)):
        return False

    def bounds(row: Mapping[str, object]) -> tuple[float, float] | None:
        start, end = row.get("start_ms"), row.get("end_ms")
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in (start, end)):
            return None
        return (start, end) if 0 <= start < end else None

    runs: list[tuple[float, float]] = []
    for interval in intervals:
        if not isinstance(interval, Mapping):
            continue
        span = bounds(interval)
        if span is None or interval.get("state") not in {
            "no_vocal_candidate", "instrumental_candidate",
        }:
            continue
        if runs and runs[-1][1] == span[0]:
            runs[-1] = (runs[-1][0], span[1])
        else:
            runs.append(span)
    for position in pending_positions:
        if position.get("fixed_performance"):
            continue
        span = bounds(position)
        if span is not None and any(
            min(span[1], end) - max(span[0], start) >= LONG_GAP_MS
            for start, end in runs
        ):
            return True
    return False
