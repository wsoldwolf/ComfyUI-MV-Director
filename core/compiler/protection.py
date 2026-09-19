"""Mechanical protection for tokens and author-authored dialogue.

Protected spans are split out of translation input entirely. They are never
represented by placeholders which a small language model could edit, omit, or
reorder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..emd.ast import Subject
from ..h3_contract import (
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
    FACE_PERFORMANCE_CUT_ACTION,
    FACE_PERFORMANCE_CUT_CAMERA,
)

_CONCEPT_RE = re.compile(r"`(サブジェクト[1-4])`")
_MEDIA_RE = re.compile(r"`(画像([1-9])|動画([1-3])|音声([1-3]))`")
_REFERENCE_RE = re.compile(
    r"<(?:Subject [1-4]|Picture [1-9]|Video [1-3]|Audio [1-3])>"
)
_D_SPAN_RE = re.compile(r"<d(?:\[[^\]\r\n]+\])?>.*?</d>")
_DIALOGUE_RE = re.compile(r"「([^「」]*)」")
_H3_CAMERA_DIRECTIVES = (
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
    FACE_PERFORMANCE_CUT_ACTION,
    FACE_PERFORMANCE_CUT_CAMERA,
    "Roll Counterclockwise",
    "Roll Clockwise",
    "Shake Slightly",
    "Shake Strongly",
    "Pedestal Down",
    "Pedestal Up",
    "Tracking Shot",
    "Static Shot",
    "Arc Shot",
    "Truck Right",
    "Truck Left",
    "Push In",
    "Pull Out",
    "Zoom In",
    "Zoom Out",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "with small amplitude",
    "with large amplitude",
    "at slow speed",
    "at fast speed",
    "POV",
)
_H3_CAMERA_DIRECTIVE_RE = re.compile(
    "(?:" + "|".join(re.escape(value) for value in _H3_CAMERA_DIRECTIVES) + ")"
)


@dataclass(frozen=True, slots=True)
class ProtectedUnit:
    fragments: tuple[str, ...]
    values: tuple[str, ...]

    @property
    def text(self) -> str:
        """Return the converted source text, including the protected spans."""

        output: list[str] = []
        for index, fragment in enumerate(self.fragments):
            output.append(fragment)
            if index < len(self.values):
                output.append(self.values[index])
        return "".join(output)

    def restore(self, translated_fragments: dict[int, str] | None = None) -> str:
        """Interleave translated ordinary fragments with untouched spans."""

        translated_fragments = translated_fragments or {}
        output: list[str] = []

        def append(piece: str, *, protected_boundary: bool) -> None:
            if (
                protected_boundary
                and output
                and output[-1]
                and piece
                and not output[-1][-1].isspace()
                and not piece[0].isspace()
                and (
                    (
                        output[-1][-1] == ">"
                        and re.match(r"[A-Za-z0-9]", piece[0])
                    )
                    or (
                        piece[0] == "<"
                        and re.match(r"[A-Za-z0-9>]", output[-1][-1])
                    )
                )
            ):
                output.append(" ")
            output.append(piece)

        for index, fragment in enumerate(self.fragments):
            append(
                translated_fragments.get(index, fragment),
                protected_boundary=index > 0,
            )
            if index < len(self.values):
                append(self.values[index], protected_boundary=True)
        return "".join(output)


def protect_unit(text: str, subjects: tuple[Subject, ...]) -> ProtectedUnit:
    subject_refs = {subject.concept_id: subject.subject_ref for subject in subjects}
    text = _CONCEPT_RE.sub(
        lambda match: subject_refs.get(match.group(1), match.group(0)), text
    )
    text = _MEDIA_RE.sub(
        lambda match: (
            f"<Picture {match.group(2)}>"
            if match.group(2)
            else f"<Video {match.group(3)}>"
            if match.group(3)
            else f"<Audio {match.group(4)}>"
        ),
        text,
    )
    text = _DIALOGUE_RE.sub(lambda match: f"<d>[Japanese]{match.group(1)}</d>", text)

    combined = re.compile(
        f"(?:{_D_SPAN_RE.pattern}|{_REFERENCE_RE.pattern}|"
        f"{_H3_CAMERA_DIRECTIVE_RE.pattern})"
    )
    fragments: list[str] = []
    values: list[str] = []
    cursor = 0
    for match in combined.finditer(text):
        fragments.append(text[cursor : match.start()])
        values.append(match.group(0))
        cursor = match.end()
    fragments.append(text[cursor:])
    return ProtectedUnit(tuple(fragments), tuple(values))
