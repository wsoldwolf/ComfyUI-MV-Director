"""Frontend-populated connected combo with strict backend validation."""

from __future__ import annotations

from typing import Any

try:
    from ...core.utilities import parse_connected_candidates
except ImportError:
    from core.utilities import parse_connected_candidates


class MVDirectorConnectedCombo:
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("value",)
    FUNCTION = "select"
    CATEGORY = "MV Director/Utilities"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "selected_value": ("STRING", {"default": ""}),
                "enum_values_json": ("STRING", {"default": "[]", "multiline": True}),
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, selected_value: str, enum_values_json: str) -> bool | str:
        try:
            candidates = parse_connected_candidates(enum_values_json)
        except ValueError as exc:
            return str(exc)
        if selected_value not in candidates:
            return "selected_value is not present in connected candidates"
        return True

    def select(self, selected_value: str, enum_values_json: str) -> tuple[str]:
        validation = self.VALIDATE_INPUTS(selected_value, enum_values_json)
        if validation is not True:
            raise ValueError(validation)
        return (selected_value,)
