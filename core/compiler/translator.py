"""One-to-one translation boundary used by the Ref2VA compiler."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .errors import CompilerError


class PromptTranslator(Protocol):
    def translate(self, units: Sequence[str]) -> Sequence[str]:
        """Translate each unit without adding, removing, or reordering units."""


class IdentityTranslator:
    """Explicit already-English mode. It never loads a model."""

    def translate(self, units: Sequence[str]) -> Sequence[str]:
        return tuple(units)


def translate_exact(
    translator: PromptTranslator, units: Sequence[str]
) -> tuple[str, ...]:
    if not units:
        return ()
    result = tuple(translator.translate(tuple(units)))
    if len(result) != len(units):
        raise CompilerError(
            f"translator returned {len(result)} units for {len(units)} inputs"
        )
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise CompilerError("translator returned an empty or non-string unit")
    return result

