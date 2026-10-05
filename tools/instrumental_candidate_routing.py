"""Research-only routing of explicitly scoped candidates from PCM evidence.

No production caller or EMD syntax change. Untyped author input is always
general; prose is never classified with a keyword dictionary or rewritten.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence

SCOPES = frozenset({"general", "intro", "interlude", "outro", "vocal_return"})


@dataclass(frozen=True)
class ScopedCandidate:
    text: str
    scope: str = "general"

    def __post_init__(self):
        if not self.text.strip() or self.scope not in SCOPES:
            raise ValueError("Invalid explicitly scoped research candidate")


def route_candidates(candidates: Sequence[ScopedCandidate], activity: Mapping | None,
                     *, start_ms: int, end_ms: int, minimum_instrumental_ms: int = 2000) -> dict:
    """Select candidate pools, not the motion itself; uncertain evidence falls back."""
    if end_ms <= start_ms or minimum_instrumental_ms < 0:
        raise ValueError("Invalid routing window")
    all_texts = [candidate.text for candidate in candidates]
    fallback = {"texts": all_texts, "eligible_scopes": sorted(SCOPES), "fallback": True}
    if not activity or activity.get("timebase") not in {"end_padded_source_pcm", "aligned_reference_pcm"}:
        return {**fallback, "reason": "no_mapped_pcm_evidence"}
    segments = []
    for row in activity.get("intervals", []):
        a, b = max(start_ms, row["start_ms"]), min(end_ms, row["end_ms"])
        if b > a:
            segments.append((a, b, row["state"]))
    cursor = start_ms
    for a, b, state in sorted(segments):
        if a != cursor or state not in {"instrumental_candidate", "vocal_candidate", "fullmix_silence_candidate", "padding"}:
            return {**fallback, "reason": "uncertain_pcm_evidence"}
        cursor = b
    if cursor != end_ms:
        return {**fallback, "reason": "incomplete_pcm_evidence"}
    scopes = {"general"}
    longest = run = 0
    for a, b, state in sorted(segments):
        run = run + b - a if state == "instrumental_candidate" else 0
        longest = max(longest, run)
    if longest >= minimum_instrumental_ms and longest > 0:
        position = activity.get("song_position")
        if position not in {"intro", "outro", "internal"}:
            return {**fallback, "reason": "unknown_song_position"}
        scopes.add("interlude" if position == "internal" else position)
    if any(state == "vocal_candidate" and any(
            previous_state == "instrumental_candidate" and previous_b == a
            for previous_a, previous_b, previous_state in segments)
           for a, b, state in segments):
        scopes.add("vocal_return")
    return {"texts": [c.text for c in candidates if c.scope in scopes],
            "eligible_scopes": sorted(scopes), "fallback": False,
            "reason": "observed_pcm_activity", "longest_instrumental_ms": longest}
