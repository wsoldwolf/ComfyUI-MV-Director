"""Strict adapters for Template and Subject-fragment EMD."""

from __future__ import annotations

from dataclasses import dataclass

from ..artifacts import normalize_newlines
from ..emd import (
    EMDDocument,
    Scene,
    parse_emd,
    parse_scene_emd_fragment,
    render_scene_emd_fragment,
)
from ..emd.errors import EMDParseError
from ..h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
from .errors import TimelinePlannerError


DEFAULT_CONCEPT_EMD = """# サブジェクト
* 詳細未指定の主要人物。
"""

_PROBE_SCENE = """
> `シーン` 1
# シーン 00:00.000 --> 00:00.208
* `H3長` 5
## ショット 00:00.000
* 未計画
"""


@dataclass(frozen=True, slots=True)
class PlannerTemplate:
    scenes: tuple[Scene, ...]

    @property
    def shot_keys(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (scene.scene_number, shot_index)
            for scene in self.scenes
            for shot_index, _ in enumerate(scene.shots, 1)
        )


def normalize_concept_emd(
    concept_emd: str,
    *,
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> str:
    if not isinstance(concept_emd, str):
        raise TimelinePlannerError("concept_emd must be a string")
    normalized = normalize_newlines(concept_emd).strip()
    if not normalized:
        normalized = DEFAULT_CONCEPT_EMD.strip()
    headings = [line for line in normalized.split("\n") if line.startswith("# ")]
    if headings != ["# サブジェクト"]:
        raise TimelinePlannerError("concept_emd must be one # サブジェクト fragment")
    try:
        parse_emd(normalized + "\n" + _PROBE_SCENE, timing_profile=timing_profile)
    except EMDParseError as exc:
        raise TimelinePlannerError(f"invalid concept_emd: {exc}") from exc
    return normalized + "\n"


def normalize_scene_emd(scene_emd: str) -> str:
    if not isinstance(scene_emd, str):
        raise TimelinePlannerError("scene_emd must be a string")
    normalized = normalize_newlines(scene_emd).strip()
    if not normalized:
        return ""
    try:
        return render_scene_emd_fragment(parse_scene_emd_fragment(normalized))
    except ValueError as exc:
        raise TimelinePlannerError(f"invalid scene_emd: {exc}") from exc


def parse_template_emd(
    template_emd: str,
    *,
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> PlannerTemplate:
    if not isinstance(template_emd, str) or not template_emd.strip():
        raise TimelinePlannerError("template_emd must be a nonempty string")
    normalized = normalize_newlines(template_emd).strip()
    if any(line.startswith("# サブジェクト") for line in normalized.split("\n")):
        raise TimelinePlannerError("template_emd must not contain a Subject section")
    try:
        document: EMDDocument = parse_emd(
            DEFAULT_CONCEPT_EMD.rstrip() + "\n\n" + normalized + "\n",
            timing_profile=timing_profile,
        )
    except EMDParseError as exc:
        raise TimelinePlannerError(f"invalid template_emd: {exc}") from exc
    for scene in document.scenes:
        if scene.audio_directives:
            raise TimelinePlannerError("template_emd must not preselect an audio mode")
        for shot in scene.shots:
            if shot.lyric_lip_sync:
                raise TimelinePlannerError("template_emd must not contain lyric lip-sync directives")
    return PlannerTemplate(document.scenes)
