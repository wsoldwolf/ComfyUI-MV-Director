"""ComfyUI wrapper for paired PCM silence padding."""

from __future__ import annotations

from typing import Any

try:
    from ...core.audio import SceneAudioWindow, align_audio_to_plan_scenes, pad_audio_pair
    from ...core.artifacts import TimelineArtifact
    from ...core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
except ImportError:
    from core.audio import SceneAudioWindow, align_audio_to_plan_scenes, pad_audio_pair
    from core.artifacts import TimelineArtifact
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile


class MVDirectorAudioPadPair:
    RETURN_TYPES = ("AUDIO", "AUDIO", "STRING", "AUDIO")
    RETURN_NAMES = (
        "padded_audio_a",
        "padded_audio_b",
        "status",
        "reference_audio_b",
    )
    FUNCTION = "pad_pair"
    CATEGORY = "MV Director/Audio"
    DESCRIPTION = "End-pad full mix and vocal stem with PCM silence without mixing."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "audio_a": ("AUDIO",),
                "audio_b": ("AUDIO",),
                "extra_padding_ms": ("INT", {"default": 0, "min": 0, "max": 600000}),
                "target_h3_frames": ("INT", {"default": 0, "min": 0, "max": 1000000}),
                "pad_position": (["end"], {"default": "end"}),
                "reference_alignment": (
                    ["off", "source_scenes_to_plan"],
                    {"default": "off"},
                ),
            },
            "optional": {
                "timeline": ("MV_DIRECTOR_TIMELINE",),
                "h3_timing_profile": ("MV_DIRECTOR_H3_TIMING_PROFILE",),
            },
        }

    def pad_pair(
        self,
        audio_a: Any,
        audio_b: Any,
        extra_padding_ms: int,
        target_h3_frames: int,
        pad_position: str,
        reference_alignment: str,
        timeline: TimelineArtifact | None = None,
        h3_timing_profile: H3TimingProfile | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
        if pad_position != "end":
            raise ValueError("only end padding is supported")
        if reference_alignment not in {"off", "source_scenes_to_plan"}:
            raise ValueError("unknown reference_alignment mode")
        profile = h3_timing_profile or DEFAULT_H3_TIMING_PROFILE
        profile.validate()
        plan_duration_ms = 0
        timeline_h3_frames = 0
        if timeline is not None:
            timeline.validate()
            plan_duration_ms = timeline.plan_duration_ms
            # ``plan_duration_ms`` is a human-readable integer serialization of
            # the frame timeline.  It can be fractionally shorter than the exact
            # frame duration (for example, 719 / 24 s serializes as 29,958 ms).
            # Keep the frame count authoritative so H3 preflight never loses the
            # final frame through millisecond rounding.
            timeline_h3_frames = sum(
                scene.delivered_frames for scene in timeline.scenes
            )
        effective_target_h3_frames = max(
            target_h3_frames,
            timeline_h3_frames,
        )
        padded_a, padded_b, targets = pad_audio_pair(
            audio_a,
            audio_b,
            plan_duration_ms=plan_duration_ms,
            target_h3_frames=effective_target_h3_frames,
            fps=profile.fps,
            extra_padding_ms=extra_padding_ms,
        )
        reference_audio_b = padded_b
        alignment_status = "reference_alignment=off"
        if reference_alignment == "source_scenes_to_plan":
            if timeline is None:
                raise ValueError(
                    "source_scenes_to_plan requires MVD_TIMELINE_V1"
                )
            windows = tuple(
                SceneAudioWindow(
                    source_start_ms=scene.source_start_ms,
                    source_end_ms=scene.source_end_ms,
                    delivered_frames=scene.delivered_frames,
                )
                for scene in timeline.scenes
            )
            reference_audio_b, gaps = align_audio_to_plan_scenes(
                audio_b,
                windows,
                target_samples=targets[1],
                fps=profile.fps,
            )
            alignment_status = (
                "reference_alignment=source_scenes_to_plan; "
                f"scene_gap_samples={sum(gaps)}"
            )
        status = (
            f"pad=end; target_samples_a={targets[0]}; target_samples_b={targets[1]}; "
            f"plan_ms={plan_duration_ms}; timeline_frames={timeline_h3_frames}; "
            f"requested_target_frames={target_h3_frames}; "
            f"target_frames={effective_target_h3_frames}; "
            f"{alignment_status}"
        )
        return padded_a, padded_b, status, reference_audio_b
