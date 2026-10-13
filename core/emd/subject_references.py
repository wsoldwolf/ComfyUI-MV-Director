"""Canonicalize explicit grouped Subject references, not creative prose."""

from __future__ import annotations

import re


_GROUP = re.compile(r"`サブジェクト([1-4](?:[ \t]*[,、][ \t]*[1-4])+)`")
_SPOKEN = re.compile(r"「[^「」]*」|<d(?:\[[^\]\r\n]+\])?>.*?</d>", re.DOTALL)


def normalize_subject_references(text: str) -> str:
    """Expand backticked comma-separated IDs, preserving order and speech.

    Only explicit IDs 1..4 are supported. Bare prose, ranges, model metadata,
    lyrics in dialogue brackets, and H3 <d> spans are not inferred or repaired.
    Subject existence is checked by the normal EMD parser after expansion.
    """
    def expand(prose: str) -> str:
        return _GROUP.sub(
            lambda match: "、".join(
                f"`サブジェクト{number}`"
                for number in re.split(r"[ \t]*[,、][ \t]*", match.group(1))
            ),
            prose,
        )

    parts: list[str] = []
    cursor = 0
    for match in _SPOKEN.finditer(text):
        parts.extend((expand(text[cursor:match.start()]), match.group(0)))
        cursor = match.end()
    parts.append(expand(text[cursor:]))
    return "".join(parts)
