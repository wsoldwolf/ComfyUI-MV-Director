"""Subject identifiers and advisory performer metadata, never noun inference."""

from __future__ import annotations

import json
import re

from ..artifacts import canonical_json
from ..emd import merge_subject_emd
from ..emd.subject_references import normalize_subject_references


# Recognize out-of-range tokens too, so they cannot be treated as anonymous.
_SUBJECT_TOKEN = re.compile(r"`(サブジェクト[0-9]+)`")
_PERFORMER_SUFFIX = re.compile(
    r"[｜|]\s*PERFORMER\s*=\s*([^｜|]*?)(?:[｜|]\s*END_STATE\s*=\s*(.*))?\Z"
)


def subject_ids_from_emd(concept_emd: str) -> tuple[str, ...]:
    return tuple(item.concept_id for item in merge_subject_emd(concept_emd).bindings)


def explicit_subjects(text: str) -> frozenset[str]:
    return frozenset(_SUBJECT_TOKEN.findall(normalize_subject_references(text)))


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Subject state")
        result[key] = value
    return result


def performer_states(state: str, subject_ids: tuple[str, ...]) -> dict[str, str]:
    """Read an actor-keyed END_STATE, not the meaning of poses or roles."""
    try:
        value = json.loads(state, object_pairs_hook=_unique_fields)
    except (TypeError, ValueError):
        return {}
    if (not isinstance(value, dict) or not value or not set(value).issubset(subject_ids)
            or not all(isinstance(v, str) and v.strip() and len(v) <= 240
                       and not any(ord(c) < 32 for c in v) for v in value.values())):
        return {}
    return value


def split_performer_metadata(
    prose: str, state: str, subject_ids: tuple[str, ...],
) -> tuple[str, str, str]:
    """Remove the optional transport suffix, even if its actor is invalid.

    Missing or invalid metadata does not invalidate the creative prose. A
    unique explicit Subject token in the prose is an unambiguous identity
    fallback; several actors are never arbitrarily reduced to Subject 1.
    """
    performer = ""
    match = _PERFORMER_SUFFIX.search(prose)
    if match and prose[:match.start()].strip():
        prose, identifier = prose[:match.start()].rstrip(), match.group(1).strip()
        if match.group(2) is not None:
            state = match.group(2).strip()
        if identifier in subject_ids:
            performer = identifier
    if not performer:
        identifiers = explicit_subjects(prose)
        if len(identifiers) == 1 and identifiers.issubset(subject_ids):
            performer = next(iter(identifiers))
    states = performer_states(state, subject_ids)
    return prose, performer, canonical_json(states) if states else ""


def bind_motion_composition(composition, performer: str, subject_ids: tuple[str, ...]):
    """Scope an anonymous supplement using an LLM-selected identity only.

    Explicit author Subject tokens keep their own authority, including a
    multi-person phrase. No action words or body-part instructions are edited.
    """
    identifiers = explicit_subjects(composition[4])
    if identifiers:
        return composition if identifiers.issubset(subject_ids) else None
    if performer not in subject_ids:
        return None
    return (*composition[:4], f"`{performer}` {composition[4]}")
