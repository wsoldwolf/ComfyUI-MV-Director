"""MVD_DIRECTION_V3."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .base import (
    canonical_json,
    require_exact_keys,
    require_integer,
    require_sequence,
    require_string,
)
from .errors import ArtifactValidationError


SCHEMA = "MVD_DIRECTION_V3"
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_RECORD_KINDS = {"input", "output", "discard"}
_SOURCES = {"user", "vision", "profile", "generated"}
_DISPOSITIONS = {"supplied", "accepted", "discarded"}
_REASONS = {
    "direct_input",
    "valid_line_record",
    "empty",
    "exact_duplicate",
    "invalid_line_record",
    "profile_enforced",
    "profile_overridden",
    "passthrough_enforced",
}
_TARGET_RE = re.compile(
    r"(?:style_direction|environment_direction|time_lighting_direction|"
    r"motion_direction|camera_direction|other_direction|retention_lines)\[[0-9]+\]\Z"
)
_RETENTION_POLICIES = {"compiler_default", "profile", "passthrough"}


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    record_id: str
    record_kind: str
    source: str
    source_ref: str
    source_position: int
    target: str | None
    disposition: str
    reason: str
    sha256: str

    def validate(self) -> None:
        require_string(self.record_id, schema=SCHEMA, path="provenance.record_id")
        if self.record_kind not in _RECORD_KINDS:
            raise ArtifactValidationError(
                SCHEMA, "provenance.record_kind", "unsupported value"
            )
        if self.source not in _SOURCES:
            raise ArtifactValidationError(
                SCHEMA, "provenance.source", "unsupported value"
            )
        require_string(self.source_ref, schema=SCHEMA, path="provenance.source_ref")
        require_integer(
            self.source_position,
            schema=SCHEMA,
            path="provenance.source_position",
            minimum=0,
        )
        if self.target is not None and not _TARGET_RE.fullmatch(self.target):
            raise ArtifactValidationError(
                SCHEMA, "provenance.target", "invalid direction target"
            )
        if self.disposition not in _DISPOSITIONS:
            raise ArtifactValidationError(
                SCHEMA, "provenance.disposition", "unsupported value"
            )
        if self.reason not in _REASONS:
            raise ArtifactValidationError(
                SCHEMA, "provenance.reason", "unsupported value"
            )
        if not _HASH_RE.fullmatch(self.sha256):
            raise ArtifactValidationError(
                SCHEMA, "provenance.sha256", "must be lowercase SHA-256 hex"
            )
        expected = {
            "input": ("supplied", None),
            "output": ("accepted", "target"),
            "discard": ("discarded", None),
        }[self.record_kind]
        if self.disposition != expected[0]:
            raise ArtifactValidationError(
                SCHEMA,
                "provenance.disposition",
                f"must be {expected[0]} for {self.record_kind}",
            )
        if expected[1] == "target" and self.target is None:
            raise ArtifactValidationError(
                SCHEMA, "provenance.target", "output record requires a target"
            )
        if expected[1] is None and self.target is not None:
            raise ArtifactValidationError(
                SCHEMA, "provenance.target", "must be null for this record kind"
            )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "source": self.source,
            "source_ref": self.source_ref,
            "source_position": self.source_position,
            "target": self.target,
            "disposition": self.disposition,
            "reason": self.reason,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProvenanceRecord":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="provenance[]",
            required={
                "record_id",
                "record_kind",
                "source",
                "source_ref",
                "source_position",
                "target",
                "disposition",
                "reason",
                "sha256",
            },
        )
        record = cls(
            record_id=value["record_id"],
            record_kind=value["record_kind"],
            source=value["source"],
            source_ref=value["source_ref"],
            source_position=value["source_position"],
            target=value["target"],
            disposition=value["disposition"],
            reason=value["reason"],
            sha256=value["sha256"],
        )
        record.validate()
        return record


@dataclass(frozen=True, slots=True)
class DirectionArtifact:
    style_direction: tuple[str, ...] = ()
    environment_direction: tuple[str, ...] = ()
    time_lighting_direction: tuple[str, ...] = ()
    motion_direction: tuple[str, ...] = ()
    camera_direction: tuple[str, ...] = ()
    other_direction: tuple[str, ...] = ()
    style_profile_id: str = ""
    motion_profile_id: str = ""
    camera_profile_id: str = ""
    retention_policy: str = "compiler_default"
    retention_lines: tuple[str, ...] = ()
    provenance: tuple[ProvenanceRecord, ...] = ()
    schema: str = SCHEMA

    def validate(self) -> None:
        if self.schema != SCHEMA:
            raise ArtifactValidationError(SCHEMA, "schema", "schema mismatch")
        for field_name in (
            "style_direction",
            "environment_direction",
            "time_lighting_direction",
            "motion_direction",
            "camera_direction",
            "other_direction",
            "retention_lines",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise ArtifactValidationError(
                    SCHEMA, field_name, "must be a tuple internally"
                )
            for index, item in enumerate(values):
                require_string(item, schema=SCHEMA, path=f"{field_name}[{index}]")
        for field_name in (
            "style_profile_id",
            "motion_profile_id",
            "camera_profile_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise ArtifactValidationError(SCHEMA, field_name, "must be a string")
        if self.retention_policy not in _RETENTION_POLICIES:
            raise ArtifactValidationError(
                SCHEMA, "retention_policy", "unsupported value"
            )
        if self.retention_policy == "passthrough" and not self.retention_lines:
            raise ArtifactValidationError(
                SCHEMA,
                "retention_lines",
                "passthrough retention requires at least one line",
            )
        if self.retention_policy != "passthrough" and self.retention_lines:
            raise ArtifactValidationError(
                SCHEMA,
                "retention_lines",
                "lines are only valid for passthrough retention",
            )
        ids: set[str] = set()
        for index, record in enumerate(self.provenance):
            if not isinstance(record, ProvenanceRecord):
                raise ArtifactValidationError(
                    SCHEMA, f"provenance[{index}]", "must be ProvenanceRecord"
                )
            record.validate()
            if record.record_id in ids:
                raise ArtifactValidationError(
                    SCHEMA, f"provenance[{index}].record_id", "duplicate record ID"
                )
            ids.add(record.record_id)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": self.schema,
            "style_direction": list(self.style_direction),
            "environment_direction": list(self.environment_direction),
            "time_lighting_direction": list(self.time_lighting_direction),
            "motion_direction": list(self.motion_direction),
            "camera_direction": list(self.camera_direction),
            "other_direction": list(self.other_direction),
            "style_profile_id": self.style_profile_id,
            "motion_profile_id": self.motion_profile_id,
            "camera_profile_id": self.camera_profile_id,
            "retention_policy": self.retention_policy,
            "retention_lines": list(self.retention_lines),
            "provenance": [record.to_dict() for record in self.provenance],
        }

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DirectionArtifact":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="$",
            required={
                "schema",
                "style_direction",
                "environment_direction",
                "time_lighting_direction",
                "motion_direction",
                "camera_direction",
                "other_direction",
                "style_profile_id",
                "motion_profile_id",
                "camera_profile_id",
                "retention_policy",
                "retention_lines",
                "provenance",
            },
        )
        if value["schema"] != SCHEMA:
            raise ArtifactValidationError(SCHEMA, "schema", "schema mismatch")

        directions: dict[str, tuple[str, ...]] = {}
        for field_name in (
            "style_direction",
            "environment_direction",
            "time_lighting_direction",
            "motion_direction",
            "camera_direction",
            "other_direction",
            "retention_lines",
        ):
            items = require_sequence(
                value[field_name], schema=SCHEMA, path=field_name
            )
            directions[field_name] = tuple(items)
        provenance_values = require_sequence(
            value["provenance"], schema=SCHEMA, path="provenance"
        )
        artifact = cls(
            style_direction=directions["style_direction"],
            environment_direction=directions["environment_direction"],
            time_lighting_direction=directions["time_lighting_direction"],
            motion_direction=directions["motion_direction"],
            camera_direction=directions["camera_direction"],
            other_direction=directions["other_direction"],
            style_profile_id=value["style_profile_id"],
            motion_profile_id=value["motion_profile_id"],
            camera_profile_id=value["camera_profile_id"],
            retention_policy=value["retention_policy"],
            retention_lines=directions["retention_lines"],
            provenance=tuple(
                ProvenanceRecord.from_dict(item) for item in provenance_values
            ),
        )
        artifact.validate()
        return artifact
