"""MVD_OBSERVATIONS_V1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .base import (
    canonical_json,
    require_exact_keys,
    require_sequence,
    require_string,
)
from .errors import ArtifactValidationError


SCHEMA = "MVD_OBSERVATIONS_V1"
PROTOCOL = "MVD_VISION_OBSERVATION_LINES_V2"
HINT_STATUSES = {"not_used", "consistent", "ambiguous", "conflict"}
VISIBILITIES = {"clear", "partial", "uncertain"}
FEATURE_CATEGORIES = {
    "face",
    "hair",
    "eyes",
    "eyebrows",
    "ears",
    "body",
    "clothing",
    "footwear",
    "accessory",
    "tail",
    "distinctive_feature",
}


@dataclass(frozen=True, slots=True)
class SubjectFeature:
    category: str
    text: str
    visibility: str

    def validate(self) -> None:
        if self.category not in FEATURE_CATEGORIES:
            raise ArtifactValidationError(
                SCHEMA, "subject_features[].category", "unsupported category"
            )
        require_string(self.text, schema=SCHEMA, path="subject_features[].text")
        if self.visibility not in VISIBILITIES:
            raise ArtifactValidationError(
                SCHEMA, "subject_features[].visibility", "unsupported visibility"
            )

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "category": self.category,
            "text": self.text,
            "visibility": self.visibility,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubjectFeature":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="subject_features[]",
            required={"category", "text", "visibility"},
        )
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class ObservationsArtifact:
    overview: str
    primary_subject: str
    hint_status: str
    hint_reason: str
    subject_features: tuple[SubjectFeature, ...]
    subject_pose: str
    scene_setting: str
    scene_elements: tuple[str, ...]
    lighting: str
    time_weather: str
    shot_size: str
    viewpoint: str
    subject_placement: str
    depth: str
    style_medium: str
    style_rendering: str
    style_palette: str
    visible_text: tuple[str, ...]
    uncertainties: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...] = ()
    schema: str = SCHEMA
    protocol: str = PROTOCOL

    def validate(self) -> None:
        if self.schema != SCHEMA:
            raise ArtifactValidationError(SCHEMA, "schema", "schema mismatch")
        if self.protocol != PROTOCOL:
            raise ArtifactValidationError(SCHEMA, "protocol", "protocol mismatch")
        for field_name in (
            "overview",
            "primary_subject",
            "hint_reason",
            "subject_pose",
            "scene_setting",
            "lighting",
            "time_weather",
            "shot_size",
            "viewpoint",
            "subject_placement",
            "depth",
            "style_medium",
            "style_rendering",
            "style_palette",
        ):
            require_string(
                getattr(self, field_name),
                schema=SCHEMA,
                path=field_name,
                allow_empty=True,
            )
        if self.hint_status not in HINT_STATUSES:
            raise ArtifactValidationError(
                SCHEMA, "hint_assessment.status", "unsupported status"
            )
        for index, feature in enumerate(self.subject_features):
            if not isinstance(feature, SubjectFeature):
                raise ArtifactValidationError(
                    SCHEMA, f"subject_features[{index}]", "invalid feature"
                )
            feature.validate()
        for field_name in ("scene_elements", "visible_text", "uncertainties"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise ArtifactValidationError(
                    SCHEMA, field_name, "must be a tuple internally"
                )
            for index, item in enumerate(values):
                require_string(
                    item, schema=SCHEMA, path=f"{field_name}[{index}]"
                )
        for index, item in enumerate(self.provenance):
            if not isinstance(item, dict):
                raise ArtifactValidationError(
                    SCHEMA, f"provenance[{index}]", "must be a JSON object"
                )
            canonical_json(item)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": self.schema,
            "protocol": self.protocol,
            "overview": self.overview,
            "primary_subject": self.primary_subject,
            "hint_assessment": {
                "status": self.hint_status,
                "reason": self.hint_reason,
            },
            "subject_features": [
                feature.to_dict() for feature in self.subject_features
            ],
            "subject_pose": self.subject_pose,
            "scene": {
                "setting": self.scene_setting,
                "elements": list(self.scene_elements),
                "lighting": self.lighting,
                "time_weather": self.time_weather,
            },
            "composition": {
                "shot_size": self.shot_size,
                "viewpoint": self.viewpoint,
                "subject_placement": self.subject_placement,
                "depth": self.depth,
            },
            "style": {
                "medium": self.style_medium,
                "rendering": self.style_rendering,
                "palette": self.style_palette,
            },
            "visible_text": list(self.visible_text),
            "uncertainties": list(self.uncertainties),
            "provenance": list(self.provenance),
        }

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObservationsArtifact":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="$",
            required={
                "schema",
                "protocol",
                "overview",
                "primary_subject",
                "hint_assessment",
                "subject_features",
                "subject_pose",
                "scene",
                "composition",
                "style",
                "visible_text",
                "uncertainties",
                "provenance",
            },
        )
        hint = value["hint_assessment"]
        scene = value["scene"]
        composition = value["composition"]
        style = value["style"]
        for path, nested, keys in (
            ("hint_assessment", hint, {"status", "reason"}),
            ("scene", scene, {"setting", "elements", "lighting", "time_weather"}),
            (
                "composition",
                composition,
                {"shot_size", "viewpoint", "subject_placement", "depth"},
            ),
            ("style", style, {"medium", "rendering", "palette"}),
        ):
            if not isinstance(nested, Mapping):
                raise ArtifactValidationError(SCHEMA, path, "must be an object")
            require_exact_keys(
                nested, schema=SCHEMA, path=path, required=keys
            )
        features = require_sequence(
            value["subject_features"], schema=SCHEMA, path="subject_features"
        )
        scene_elements = require_sequence(
            scene["elements"], schema=SCHEMA, path="scene.elements"
        )
        visible_text = require_sequence(
            value["visible_text"], schema=SCHEMA, path="visible_text"
        )
        uncertainties = require_sequence(
            value["uncertainties"], schema=SCHEMA, path="uncertainties"
        )
        provenance = require_sequence(
            value["provenance"], schema=SCHEMA, path="provenance"
        )
        artifact = cls(
            schema=value["schema"],
            protocol=value["protocol"],
            overview=value["overview"],
            primary_subject=value["primary_subject"],
            hint_status=hint["status"],
            hint_reason=hint["reason"],
            subject_features=tuple(
                SubjectFeature.from_dict(item) for item in features
            ),
            subject_pose=value["subject_pose"],
            scene_setting=scene["setting"],
            scene_elements=tuple(scene_elements),
            lighting=scene["lighting"],
            time_weather=scene["time_weather"],
            shot_size=composition["shot_size"],
            viewpoint=composition["viewpoint"],
            subject_placement=composition["subject_placement"],
            depth=composition["depth"],
            style_medium=style["medium"],
            style_rendering=style["rendering"],
            style_palette=style["palette"],
            visible_text=tuple(visible_text),
            uncertainties=tuple(uncertainties),
            provenance=tuple(dict(item) for item in provenance),
        )
        artifact.validate()
        return artifact
