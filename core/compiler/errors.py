"""Compiler-specific failures without repair or retry."""


class CompilerError(ValueError):
    """Raised when deterministic compilation cannot continue."""

