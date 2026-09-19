"""ComfyUI wrapper for video-time H3 background Picture binding."""

from __future__ import annotations

from typing import Any

try:
    from ...core.h3_contract.background_reference import (
        bind_h3_background_reference,
    )
except ImportError:
    from core.h3_contract.background_reference import bind_h3_background_reference


class MVDirectorH3BackgroundReference:
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("plan_json", "background_image", "status")
    FUNCTION = "bind"
    CATEGORY = "MV Director/Video"
    DESCRIPTION = (
        "Bind one background image to an H3 Picture slot and add an "
        "environment-only reference contract to every compiled Shot."
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "plan_json": ("STRING", {"forceInput": True}),
                "background_image": ("IMAGE",),
                "picture_index": (
                    "INT",
                    {"default": 2, "min": 1, "max": 9},
                ),
            }
        }

    def bind(
        self,
        plan_json: str,
        background_image: Any,
        picture_index: int,
    ) -> tuple[str, Any, str]:
        bound_plan, shot_count = bind_h3_background_reference(
            plan_json,
            picture_index=picture_index,
        )
        return (
            bound_plan,
            background_image,
            f"picture=<Picture {picture_index}>; shots={shot_count}; role=environment",
        )


__all__ = ["MVDirectorH3BackgroundReference"]
