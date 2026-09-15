"""Strict parser for the MV Director plain-lyrics format."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from ..artifacts.base import normalize_newlines
from .errors import LyricSegmentationError


_SECTION_RE = re.compile(
    r"\[([A-Z][A-Z0-9_-]*)\]\Z",
    re.IGNORECASE | re.ASCII,
)
_ATOMIC_RE = re.compile(r"[^ \t\u3000]+")
_LRC_RE = re.compile(r"\[[0-9]{1,3}:[0-5][0-9](?:[.:][0-9]{1,3})?\]")
_SRT_TIME_RE = re.compile(
    r"[0-9]{2}:[0-5][0-9]:[0-5][0-9][,.][0-9]{3}\s*-->"
)


@dataclass(frozen=True, slots=True)
class SourceLyricSegment:
    segment_id: str
    text: str
    section: str
    source_line: int
    source_start: int
    source_end: int
    normalized: str


def _katakana_to_hiragana(text: str) -> str:
    result: list[str] = []
    for character in text:
        codepoint = ord(character)
        result.append(
            chr(codepoint - 0x60)
            if 0x30A1 <= codepoint <= 0x30F6
            else character
        )
    return "".join(result)


def normalize_match_text(text: str) -> str:
    """Normalize only the comparison form; author text is never changed."""

    normalized = _katakana_to_hiragana(unicodedata.normalize("NFKC", text).casefold())
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] not in {"P", "Z"}
    )


def parse_plain_lyrics(text: str) -> tuple[SourceLyricSegment, ...]:
    if not isinstance(text, str):
        raise LyricSegmentationError("lyrics_text must be a string")
    source = normalize_newlines(text)
    if "\x00" in source:
        raise LyricSegmentationError("lyrics_text must not contain NUL")

    current_section: str | None = None
    saw_nonempty = False
    result: list[SourceLyricSegment] = []
    for line_number, line in enumerate(source.split("\n"), 1):
        if line == "":
            continue
        saw_nonempty = True
        section_match = _SECTION_RE.fullmatch(line)
        if section_match:
            current_section = section_match.group(1).upper()
            continue
        if current_section is None:
            raise LyricSegmentationError(
                f"lyrics line {line_number}: first nonempty line must be a section "
                "heading such as [VERSE1] or [Chorus]"
            )
        if (
            line != line.strip()
            or line.startswith(("#", "//", ";"))
            or _LRC_RE.search(line)
            or _SRT_TIME_RE.search(line)
            or line.isdecimal()
            or (line.startswith("[") and line.endswith("]"))
        ):
            raise LyricSegmentationError(
                f"lyrics line {line_number}: metadata, comments, timestamps, and surrounding whitespace are not allowed"
            )
        for match in _ATOMIC_RE.finditer(line):
            normalized = normalize_match_text(match.group(0))
            if not normalized:
                raise LyricSegmentationError(
                    f"lyrics line {line_number}: segment is empty after match normalization"
                )
            result.append(
                SourceLyricSegment(
                    segment_id=f"lyric_{len(result) + 1:04d}",
                    text=match.group(0),
                    section=current_section,
                    source_line=line_number,
                    source_start=match.start(),
                    source_end=match.end(),
                    normalized=normalized,
                )
            )
    if not saw_nonempty:
        raise LyricSegmentationError("lyrics_text must contain a section heading")
    return tuple(result)
