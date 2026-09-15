"""Canonical success-only cache keys and a small atomic file store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from core.artifacts.base import canonical_json, sha256_text


def build_cache_key(
    *, task: str, algorithm_version: str, inputs: Mapping[str, Any]
) -> str:
    if not task or not algorithm_version:
        raise ValueError("task and algorithm_version are required")
    return sha256_text(
        canonical_json(
            {
                "task": task,
                "algorithm_version": algorithm_version,
                "inputs": dict(inputs),
            }
        )
    )


class SuccessCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(value, dict) or value.get("cache_key") != key:
            return None
        payload = value.get("payload")
        return payload if isinstance(payload, dict) else None

    def put_success(self, key: str, payload: Mapping[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = canonical_json({"cache_key": key, "payload": dict(payload)})
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{key}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as file:
                file.write(serialized)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("cache key must be lowercase SHA-256 hex")
        return self.root / key[:2] / f"{key}.json"

