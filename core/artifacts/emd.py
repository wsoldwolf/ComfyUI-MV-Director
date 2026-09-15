"""Versioned EMD text artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .base import (
    canonical_json,
    normalize_newlines,
    require_exact_keys,
    require_string,
    sha256_text,
)
from .errors import ArtifactValidationError


EMD_SCHEMAS = frozenset(
    {"MVD_EMD_FRAGMENT_V1", "MVD_EMD_TEMPLATE_V1", "MVD_EMD_V1"}
)
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class EMDTextArtifact:
    schema: str
    text: str
    sha256: str

    @classmethod
    def create(cls, schema: str, text: str) -> "EMDTextArtifact":
        normalized = normalize_newlines(text)
        artifact = cls(schema=schema, text=normalized, sha256=sha256_text(normalized))
        artifact.validate()
        return artifact

    def validate(self) -> None:
        if self.schema not in EMD_SCHEMAS:
            raise ArtifactValidationError(self.schema, "schema", "unsupported EMD schema")
        require_string(self.text, schema=self.schema, path="text", allow_empty=False)
        if "\r" in self.text:
            raise ArtifactValidationError(
                self.schema, "text", "must contain LF newlines only"
            )
        if not _HASH_RE.fullmatch(self.sha256):
            raise ArtifactValidationError(
                self.schema, "sha256", "must be lowercase SHA-256 hex"
            )
        if sha256_text(self.text) != self.sha256:
            raise ArtifactValidationError(self.schema, "sha256", "hash mismatch")

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {"schema": self.schema, "text": self.text, "sha256": self.sha256}

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EMDTextArtifact":
        schema = value.get("schema")
        if not isinstance(schema, str):
            raise ArtifactValidationError("MVD_EMD_*", "schema", "must be a string")
        require_exact_keys(
            value,
            schema=schema,
            path="$",
            required={"schema", "text", "sha256"},
        )
        artifact = cls(schema=schema, text=value["text"], sha256=value["sha256"])
        artifact.validate()
        return artifact

