"""Strict parser for the user-authored Direction EMD passthrough fragment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..artifacts import normalize_newlines


_COMMON = ("スタイル", "環境", "時間・照明", "モーション", "カメラ", "その他")
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
        if lines[position] != "# 共通プロンプト":
            raise DirectionPassthroughError(
                f"line {position + 1}: expected '# 共通プロンプト'"
            )
        position += 1
        previous = -1
        while position < len(lines):
            heading = lines[position]
            if not heading.startswith("## ") or heading[3:] not in _COMMON:
                raise DirectionPassthroughError(
                    f"line {position + 1}: invalid common prompt subsection"
                )
            name = heading[3:]
            order = _COMMON.index(name)
            if order <= previous:
                raise DirectionPassthroughError(
                    f"line {position + 1}: common prompt subsection order is invalid"
                )
            previous = order
            position += 1
            values = sections[_FIELD[name]]
            while position < len(lines) and lines[position].startswith("* "):
                body = lines[position][2:]
                if not body or body.startswith("`"):
                    raise DirectionPassthroughError(
                        f"line {position + 1}: invalid passthrough direction"
                    )
                values.append(body)
                position += 1
            if not values:
                raise DirectionPassthroughError(f"## {name} must not be empty")

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
