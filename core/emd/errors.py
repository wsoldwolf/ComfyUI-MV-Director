"""EMD syntax errors."""

from __future__ import annotations


class EMDParseError(ValueError):
    def __init__(self, line_number: int, message: str) -> None:
        self.line_number = line_number
        self.message = message
        location = f"line {line_number}" if line_number else "document"
        super().__init__(f"{location}: {message}")

