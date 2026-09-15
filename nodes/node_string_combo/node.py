"""Finite list to connected STRING utility."""

from __future__ import annotations

from typing import Any

try:
    from ...core.utilities import parse_string_combo
except ImportError:
    from core.utilities import parse_string_combo


class MVDirectorStringCombo:
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("value",)
    FUNCTION = "select"
    CATEGORY = "MV Director/Utilities"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "string_list": ("STRING", {"default": "context_loop|audio_reference|lyrics", "multiline": True}),
                "selected_value": ("STRING", {"default": "lyrics"}),
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, string_list: str, selected_value: str) -> bool | str:
        try:
            candidates = parse_string_combo(string_list)
        except ValueError as exc:
            return str(exc)
        if selected_value not in candidates:
            return "selected_value is not present in string_list"
        return True

    def select(self, string_list: str, selected_value: str) -> tuple[str]:
        validation = self.VALIDATE_INPUTS(string_list, selected_value)
        if validation is not True:
            raise ValueError(validation)
        return (selected_value,)
