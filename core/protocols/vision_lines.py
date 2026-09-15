"""Strict fixed-order parser for MVD_VISION_OBSERVATION_LINES_V1."""

from __future__ import annotations

from dataclasses import dataclass

from core.artifacts.base import normalize_newlines
from core.artifacts.observations import (
    FEATURE_CATEGORIES,
    HINT_STATUSES,
    VISIBILITIES,
    ObservationsArtifact,
    SubjectFeature,
)

from .vision_contract import VISION_END_MARKER, VISION_PROTOCOL_ID


class VisionProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VisionParseResult:
    observations: ObservationsArtifact
    warnings: tuple[str, ...] = ()


def _value(parts: list[str], start: int, context: str, *, allow_empty: bool) -> str:
    fragments = [part.strip() for part in parts[start:] if part.strip()]
    value = "、".join(fragments)
    if not value and not allow_empty:
        raise VisionProtocolError(f"{context} must not be empty")
    return value


class _VisionParser:
    def __init__(self, content: str, allow_missing_end: bool) -> None:
        if not isinstance(content, str):
            raise VisionProtocolError("Vision response must be a string")
        if "\x00" in content:
            raise VisionProtocolError("NUL is not allowed")
        normalized = normalize_newlines(content)
        self.lines = [line for line in normalized.split("\n") if line != ""]
        if any(line.startswith("```") for line in self.lines):
            raise VisionProtocolError("Markdown code fences are not allowed")
        if any("<Picture " in line or "<Subject " in line for line in self.lines):
            raise VisionProtocolError("H3 reference tags are not allowed")
        self.cursor = 0
        self.allow_missing_end = allow_missing_end
        self.warnings: list[str] = []

    def current(self) -> str | None:
        return self.lines[self.cursor] if self.cursor < len(self.lines) else None

    def take_scalar(self, record_type: str, *, allow_empty: bool = True) -> str:
        line = self.current()
        if line is None:
            raise VisionProtocolError(f"expected {record_type}")
        parts = line.split("\t")
        if not parts or parts[0] != record_type:
            raise VisionProtocolError(
                f"line {self.cursor + 1}: expected {record_type}, found {parts[0]!r}"
            )
        if len(parts) == 1 and allow_empty:
            self.warnings.append(
                f"normalized empty {record_type} without TAB at line {self.cursor + 1}"
            )
            value = ""
        elif len(parts) < 2:
            raise VisionProtocolError(f"{record_type} has no value field")
        else:
            value = _value(parts, 1, record_type, allow_empty=allow_empty)
            if len(parts) > 2:
                self.warnings.append(
                    f"merged TAB-separated {record_type} value fragments at line "
                    f"{self.cursor + 1}"
                )
        self.cursor += 1
        return value

    def take_keyed(self, record_type: str, key: str) -> str:
        line = self.current()
        if line is None:
            raise VisionProtocolError(f"expected {record_type} {key}")
        parts = line.split("\t")
        if len(parts) < 2 or parts[:2] != [record_type, key]:
            found = "\t".join(parts[:2])
            raise VisionProtocolError(
                f"line {self.cursor + 1}: expected {record_type} {key}, found {found!r}"
            )
        value = _value(parts, 2, f"{record_type} {key}", allow_empty=True)
        if len(parts) != 3:
            self.warnings.append(
                f"normalized TAB-separated {record_type} {key} value at line "
                f"{self.cursor + 1}"
            )
        self.cursor += 1
        return value

    def parse(self) -> VisionParseResult:
        if not self.lines or self.lines[0] != VISION_PROTOCOL_ID:
            raise VisionProtocolError(
                f"Vision response must start with {VISION_PROTOCOL_ID}"
            )
        self.cursor = 1
        overview = self.take_scalar("OVERVIEW", allow_empty=False)
        primary_subject = self.take_scalar("PRIMARY_SUBJECT")

        line = self.current()
        if line is None:
            raise VisionProtocolError("expected HINT_ASSESSMENT")
        parts = line.split("\t")
        if len(parts) < 2 or parts[0] != "HINT_ASSESSMENT":
            raise VisionProtocolError(
                f"line {self.cursor + 1}: expected HINT_ASSESSMENT"
            )
        hint_status = parts[1].strip()
        if hint_status not in HINT_STATUSES:
            raise VisionProtocolError(
                f"HINT_ASSESSMENT uses unknown status {hint_status!r}"
            )
        hint_reason = _value(
            parts, 2, "HINT_ASSESSMENT reason", allow_empty=True
        )
        if hint_status == "not_used" and hint_reason:
            raise VisionProtocolError("not_used HINT_ASSESSMENT must have no reason")
        if hint_status != "not_used" and not hint_reason:
            raise VisionProtocolError(f"{hint_status} HINT_ASSESSMENT requires a reason")
        if len(parts) != 3:
            self.warnings.append(
                f"normalized HINT_ASSESSMENT reason at line {self.cursor + 1}"
            )
        self.cursor += 1

        features: list[SubjectFeature] = []
        while (line := self.current()) is not None and line.startswith(
            "SUBJECT_FEATURE\t"
        ):
            parts = line.split("\t")
            if len(parts) < 3:
                raise VisionProtocolError("SUBJECT_FEATURE has too few fields")
            category = parts[1].strip()
            if category not in FEATURE_CATEGORIES:
                raise VisionProtocolError(
                    f"SUBJECT_FEATURE uses unknown category {category!r}"
                )
            raw_visibility = parts[-1].strip().casefold()
            if len(parts) == 3 and raw_visibility not in VISIBILITIES | {"visible"}:
                visibility = "partial"
                description_parts = parts[2:]
                self.warnings.append(
                    f"defaulted missing SUBJECT_FEATURE visibility to partial at line "
                    f"{self.cursor + 1}"
                )
            else:
                visibility = "clear" if raw_visibility == "visible" else raw_visibility
                description_parts = parts[2:-1]
                if raw_visibility == "visible":
                    self.warnings.append(
                        f"normalized SUBJECT_FEATURE visibility visible to clear at line "
                        f"{self.cursor + 1}"
                    )
            if visibility not in VISIBILITIES:
                raise VisionProtocolError(
                    f"SUBJECT_FEATURE uses unknown visibility {raw_visibility!r}"
                )
            description = _value(
                ["SUBJECT_FEATURE", *description_parts],
                1,
                "SUBJECT_FEATURE text",
                allow_empty=False,
            )
            if len(description_parts) > 1:
                self.warnings.append(
                    f"merged SUBJECT_FEATURE text fragments at line {self.cursor + 1}"
                )
            features.append(SubjectFeature(category, description, visibility))
            self.cursor += 1

        subject_pose = self.take_scalar("SUBJECT_POSE")
        scene_setting = self.take_scalar("SCENE_SETTING")
        scene_elements: list[str] = []
        while (line := self.current()) is not None and line.startswith("SCENE_ELEMENT\t"):
            scene_elements.append(self.take_scalar("SCENE_ELEMENT", allow_empty=False))
        lighting = self.take_scalar("LIGHTING")
        time_weather = self.take_scalar("TIME_WEATHER")

        composition = {
            key: self.take_keyed("COMPOSITION", key)
            for key in ("shot_size", "viewpoint", "subject_placement", "depth")
        }
        style = {
            key: self.take_keyed("STYLE", key)
            for key in ("medium", "rendering", "palette")
        }
        visible_text: list[str] = []
        while (line := self.current()) is not None and line.startswith("VISIBLE_TEXT\t"):
            visible_text.append(self.take_scalar("VISIBLE_TEXT", allow_empty=False))
        uncertainties: list[str] = []
        while (line := self.current()) is not None and line.startswith("UNCERTAINTY\t"):
            uncertainties.append(self.take_scalar("UNCERTAINTY", allow_empty=False))

        if self.current() == VISION_END_MARKER:
            self.cursor += 1
        elif self.current() is None and self.allow_missing_end:
            self.warnings.append(f"missing {VISION_END_MARKER}")
        else:
            raise VisionProtocolError(
                f"expected {VISION_END_MARKER}, found {self.current()!r}"
            )
        if self.current() is not None:
            raise VisionProtocolError("content after Vision end marker is not allowed")

        observations = ObservationsArtifact(
            overview=overview,
            primary_subject=primary_subject,
            hint_status=hint_status,
            hint_reason=hint_reason,
            subject_features=tuple(features),
            subject_pose=subject_pose,
            scene_setting=scene_setting,
            scene_elements=tuple(scene_elements),
            lighting=lighting,
            time_weather=time_weather,
            shot_size=composition["shot_size"],
            viewpoint=composition["viewpoint"],
            subject_placement=composition["subject_placement"],
            depth=composition["depth"],
            style_medium=style["medium"],
            style_rendering=style["rendering"],
            style_palette=style["palette"],
            visible_text=tuple(visible_text),
            uncertainties=tuple(uncertainties),
        )
        observations.validate()
        return VisionParseResult(observations, tuple(self.warnings))


def parse_vision_observations(
    content: str, *, allow_missing_end: bool = True
) -> VisionParseResult:
    return _VisionParser(content, allow_missing_end).parse()

