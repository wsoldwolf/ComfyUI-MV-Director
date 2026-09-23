"""Shared structural parser for the body of a common-prompt EMD section."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..artifacts.base import normalize_newlines


COMMON_HEADINGS = (
    "スタイル",
    "環境",
    "時間・照明",
    "モーション",
    "カメラ",
    "その他",
)


class CommonPromptError(ValueError):
    pass


_SHOT_DIRECTIVE = re.compile(r"`(演技|演出|カメラ)`[ \t]+(.+)\Z")


def split_shot_directive(text: str) -> tuple[str, str] | None:
    """Return the typed kind and original prose, without inferring meaning."""
    match = _SHOT_DIRECTIVE.fullmatch(text)
    if match is None:
        return None
    return match.group(1), match.group(2)


def shot_prose(text: str) -> str:
    typed = split_shot_directive(text)
    return typed[1] if typed is not None else text


@dataclass(frozen=True, slots=True)
class CommonSection:
    heading: str
    body: tuple[str, ...]
    line_number: int


def parse_common_prompt_fragment(
    source: str,
    *,
    allowed_headings: frozenset[str] | None = None,
) -> tuple[CommonSection, ...]:
    """Parse the same common-prompt prose for user, profile, and final EMD.

    This is syntax only. The caller supplies authority and purpose; neither
    profile metadata nor planning-only candidate sections belong here.
    """
    lines = [
        (number, line.strip())
        for number, line in enumerate(normalize_newlines(source).split("\n"), 1)
        if line.strip()
    ]
    if not lines or lines[0][1] != "# 共通プロンプト":
        raise CommonPromptError("line 1: expected '# 共通プロンプト'")
    if len(lines) == 1:
        raise CommonPromptError("# 共通プロンプト must not be empty")
    sections: list[CommonSection] = []
    previous = -1
    position = 1
    while position < len(lines):
        number, heading = lines[position]
        if not heading.startswith("## ") or heading[3:] not in COMMON_HEADINGS:
            raise CommonPromptError(f"line {number}: invalid common prompt subsection")
        name = heading[3:]
        if allowed_headings is not None and name not in allowed_headings:
            raise CommonPromptError(f"line {number}: ## {name} is not allowed here")
        order = COMMON_HEADINGS.index(name)
        if order <= previous:
            raise CommonPromptError(
                f"line {number}: common prompt subsection order is invalid"
            )
        previous = order
        position += 1
        body: list[str] = []
        while position < len(lines) and lines[position][1].startswith("* "):
            item_number, raw = lines[position]
            text = raw[2:]
            if not text or text.startswith("`"):
                raise CommonPromptError(
                    f"line {item_number}: invalid common prompt direction"
                )
            body.append(text)
            position += 1
        if not body:
            raise CommonPromptError(f"line {number}: ## {name} must not be empty")
        sections.append(CommonSection(name, tuple(body), number))
    return tuple(sections)
