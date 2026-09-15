"""Decode a browser-embedded UTF-8 .txt file."""

from __future__ import annotations

from typing import Any

try:
    from ...core.utilities import decode_embedded_text, text_file_fingerprint
except ImportError:
    from core.utilities import decode_embedded_text, text_file_fingerprint


class MVDirectorLoadTextFile:
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "load_text"
    CATEGORY = "MV Director/Utilities"
    DESCRIPTION = "Return an embedded UTF-8 .txt file as a STRING."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "file_data_base64": ("STRING", {"default": "", "multiline": True}),
                "basename": ("STRING", {"default": "lyrics.txt"}),
                "browser_metadata_json": ("STRING", {"default": "{}", "multiline": True}),
            }
        }

    @classmethod
    def IS_CHANGED(
        cls, file_data_base64: str, basename: str, browser_metadata_json: str
    ) -> str:
        return text_file_fingerprint(file_data_base64, basename, browser_metadata_json)

    def load_text(
        self, file_data_base64: str, basename: str, browser_metadata_json: str
    ) -> tuple[str]:
        return (decode_embedded_text(file_data_base64, basename, browser_metadata_json),)
