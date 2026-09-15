"""Render verified observations into one editable Subject EMD fragment."""

from __future__ import annotations

from dataclasses import dataclass

from core.artifacts.base import normalize_newlines
from core.artifacts.observations import ObservationsArtifact


class SubjectEMDError(ValueError):
    pass


_CONCEPT_PREFIX = {"person": "人物", "location": "場所", "object": "物品"}


@dataclass(frozen=True, slots=True)
class SubjectEMDResult:
    emd_fragment: str
    included_hint: bool
    omitted_uncertain_features: int


def _hint_lines(subject_hint: str) -> list[str]:
    normalized = normalize_newlines(subject_hint)
    if "\x00" in normalized:
        raise SubjectEMDError("subject_hint contains NUL")
    return [line for line in normalized.split("\n") if line]


def render_subject_emd(
    observations: ObservationsArtifact,
    *,
    concept_type: str,
    concept_index: int,
    subject_index: int,
    picture_index: int | None = None,
    subject_hint: str = "",
    hint_mode: str = "lock_identity",
    hint_conflict: str = "warn",
) -> SubjectEMDResult:
    observations.validate()
    if concept_type not in _CONCEPT_PREFIX:
        raise SubjectEMDError("concept_type must be person, location, or object")
    if not 1 <= concept_index <= 16:
        raise SubjectEMDError("concept_index must be in 1..16")
    if not 1 <= subject_index <= 4:
        raise SubjectEMDError("subject_index must be in 1..4")
    if picture_index is not None and not 1 <= picture_index <= 9:
        raise SubjectEMDError("picture_index must be in 1..9")
    if hint_mode not in {"observe_only", "assist", "lock_identity"}:
        raise SubjectEMDError("unknown hint_mode")
    if hint_conflict not in {"warn", "strict"}:
        raise SubjectEMDError("unknown hint_conflict")
    if hint_conflict == "strict" and observations.hint_status == "conflict":
        raise SubjectEMDError("Vision reported a clear subject_hint conflict")

    concept_id = f"{_CONCEPT_PREFIX[concept_type]}{concept_index}"
    lines = [
        "# サブジェクト",
        f"* `{concept_id}`",
        f"* `H3サブジェクト` `<Subject {subject_index}>`",
    ]
    if picture_index is not None:
        lines.append(f"* `参照画像` `<Picture {picture_index}>`")
    if observations.primary_subject:
        lines.append(f"* `名称` {observations.primary_subject}")

    descriptions: list[str] = []
    omitted_uncertain = 0
    if concept_type in {"person", "object"}:
        for feature in observations.subject_features:
            if feature.visibility == "uncertain":
                omitted_uncertain += 1
            else:
                descriptions.append(feature.text)
    else:
        if observations.scene_setting:
            descriptions.append(observations.scene_setting)
        descriptions.extend(observations.scene_elements)

    hint_values = _hint_lines(subject_hint)
    included_hint = hint_mode == "lock_identity" and bool(hint_values)
    if included_hint:
        descriptions.extend(hint_values)
    if not descriptions:
        fallback = observations.primary_subject or observations.overview
        if fallback:
            descriptions.append(fallback)
    if not descriptions:
        raise SubjectEMDError("observations contain no stable Subject description")
    lines.extend(f"* {description}" for description in descriptions)
    return SubjectEMDResult("\n".join(lines) + "\n", included_hint, omitted_uncertain)

