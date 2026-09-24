"""ComfyUI node for slicing one contiguous Context Loop Scene range."""

from __future__ import annotations

from typing import Any

try:
    from ...core.audio import slice_audio_frame_window, split_context_loop_plan
    from ...core.h3_contract import DEFAULT_H3_TIMING_PROFILE
except ImportError:
    from core.audio import slice_audio_frame_window, split_context_loop_plan
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE


class MVDirectorSceneDebugSplitter:
    RETURN_TYPES = ("STRING", "AUDIO", "AUDIO")
    RETURN_NAMES = ("plan_json", "vocal_audio", "full_mix_audio")
    FUNCTION = "split_scenes"
    CATEGORY = "MV Director/Utilities"
    DESCRIPTION = (
        "Select a contiguous one-based Scene range from a Context Loop Plan "
        "and slice its vocal/full-mix PCM window for focused debugging."
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "plan_json": ("STRING", {"forceInput": True}),
                "vocal_audio": ("AUDIO",),
                "full_mix_audio": ("AUDIO",),
                "enable": ("BOOLEAN", {"default": True}),
                "scene_start": (
                    "INT",
                    {"default": 1, "min": 1, "max": 1_000_000, "step": 1},
                ),
                "scene_length": (
                    "INT",
                    {"default": 1, "min": 1, "max": 1_000_000, "step": 1},
                ),
            }
        }

    def split_scenes(
        self,
        plan_json: str,
        vocal_audio: Any,
        full_mix_audio: Any,
        enable: bool,
        scene_start: int,
        scene_length: int,
    ) -> dict[str, Any]:
        if not isinstance(enable, bool):
            raise ValueError("enable must be a boolean")
        if not enable:
            return {
                "ui": {"status": ["enabled=no; passthrough=yes"]},
                "result": (plan_json, vocal_audio, full_mix_audio),
            }

        profile = DEFAULT_H3_TIMING_PROFILE
        profile.validate()
        selection = split_context_loop_plan(
            plan_json,
            scene_start=scene_start,
            scene_length=scene_length,
        )
        sliced_vocal, vocal_padding = slice_audio_frame_window(
            vocal_audio,
            skipped_frames=selection.skipped_frames,
            selected_frames=selection.selected_frames,
            output_frames=selection.output_frames,
            fps=profile.fps,
            name="vocal_audio",
        )
        sliced_mix, mix_padding = slice_audio_frame_window(
            full_mix_audio,
            skipped_frames=selection.skipped_frames,
            selected_frames=selection.selected_frames,
            output_frames=selection.output_frames,
            fps=profile.fps,
            name="full_mix_audio",
        )
        end_scene = scene_start + scene_length - 1
        status = (
            f"enabled=yes; scenes={scene_start}..{end_scene}; "
            f"skip_frames={selection.skipped_frames}; "
            f"source_frames={selection.selected_frames}; "
            f"output_frames={selection.output_frames}; fps={profile.fps}; "
            f"vocal_end_padding_samples={vocal_padding}; "
            f"full_mix_end_padding_samples={mix_padding}"
        )
        return {
            "ui": {"status": [status]},
            "result": (
                selection.plan_json,
                sliced_vocal,
                sliced_mix,
            ),
        }
