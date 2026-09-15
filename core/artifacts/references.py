"""Reference binding and compiler requirement artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .base import (
    canonical_json,
    require_exact_keys,
    require_sequence,
    require_string,
)
from .errors import ArtifactValidationError


BINDINGS_SCHEMA = "MVD_REFERENCE_BINDINGS_V1"
REQUIRED_SCHEMA = "MVD_REQUIRED_REFERENCES_V1"
_CONCEPT_RE = re.compile(r"(?:人物|場所|物品)(?:[1-9]|1[0-6])\Z")
_SUBJECT_RE = re.compile(r"<Subject [1-4]>\Z")
_PICTURE_RE = re.compile(r"<Picture ([1-9])>\Z")
_AUDIO_RE = re.compile(r"<Audio ([1-3])>\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


def _validate_concept(value: str, schema: str, path: str) -> None:
    if not isinstance(value, str) or not _CONCEPT_RE.fullmatch(value):
        raise ArtifactValidationError(schema, path, "invalid concept ID")


@dataclass(frozen=True, slots=True)
class ReferenceBinding:
    concept_id: str
    subject_ref: str
    picture_ref: str
    target_node_id: str
    target_class_type: str
    target_input: str
    image_sha256: str
    binding_sha256: str

    def validate(self) -> None:
        _validate_concept(self.concept_id, BINDINGS_SCHEMA, "concept_id")
        if not isinstance(self.subject_ref, str) or not _SUBJECT_RE.fullmatch(
            self.subject_ref
        ):
            raise ArtifactValidationError(
                BINDINGS_SCHEMA, "subject_ref", "invalid Subject reference"
            )
        match = _PICTURE_RE.fullmatch(self.picture_ref)
        if match is None:
            raise ArtifactValidationError(
                BINDINGS_SCHEMA, "picture_ref", "invalid Picture reference"
            )
        require_string(
            self.target_node_id, schema=BINDINGS_SCHEMA, path="target_node_id"
        )
        require_string(
            self.target_class_type, schema=BINDINGS_SCHEMA, path="target_class_type"
        )
        expected = f"ref_images.ref_image_{int(match.group(1)) - 1}"
        if self.target_input not in {expected, expected.split(".")[-1]}:
            raise ArtifactValidationError(
                BINDINGS_SCHEMA, "target_input", f"must correspond to {self.picture_ref}"
            )
        for field_name in ("image_sha256", "binding_sha256"):
            if not _HASH_RE.fullmatch(getattr(self, field_name)):
                raise ArtifactValidationError(
                    BINDINGS_SCHEMA, field_name, "must be lowercase SHA-256 hex"
                )

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "concept_id": self.concept_id,
            "subject_ref": self.subject_ref,
            "picture_ref": self.picture_ref,
            "target_node_id": self.target_node_id,
            "target_class_type": self.target_class_type,
            "target_input": self.target_input,
            "image_sha256": self.image_sha256,
            "binding_sha256": self.binding_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReferenceBinding":
        require_exact_keys(
            value,
            schema=BINDINGS_SCHEMA,
            path="bindings[]",
            required={
                "concept_id",
                "subject_ref",
                "picture_ref",
                "target_node_id",
                "target_class_type",
                "target_input",
                "image_sha256",
                "binding_sha256",
            },
        )
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class ReferenceBindingsArtifact:
    bindings: tuple[ReferenceBinding, ...] = ()
    schema: str = BINDINGS_SCHEMA

    def validate(self) -> None:
        if self.schema != BINDINGS_SCHEMA:
            raise ArtifactValidationError(BINDINGS_SCHEMA, "schema", "schema mismatch")
        for index, binding in enumerate(self.bindings):
            if not isinstance(binding, ReferenceBinding):
                raise ArtifactValidationError(
                    BINDINGS_SCHEMA, f"bindings[{index}]", "invalid binding"
                )
            binding.validate()

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": self.schema,
            "bindings": [binding.to_dict() for binding in self.bindings],
        }

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReferenceBindingsArtifact":
        require_exact_keys(
            value,
            schema=BINDINGS_SCHEMA,
            path="$",
            required={"schema", "bindings"},
        )
        if value["schema"] != BINDINGS_SCHEMA:
            raise ArtifactValidationError(BINDINGS_SCHEMA, "schema", "schema mismatch")
        bindings = require_sequence(
            value["bindings"], schema=BINDINGS_SCHEMA, path="bindings"
        )
        artifact = cls(tuple(ReferenceBinding.from_dict(item) for item in bindings))
        artifact.validate()
        return artifact


@dataclass(frozen=True, slots=True)
class RequiredReference:
    concept_id: str
    h3_ref: str
    required_input: str
    purpose: str
    subject_ref: str | None = None

    def validate(self) -> None:
        _validate_concept(self.concept_id, REQUIRED_SCHEMA, "concept_id")
        if self.purpose == "visual_identity":
            match = _PICTURE_RE.fullmatch(self.h3_ref)
            if match is None:
                raise ArtifactValidationError(
                    REQUIRED_SCHEMA, "h3_ref", "visual identity requires Picture"
                )
            if self.subject_ref is None or not _SUBJECT_RE.fullmatch(self.subject_ref):
                raise ArtifactValidationError(
                    REQUIRED_SCHEMA,
                    "subject_ref",
                    "visual identity requires Subject reference",
                )
            expected = f"ref_images.ref_image_{int(match.group(1)) - 1}"
        elif self.purpose == "lip_sync_audio_reference":
            match = _AUDIO_RE.fullmatch(self.h3_ref)
            if match is None:
                raise ArtifactValidationError(
                    REQUIRED_SCHEMA, "h3_ref", "audio purpose requires Audio reference"
                )
            if self.subject_ref is not None and not _SUBJECT_RE.fullmatch(
                self.subject_ref
            ):
                raise ArtifactValidationError(
                    REQUIRED_SCHEMA, "subject_ref", "invalid Subject reference"
                )
            expected = f"ref_audios.ref_audio_{int(match.group(1)) - 1}"
        else:
            raise ArtifactValidationError(
                REQUIRED_SCHEMA, "purpose", "unsupported purpose"
            )
        if self.required_input != expected:
            raise ArtifactValidationError(
                REQUIRED_SCHEMA, "required_input", f"must be {expected}"
            )

    def to_dict(self) -> dict[str, str]:
        self.validate()
        result = {
            "concept_id": self.concept_id,
            "h3_ref": self.h3_ref,
            "required_input": self.required_input,
            "purpose": self.purpose,
        }
        if self.subject_ref is not None:
            result["subject_ref"] = self.subject_ref
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequiredReference":
        require_exact_keys(
            value,
            schema=REQUIRED_SCHEMA,
            path="references[]",
            required={"concept_id", "h3_ref", "required_input", "purpose"},
            optional={"subject_ref"},
        )
        result = cls(
            concept_id=value["concept_id"],
            h3_ref=value["h3_ref"],
            required_input=value["required_input"],
            purpose=value["purpose"],
            subject_ref=value.get("subject_ref"),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class RequiredReferencesArtifact:
    references: tuple[RequiredReference, ...] = ()
    schema: str = REQUIRED_SCHEMA

    def validate(self) -> None:
        if self.schema != REQUIRED_SCHEMA:
            raise ArtifactValidationError(REQUIRED_SCHEMA, "schema", "schema mismatch")
        seen: set[tuple[str, str, str]] = set()
        for index, reference in enumerate(self.references):
            if not isinstance(reference, RequiredReference):
                raise ArtifactValidationError(
                    REQUIRED_SCHEMA, f"references[{index}]", "invalid reference"
                )
            reference.validate()
            key = (reference.concept_id, reference.h3_ref, reference.purpose)
            if key in seen:
                raise ArtifactValidationError(
                    REQUIRED_SCHEMA, f"references[{index}]", "duplicate reference"
                )
            seen.add(key)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": self.schema,
            "references": [reference.to_dict() for reference in self.references],
        }

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequiredReferencesArtifact":
        require_exact_keys(
            value,
            schema=REQUIRED_SCHEMA,
            path="$",
            required={"schema", "references"},
        )
        if value["schema"] != REQUIRED_SCHEMA:
            raise ArtifactValidationError(REQUIRED_SCHEMA, "schema", "schema mismatch")
        references = require_sequence(
            value["references"], schema=REQUIRED_SCHEMA, path="references"
        )
        artifact = cls(
            tuple(RequiredReference.from_dict(item) for item in references)
        )
        artifact.validate()
        return artifact

