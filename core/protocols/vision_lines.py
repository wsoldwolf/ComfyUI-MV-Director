"""Bounded parser for MVD_VISION_OBSERVATION_LINES_V2.

The wire format has one canonical record order, but small Vision models
occasionally permute otherwise valid named records or restart a response. The
parser canonicalizes only known record names before applying strict field and
artifact validation. It never guesses an unknown line's meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..artifacts.base import normalize_newlines
from ..artifacts.observations import (
    FEATURE_CATEGORIES,
    HINT_STATUSES,
    VISIBILITIES,
    ObservationsArtifact,
    SubjectFeature,
)

from .vision_contract import VISION_END_MARKER, VISION_PROTOCOL_ID


_CANONICAL_RECORD_ORDER = (
    "OVERVIEW",
    "PRIMARY_SUBJECT",
    "HINT_STATUS",
    "HINT_REASON",
    "SUBJECT_FEATURE",
    "SUBJECT_POSE",
    "SCENE_SETTING",
    "SCENE_ELEMENT",
    "LIGHTING",
    "TIME_WEATHER",
    "SHOT_SIZE",
    "VIEWPOINT",
    "SUBJECT_PLACEMENT",
    "DEPTH",
    "STYLE_MEDIUM",
    "STYLE_RENDERING",
    "STYLE_PALETTE",
    "VISIBLE_TEXT",
    "UNCERTAINTY",
)
_REPEATED_RECORDS = {
    "SUBJECT_FEATURE",
    "SCENE_ELEMENT",
    "VISIBLE_TEXT",
    "UNCERTAINTY",
}
_EMPTY_ALLOWED_SCALAR_RECORDS = {
    "PRIMARY_SUBJECT",
    "HINT_REASON",
    "SUBJECT_POSE",
    "SCENE_SETTING",
    "LIGHTING",
    "TIME_WEATHER",
    "SHOT_SIZE",
    "VIEWPOINT",
    "SUBJECT_PLACEMENT",
    "DEPTH",
    "STYLE_MEDIUM",
    "STYLE_RENDERING",
    "STYLE_PALETTE",
}


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


def _record_name(line: str) -> str:
    raw = line.split("\t", 1)[0].strip()
    return raw.replace(" ", "_").replace("-", "_").upper()


def _is_redundant_protocol_id_line(line: str) -> bool:
    """Return true only for a protocol_id label carrying no observation data."""

    if _record_name(line) != "PROTOCOL_ID":
        return False
    values = [part.strip() for part in line.split("\t")[1:] if part.strip()]
    return not values or all(value == VISION_PROTOCOL_ID for value in values)


class _VisionParser:
    def __init__(
        self,
        content: str,
        allow_missing_end: bool,
        analysis_profile: str,
    ) -> None:
        if not isinstance(content, str):
            raise VisionProtocolError("Vision response must be a string")
        if "\x00" in content:
            raise VisionProtocolError("NUL is not allowed")
        normalized = normalize_newlines(content)
        self.warnings: list[str] = []
        think_match = re.match(
            r"\A\s*<think>.*?</think>\s*",
            normalized,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if think_match is not None:
            normalized = normalized[think_match.end():]
            self.warnings.append("removed leading closed Vision think block")
        self.lines = [line for line in normalized.split("\n") if line != ""]
        if any(line.startswith("```") for line in self.lines):
            raise VisionProtocolError("Markdown code fences are not allowed")
        if any("<Picture " in line or "<Subject " in line for line in self.lines):
            raise VisionProtocolError("H3 reference tags are not allowed")
        self.cursor = 0
        self.allow_missing_end = allow_missing_end
        if analysis_profile not in {"general", "subject_only", "scene_only"}:
            raise VisionProtocolError(
                f"unknown Vision analysis profile {analysis_profile!r}"
            )
        self.analysis_profile = analysis_profile

    def current(self) -> str | None:
        return self.lines[self.cursor] if self.cursor < len(self.lines) else None

    def take_scalar(self, record_type: str, *, allow_empty: bool = True) -> str:
        line = self.current()
        if line is None:
            raise VisionProtocolError(f"expected {record_type}")
        if record_type == "OVERVIEW" and line.startswith(("Overview:", "OVERVIEW:")):
            value = line.split(":", 1)[1].strip()
            if not value and not allow_empty:
                raise VisionProtocolError("OVERVIEW must not be empty")
            self.warnings.append(
                f"normalized colon-form OVERVIEW at line {self.cursor + 1}"
            )
            self.cursor += 1
            return value
        parts = line.split("\t")
        if not parts or _record_name(line) != record_type:
            raise VisionProtocolError(
                f"line {self.cursor + 1}: expected {record_type}, found {parts[0]!r}"
            )
        if parts[0] != record_type:
            self.warnings.append(
                f"normalized record name {parts[0]!r} to {record_type} at line "
                f"{self.cursor + 1}"
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

    def take_optional_repeated(self, record_type: str) -> list[str]:
        values: list[str] = []
        while (
            (line := self.current()) is not None
            and _record_name(line) == record_type
        ):
            line_number = self.cursor + 1
            value = self.take_scalar(record_type, allow_empty=True)
            if value:
                values.append(value)
            else:
                self.warnings.append(
                    f"ignored empty optional {record_type} at line {line_number}"
                )
        return values

    @staticmethod
    def _record_value_for_duplicate_check(line: str, record_type: str) -> str:
        if record_type == "OVERVIEW" and line.startswith(
            ("Overview:", "OVERVIEW:")
        ):
            return line.split(":", 1)[1].strip()
        parts = line.split("\t")
        return "\t".join(part.strip() for part in parts[1:]).strip()

    def _canonicalize_known_records(self) -> None:
        """Put known named records in wire order without inventing content."""

        body = self.lines[self.cursor :]
        by_name: dict[str, list[str]] = {
            name: [] for name in _CANONICAL_RECORD_ORDER
        }
        observed_names: list[str] = []
        saw_end = False
        for offset, line in enumerate(body, start=self.cursor + 1):
            if line == VISION_END_MARKER:
                saw_end = True
                continue
            if line == VISION_PROTOCOL_ID or _is_redundant_protocol_id_line(line):
                self.warnings.append(
                    f"ignored repeated Vision protocol marker at line {offset}"
                )
                continue
            if line.startswith(("Overview:", "OVERVIEW:")):
                name = "OVERVIEW"
                line = f"OVERVIEW\t{line.split(':', 1)[1].strip()}"
                self.warnings.append(
                    f"normalized colon-form OVERVIEW at line {offset}"
                )
            else:
                name = _record_name(line)
            if name not in by_name:
                raw_name = line.split("\t", 1)[0]
                raise VisionProtocolError(
                    f"line {offset}: unknown Vision record {raw_name!r}"
                )
            observed_names.append(name)
            records = by_name[name]
            value = self._record_value_for_duplicate_check(line, name)
            if name in _REPEATED_RECORDS:
                if any(
                    self._record_value_for_duplicate_check(existing, name) == value
                    for existing in records
                ):
                    self.warnings.append(
                        f"ignored duplicate {name} record at line {offset}"
                    )
                    continue
                records.append(line)
                continue
            if not records:
                records.append(line)
                continue
            previous = self._record_value_for_duplicate_check(records[0], name)
            if not previous and value:
                records[0] = line
                self.warnings.append(
                    f"used non-empty duplicate {name} value at line {offset}"
                )
            else:
                qualifier = "conflicting " if previous and value != previous else ""
                self.warnings.append(
                    f"ignored {qualifier}duplicate {name} record at line {offset}"
                )

        for name in _EMPTY_ALLOWED_SCALAR_RECORDS:
            if not by_name[name]:
                by_name[name].append(f"{name}\t")
                self.warnings.append(
                    f"restored omitted empty {name} record"
                )

        canonical_names = [
            name
            for name in _CANONICAL_RECORD_ORDER
            for _line in by_name[name]
        ]
        if observed_names != canonical_names:
            self.warnings.append("normalized known Vision records to canonical order")
        canonical_body = [
            line
            for name in _CANONICAL_RECORD_ORDER
            for line in by_name[name]
        ]
        if saw_end:
            canonical_body.append(VISION_END_MARKER)
        self.lines = self.lines[: self.cursor] + canonical_body

    def parse(self) -> VisionParseResult:
        if self.lines:
            first_name = _record_name(self.lines[0])
            first_is_colon_overview = self.lines[0].startswith(
                ("Overview:", "OVERVIEW:")
            )
            if first_name in {"OVERVIEW", "PRIMARY_SUBJECT"} or first_is_colon_overview:
                self.lines.insert(0, VISION_PROTOCOL_ID)
                self.warnings.append(f"normalized missing {VISION_PROTOCOL_ID}")
        if not self.lines or self.lines[0] != VISION_PROTOCOL_ID:
            first = self.lines[0][:120] if self.lines else "<empty>"
            raise VisionProtocolError(
                f"Vision response must start with {VISION_PROTOCOL_ID}; "
                f"found {first!r}"
            )
        self.cursor = 1
        if (
            (line := self.current()) is not None
            and _is_redundant_protocol_id_line(line)
        ):
            self.cursor += 1
            if line.strip().casefold() == "protocol_id":
                self.warnings.append(
                    "ignored redundant bare protocol_id after Vision protocol ID"
                )
            else:
                self.warnings.append(
                    "ignored redundant protocol_id metadata after Vision protocol ID"
                )
        if (
            (line := self.current()) is not None
            and "\t" not in line
            and not line.startswith(("Overview:", "OVERVIEW:"))
            and _record_name(line)
            not in {"OVERVIEW", "PRIMARY_SUBJECT", "HINT_STATUS"}
            and self.cursor + 1 < len(self.lines)
        ):
            next_name = _record_name(self.lines[self.cursor + 1])
            if next_name == "PRIMARY_SUBJECT":
                self.lines[self.cursor] = f"OVERVIEW\t{line.strip()}"
                self.warnings.append(
                    f"labelled bare OVERVIEW value at line {self.cursor + 1}"
                )
            elif next_name == "HINT_STATUS":
                self.lines[self.cursor] = f"PRIMARY_SUBJECT\t{line.strip()}"
                self.warnings.append(
                    f"labelled bare PRIMARY_SUBJECT value at line {self.cursor + 1}"
                )
        self._canonicalize_known_records()
        if (
            (line := self.current()) is not None
            and _record_name(line) == "PRIMARY_SUBJECT"
        ):
            parts = line.split("\t")
            subject = _value(
                parts, 1, "PRIMARY_SUBJECT", allow_empty=True
            ) if len(parts) > 1 else ""
            overview = f"{subject}の参照画像。" if subject else "参照画像。"
            self.warnings.append(
                f"normalized missing OVERVIEW before line {self.cursor + 1}"
            )
        else:
            overview = self.take_scalar("OVERVIEW", allow_empty=False)
        primary_subject = self.take_scalar("PRIMARY_SUBJECT")

        hint_status = self.take_scalar("HINT_STATUS", allow_empty=False)
        if hint_status not in HINT_STATUSES:
            raise VisionProtocolError(
                f"HINT_STATUS uses unknown status {hint_status!r}"
            )
        hint_reason = self.take_scalar("HINT_REASON")
        if hint_status == "not_used" and hint_reason:
            raise VisionProtocolError("not_used HINT_STATUS must have no reason")
        if hint_status != "not_used" and not hint_reason:
            self.warnings.append(
                f"accepted empty HINT_REASON for {hint_status} HINT_STATUS"
            )

        features: list[SubjectFeature] = []
        while (line := self.current()) is not None and _record_name(line) == "SUBJECT_FEATURE":
            parts = line.split("\t")
            if len(parts) == 2:
                lone_value = parts[1].strip()
                if not lone_value or lone_value.casefold() in FEATURE_CATEGORIES:
                    raise VisionProtocolError("SUBJECT_FEATURE has too few fields")
                features.append(
                    SubjectFeature("distinctive_feature", lone_value, "partial")
                )
                self.warnings.append(
                    "defaulted missing SUBJECT_FEATURE category to "
                    "distinctive_feature and visibility to partial at line "
                    f"{self.cursor + 1}"
                )
                self.cursor += 1
                continue
            if len(parts) < 3:
                raise VisionProtocolError("SUBJECT_FEATURE has too few fields")
            raw_category = parts[1].strip()
            category = raw_category.casefold()
            if category not in FEATURE_CATEGORIES:
                raise VisionProtocolError(
                    f"SUBJECT_FEATURE uses unknown category {category!r}"
                )
            if category != raw_category:
                self.warnings.append(
                    f"normalized SUBJECT_FEATURE category {raw_category!r} to "
                    f"{category!r} at line {self.cursor + 1}"
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
        scene_elements = self.take_optional_repeated("SCENE_ELEMENT")
        lighting = self.take_scalar("LIGHTING")
        time_weather = self.take_scalar("TIME_WEATHER")

        shot_size = self.take_scalar("SHOT_SIZE")
        viewpoint = self.take_scalar("VIEWPOINT")
        subject_placement = self.take_scalar("SUBJECT_PLACEMENT")
        depth = self.take_scalar("DEPTH")
        style_medium = self.take_scalar("STYLE_MEDIUM")
        style_rendering = self.take_scalar("STYLE_RENDERING")
        style_palette = self.take_scalar("STYLE_PALETTE")
        visible_text = self.take_optional_repeated("VISIBLE_TEXT")
        uncertainties = self.take_optional_repeated("UNCERTAINTY")

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
            shot_size=shot_size,
            viewpoint=viewpoint,
            subject_placement=subject_placement,
            depth=depth,
            style_medium=style_medium,
            style_rendering=style_rendering,
            style_palette=style_palette,
            visible_text=tuple(visible_text),
            uncertainties=tuple(uncertainties),
        )
        observations.validate()
        return VisionParseResult(observations, tuple(self.warnings))


def parse_vision_observations(
    content: str,
    *,
    allow_missing_end: bool = True,
    analysis_profile: str = "general",
) -> VisionParseResult:
    return _VisionParser(content, allow_missing_end, analysis_profile).parse()
