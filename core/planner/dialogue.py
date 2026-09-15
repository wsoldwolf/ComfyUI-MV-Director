"""Protect author dialogue and remove dialogue invented by a Planner LLM."""

from __future__ import annotations

from dataclasses import dataclass
import re


_D_TAG_RE = re.compile(r"<d(?:\[[^\]\r\n]+\])?>.*?</d>", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"__MVD_LOCKED_DIALOGUE_[0-9]{4}__")
_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'))


@dataclass(frozen=True, slots=True)
class ProtectedDialogue:
    placeholder: str
    text: str
    source_ref: str
    source_position: int


@dataclass(frozen=True, slots=True)
class DialogueFilterResult:
    texts: tuple[str, ...]
    removed_count: int
    unused_ids: tuple[str, ...]


class DialogueProtector:
    def __init__(self) -> None:
        self._records: list[ProtectedDialogue] = []

    @property
    def records(self) -> tuple[ProtectedDialogue, ...]:
        return tuple(self._records)

    def protect(self, text: str, *, source_ref: str) -> str:
        spans: list[tuple[int, int]] = []
        spans.extend((match.start(), match.end()) for match in _D_TAG_RE.finditer(text))
        for opening, closing in _PAIRS:
            if opening == closing:
                pattern = re.compile(re.escape(opening) + r".*?" + re.escape(closing), re.DOTALL)
            else:
                pattern = re.compile(re.escape(opening) + r".*?" + re.escape(closing), re.DOTALL)
            spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
        selected: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if selected and start < selected[-1][1]:
                continue
            selected.append((start, end))
        if not selected:
            return text
        pieces: list[str] = []
        cursor = 0
        for start, end in selected:
            pieces.append(text[cursor:start])
            placeholder = f"__MVD_LOCKED_DIALOGUE_{len(self._records) + 1:04d}__"
            self._records.append(
                ProtectedDialogue(placeholder, text[start:end], source_ref, start)
            )
            pieces.append(placeholder)
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces)


class DialogueFilter:
    def __init__(self, records: tuple[ProtectedDialogue, ...]) -> None:
        self._by_id = {record.placeholder: record for record in records}
        self._used: set[str] = set()
        self.removed_count = 0

    @property
    def unused_ids(self) -> tuple[str, ...]:
        return tuple(key for key in self._by_id if key not in self._used)

    def filter(self, source: str) -> str:
        def remove_placeholder(match: re.Match[str]) -> str:
            placeholder = match.group(0)
            if placeholder in self._by_id:
                self._used.add(placeholder)
            self.removed_count += 1
            return ""

        text = _PLACEHOLDER_RE.sub(remove_placeholder, source)
        text, count = _D_TAG_RE.subn("", text)
        self.removed_count += count
        if "<d" in text:
            position = text.find("<d")
            text = text[:position]
            self.removed_count += 1
        if "</d>" in text:
            self.removed_count += text.count("</d>")
            text = text.replace("</d>", "")
        for opening, closing in _PAIRS:
            text, count = _remove_pair(text, opening, closing)
            self.removed_count += count
        text = re.sub(r"[ \t]+", " ", text).strip()
        return text


def _remove_pair(text: str, opening: str, closing: str) -> tuple[str, int]:
    result: list[str] = []
    removed = 0
    index = 0
    while index < len(text):
        if text.startswith(opening, index):
            end = text.find(closing, index + len(opening))
            if end < 0:
                removed += 1
                break
            removed += 1
            index = end + len(closing)
            continue
        if opening != closing and text.startswith(closing, index):
            removed += 1
            index += len(closing)
            continue
        result.append(text[index])
        index += 1
    return "".join(result), removed


def filter_generated_dialogue(
    texts: tuple[str, ...], records: tuple[ProtectedDialogue, ...]
) -> DialogueFilterResult:
    dialogue_filter = DialogueFilter(records)
    output: list[str] = []
    for source in texts:
        text = dialogue_filter.filter(source)
        if text:
            output.append(text)
    return DialogueFilterResult(
        tuple(output), dialogue_filter.removed_count, dialogue_filter.unused_ids
    )
