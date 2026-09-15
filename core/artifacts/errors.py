"""Artifact validation errors."""

from __future__ import annotations


class ArtifactValidationError(ValueError):
    """A versioned artifact failed structural validation."""

    def __init__(self, schema: str, path: str, message: str) -> None:
        self.schema = schema
        self.path = path
        self.message = message
        super().__init__(f"{schema} at {path}: {message}")

