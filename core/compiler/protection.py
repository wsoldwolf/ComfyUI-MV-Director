"""Mechanical protection for tokens and author-authored dialogue."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..emd.ast import Subject

from .errors import CompilerError


_CONCEPT_RE = re.compile(r"`((?:人物|場所|物品)(?:[1-9]|1[0-6]))`")
_REFERENCE_RE = re.compile(
    r"<(?:Subject [1-4]|Picture [1-9]|Video [1-9]|Audio [1-3])>"
)
_D_SPAN_RE = re.compile(r"<d(?:\[[^\]\r\n]+\])?>.*?</d>")
_DIALOGUE_RE = re.compile(r"「([^「」]*)」")
_PLACEHOLDER_RE = re.compile(r"⟪MVD_PROTECTED_[0-9]{4}⟫")


@dataclass(frozen=True, slots=True)
class ProtectedUnit:
    text: str
    values: tuple[str, ...]

    def restore(self, translated: str) -> str:
        actual = _PLACEHOLDER_RE.findall(translated)
        expected = [f"⟪MVD_PROTECTED_{index:04d}⟫" for index in range(len(self.values))]
        if actual != expected:
            raise CompilerError("translator changed, removed, or reordered a protected span")
        result = translated
        for placeholder, value in zip(expected, self.values):
            result = result.replace(placeholder, value, 1)
        return result


def protect_unit(text: str, subjects: tuple[Subject, ...]) -> ProtectedUnit:
    subject_refs = {subject.concept_id: subject.subject_ref for subject in subjects}
    text = _CONCEPT_RE.sub(
        lambda match: subject_refs.get(match.group(1), match.group(0)), text
    )
    text = _DIALOGUE_RE.sub(lambda match: f"<d>[Japanese]{match.group(1)}</d>", text)

    values: list[str] = []

    def replace(match: re.Match[str]) -> str:
        placeholder = f"⟪MVD_PROTECTED_{len(values):04d}⟫"
        values.append(match.group(0))
        return placeholder

    combined = re.compile(f"(?:{_D_SPAN_RE.pattern}|{_REFERENCE_RE.pattern})")
    return ProtectedUnit(combined.sub(replace, text), tuple(values))
