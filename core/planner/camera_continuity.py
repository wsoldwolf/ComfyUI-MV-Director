"""Conservative Arc direction checks; never rewrite camera prose or Roll."""

from __future__ import annotations

import re
from typing import Mapping

_ARC = re.compile(r"\barc\s+shot\b|\bArc\b|アーク|回り込|周回|旋回", re.IGNORECASE)
_ROLL = re.compile(
    r"\broll\s+(?:counter[ -]?clockwise|anti[ -]?clockwise|clockwise)\b",
    re.IGNORECASE,
)
_COUNTER = re.compile(r"\b(?:counter[ -]?clockwise|anti[ -]?clockwise)\b|反時計回り|左回り", re.IGNORECASE)
_CLOCK = re.compile(r"\bclockwise\b|(?<!反)時計回り|右回り", re.IGNORECASE)


def arc_directions(text: str) -> frozenset[str]:
    """Recognize explicit directions in Arc clauses, excluding named Roll.

    Viewpoint (left/right side), performer turns and camera roll alone do not
    establish an orbit. Ambiguous prose is left to the LLM, not inferred here.
    """
    found: set[str] = set()
    for clause in re.split(r"[。.!?！？;；\n]", text):
        clause = _ROLL.sub("", clause)
        if not _ARC.search(clause):
            continue
        if _COUNTER.search(clause):
            found.add("counterclockwise")
        if _CLOCK.search(_COUNTER.sub("", clause)):
            found.add("clockwise")
    return frozenset(found)


def inspect_arc_sequence(
    cameras: Mapping[int, str], fixed: Mapping[int, str], inherited: str | None,
) -> tuple[dict[int, str], str | None]:
    """Keep orbit through non-Arc shots; author cameras define local overrides."""
    expected = inherited
    conflicts: dict[int, str] = {}
    for index, text in sorted(cameras.items()):
        directions = arc_directions(text)
        if index in fixed:
            # An authored change is intentional: never ask the LLM to edit it.
            if len(directions) == 1:
                expected = next(iter(directions))
            elif directions:
                expected = None
            continue
        if not directions:
            continue
        if expected is None:
            if len(directions) == 1:
                expected = next(iter(directions))
            # A two-direction first shot has no established path. Use its
            # first explicit direction as the repair target, not a global CW.
            else:
                without_roll = _ROLL.sub("", text)
                matches = [(match.start(), "counterclockwise")
                           for match in _COUNTER.finditer(without_roll)]
                clock_text = _COUNTER.sub(lambda m: " " * len(m.group()), without_roll)
                matches.extend((match.start(), "clockwise")
                               for match in _CLOCK.finditer(clock_text))
                expected = min(matches)[1]
        if directions != {expected}:
            conflicts[index] = expected
    return conflicts, expected
