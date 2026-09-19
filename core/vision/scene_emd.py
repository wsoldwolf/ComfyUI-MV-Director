"""Render verified scene observations into one deterministic Scene EMD fragment."""

from __future__ import annotations

from dataclasses import dataclass

from ..artifacts import EMDTextArtifact, ObservationsArtifact, normalize_newlines
from ..emd import SceneSetting, render_scene_emd_fragment


@dataclass(frozen=True, slots=True)
class SceneEMDResult:
    artifact: EMDTextArtifact
    included_hint: bool

    @property
    def emd_fragment(self) -> str:
        return self.artifact.text


def _values(source: str) -> list[str]:
    return [value.strip() for value in normalize_newlines(source).split("\n") if value.strip()]


def render_scene_emd(
    observations: ObservationsArtifact,
    *,
    picture_index: int | None = None,
    scene_hint: str = "",
    hint_mode: str = "lock_identity",
) -> SceneEMDResult:
    """Build scene EMD without another model call or inferred semantics."""

    observations.validate()
    if picture_index is not None and not 1 <= picture_index <= 9:
        raise ValueError("picture_index must be in 1..9")
    if hint_mode not in {"observe_only", "assist", "lock_identity"}:
        raise ValueError("unknown hint_mode")

    environment: list[str] = []
    hint_values = _values(scene_hint)
    included_hint = hint_mode == "lock_identity" and bool(hint_values)
    if included_hint:
        environment.extend(hint_values)
    environment.extend(_values(observations.scene_setting))
    environment.extend(value.strip() for value in observations.scene_elements if value.strip())
    if not environment:
        environment.extend(_values(observations.overview))
    environment = list(dict.fromkeys(environment))
    if not environment:
        raise ValueError("scene observations contain no stable environment description")

    time_lighting = list(
        dict.fromkeys(
            [
                *_values(observations.time_weather),
                *_values(observations.lighting),
            ]
        )
    )
    setting = SceneSetting(
        environment=tuple(environment),
        time_lighting=tuple(time_lighting),
        picture_ref=(f"<Picture {picture_index}>" if picture_index is not None else None),
    )
    text = render_scene_emd_fragment(setting)
    return SceneEMDResult(
        artifact=EMDTextArtifact.create("MVD_SCENE_EMD_FRAGMENT_V1", text),
        included_hint=included_hint,
    )


__all__ = ["SceneEMDResult", "render_scene_emd"]
