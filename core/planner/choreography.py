"""Finite choreography selection transport for opt-in Motion profiles."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence


_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
FREEFORM_CHOREOGRAPHY = "FREEFORM"


def build_choreography_choice_grammar(ids: Sequence[str]) -> str:
    """Constrain one Scene choice to a profile-owned ID, never authored prose."""
    if not ids or len(set(ids)) != len(ids) or any(
        not _ID_RE.fullmatch(value) for value in ids
    ):
        raise ValueError("choreography choices require distinct profile IDs")
    choices = " | ".join(json.dumps(value) for value in (*ids, FREEFORM_CHOREOGRAPHY))
    return 'root ::= "CHOICE\\t1\\t" choice "\\n"?\n' + f"choice ::= {choices}\n"


def accept_choreography_choice(value: str, ids: Sequence[str]) -> str | None:
    """Validate the model's finite choice without repairing its response."""
    return value if value in (*ids, FREEFORM_CHOREOGRAPHY) else None
