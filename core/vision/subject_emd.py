"""Render verified observations into one editable Subject EMD fragment."""

from __future__ import annotations

from dataclasses import dataclass

from ..artifacts.base import normalize_newlines
from ..artifacts.observations import ObservationsArtifact


class SubjectEMDError(ValueError):
    pass


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
    picture_index: int | None = None,
    subject_hint: str = "",
    hint_mode: str = "lock_identity",
    hint_conflict: str = "warn",
) -> SubjectEMDResult:
    observations.validate()
    if concept_type not in {"person", "location", "object"}:
        raise SubjectEMDError("concept_type must be person, location, or object")
    if picture_index is not None and not 1 <= picture_index <= 9:
        raise SubjectEMDError("picture_index must be in 1..9")
    if hint_mode not in {"observe_only", "assist", "lock_identity"}:
        raise SubjectEMDError("unknown hint_mode")
    if hint_conflict not in {"warn", "strict"}:
        raise SubjectEMDError("unknown hint_conflict")
    if hint_conflict == "strict" and observations.hint_status == "conflict":
        raise SubjectEMDError("Vision reported a clear subject_hint conflict")

    descriptions: list[str] = []
    if observations.primary_subject:
        descriptions.append(observations.primary_subject)
    hint_values = _hint_lines(subject_hint)
    included_hint = hint_mode == "lock_identity" and bool(hint_values)
    if included_hint:
        descriptions.append(
            "優先して保持する識別特徴: " + " ".join(hint_values)
        )
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

    if not descriptions:
        fallback = observations.primary_subject or observations.overview
        if fallback:
            descriptions.append(fallback)
    if not descriptions:
        raise SubjectEMDError("observations contain no stable Subject description")
    descriptions = list(dict.fromkeys(value.strip() for value in descriptions if value.strip()))
    prefix = f"`画像{picture_index}` " if picture_index is not None else ""
    lines = ["# サブジェクト", f"* {prefix}{' '.join(descriptions)}"]
    return SubjectEMDResult("\n".join(lines) + "\n", included_hint, omitted_uncertain)
