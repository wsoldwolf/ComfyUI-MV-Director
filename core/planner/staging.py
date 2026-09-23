"""Transport-only handling for LLM-selected, Scene-local staging ideas."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence


_CHOICE_RE = re.compile(r"\AC([1-9][0-9]*)\|(.+)\Z")


def build_staging_selection_grammar(candidate_ids: Sequence[str]) -> str:
    """Constrain the record envelope and candidate ID, not its spatial prose."""

    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("Staging selection requires distinct candidate IDs")
    if any(not re.fullmatch(r"C[1-9][0-9]*", value) for value in candidate_ids):
        raise ValueError("Invalid staging candidate ID")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    choices = " | ".join(quote(value + "|") + " anchor" for value in candidate_ids)
    return (
        'root ::= "STAGING\\t1\\t" ("NONE|なし" | ' + choices + ') "\\n"?\n'
        'anchor ::= [^\\x00-\\x1f|｜]+\n'
    )


def parse_staging_selection(
    response: str,
    candidates: Sequence[str],
    *,
    current_target: str = "",
) -> tuple[int, str] | None:
    """Validate an LLM choice without choosing or composing natural language."""

    if response == "NONE|なし":
        return None
    match = _CHOICE_RE.fullmatch(response)
    if match is None:
        raise ValueError("Staging selection must be Cn|anchor or NONE|なし")
    index = int(match.group(1))
    anchor = match.group(2).strip()
    if not 1 <= index <= len(candidates):
        raise ValueError("Staging candidate ID is outside the supplied list")
    if (
        not anchor
        or len(anchor) > 180
        or any(ord(char) < 32 for char in anchor)
        or "|" in anchor
        or "｜" in anchor
    ):
        raise ValueError("Invalid staging spatial anchor")
    if anchor != "なし" and (
        not current_target or not anchor.startswith(current_target)
    ):
        raise ValueError("Staging spatial anchor requires the selected lyric target as its prefix")
    if anchor != "なし" and current_target not in candidates[index - 1]:
        raise ValueError("Staging candidate must itself name the selected lyric target")
    if anchor == "なし" and current_target and current_target in candidates[index - 1]:
        raise ValueError("A candidate naming the current lyric target requires a spatial anchor")
    return index, anchor
