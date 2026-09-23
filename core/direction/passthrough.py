"""Strict parser for the user-authored Direction EMD passthrough fragment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..artifacts import normalize_newlines
from ..emd.common import (
    COMMON_HEADINGS,
    CommonPromptError,
    parse_common_prompt_fragment,
)


_FIELD = {
    "スタイル": "style",
    "環境": "environment",
    "時間・照明": "time_lighting",
    "モーション": "motion",
    "カメラ": "camera",
    "その他": "other",
}
_RETENTION_RE = re.compile(
    r"`(サブジェクト[1-4])`:\s*"
    r"`(fully_preserved|partially_preserved)`\s+(.+)\Z"
)


class DirectionPassthroughError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DirectionPassthrough:
    retention: tuple[str, ...] = ()
    style: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    time_lighting: tuple[str, ...] = ()
    motion: tuple[str, ...] = ()
    camera: tuple[str, ...] = ()
    other: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.retention,
                self.style,
                self.environment,
                self.time_lighting,
                self.motion,
                self.camera,
                self.other,
            )
        )


def _subject_count(concept_emd: str) -> int:
    return sum(
        1
        for line in normalize_newlines(concept_emd).strip().split("\n")
        if line.startswith("* ")
    )


def parse_direction_passthrough(
    source: str, *, concept_emd: str = ""
) -> DirectionPassthrough:
    text = normalize_newlines(source).strip()
    if not text:
        return DirectionPassthrough()
    raw_lines = text.split("\n")
    if any(not line.strip() for line in raw_lines):
        lines = [line for line in raw_lines if line.strip()]
    else:
        lines = raw_lines
    position = 0
    retention: list[str] = []
    sections: dict[str, list[str]] = {name: [] for name in _FIELD.values()}

    if lines[position] == "# 保持分析":
        position += 1
        while position < len(lines) and lines[position].startswith("* "):
            body = lines[position][2:]
            match = _RETENTION_RE.fullmatch(body)
            if match is None:
                raise DirectionPassthroughError(
                    f"line {position + 1}: invalid retention record"
                )
            retention.append(body)
            position += 1
        if not retention:
            raise DirectionPassthroughError("# 保持分析 must not be empty")

    if position < len(lines):
        try:
            parsed = parse_common_prompt_fragment("\n".join(lines[position:]))
        except CommonPromptError as exc:
            raise DirectionPassthroughError(str(exc)) from exc
        for item in parsed:
            sections[_FIELD[item.heading]].extend(item.body)
        position = len(lines)

    if position != len(lines):
        raise DirectionPassthroughError(f"line {position + 1}: unexpected content")
    result = DirectionPassthrough(retention=tuple(retention), **sections)
    if result.empty:
        raise DirectionPassthroughError("Direction EMD passthrough is empty")

    if result.retention:
        count = _subject_count(concept_emd)
        if count == 0:
            raise DirectionPassthroughError(
                "passthrough retention requires concept_emd subjects"
            )
        allowed = {f"サブジェクト{index}" for index in range(1, count + 1)}
        seen: set[str] = set()
        for line in result.retention:
            concept_id = _RETENTION_RE.fullmatch(line).group(1)  # type: ignore[union-attr]
            if concept_id not in allowed:
                raise DirectionPassthroughError(
                    f"retention references undefined {concept_id}"
                )
            if concept_id in seen:
                raise DirectionPassthroughError(
                    f"duplicate retention record for {concept_id}"
                )
            seen.add(concept_id)
    return result
