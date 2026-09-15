"""Shared validation and canonical JSON helpers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .errors import ArtifactValidationError


class DictArtifact(Protocol):
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary."""


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"{path} contains a non-finite float")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string key")
            _json_value(item, f"{path}.{key}")
        return
    raise TypeError(f"{path} contains non-JSON value {type(value).__name__}")


def canonical_json(value: Mapping[str, Any] | DictArtifact) -> str:
    payload = value.to_dict() if hasattr(value, "to_dict") else dict(value)
    _json_value(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def require_exact_keys(
    value: Mapping[str, Any],
    *,
    schema: str,
    path: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise ArtifactValidationError(schema, path, f"missing keys: {missing}")
    if unknown:
        raise ArtifactValidationError(schema, path, f"unknown keys: {unknown}")


def require_string(
    value: Any,
    *,
    schema: str,
    path: str,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ArtifactValidationError(schema, path, "must be a string")
    if not allow_empty and not value:
        raise ArtifactValidationError(schema, path, "must not be empty")
    return value


def require_integer(
    value: Any,
    *,
    schema: str,
    path: str,
    minimum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ArtifactValidationError(schema, path, "must be an integer")
    if minimum is not None and value < minimum:
        raise ArtifactValidationError(schema, path, f"must be >= {minimum}")
    return value


def require_sequence(
    value: Any,
    *,
    schema: str,
    path: str,
) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ArtifactValidationError(schema, path, "must be a JSON array")
    return value

