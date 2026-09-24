"""Deterministic Context Loop Scene slicing for focused video debugging."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SceneDebugPlanSlice:
    plan_json: str
    scene_start: int
    scene_length: int
    skipped_frames: int
    selected_frames: int
    output_frames: int


def _positive_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    if value < 1:
        raise ValueError(f"{path} must be positive")
    return value


def _scene_delivered_frames(scene: Any, index: int) -> int:
    if not isinstance(scene, Mapping):
        raise ValueError(f"plan_json.shots[{index}] must be an object")
    length = _positive_integer(scene.get("length"), f"plan_json.shots[{index}].length")
    context = scene.get("context_length", 0)
    if isinstance(context, bool) or not isinstance(context, int):
        raise ValueError(
            f"plan_json.shots[{index}].context_length must be an integer"
        )
    if context < 0:
        raise ValueError(
            f"plan_json.shots[{index}].context_length must be non-negative"
        )
    delivered = length - context
    if delivered < 1:
        raise ValueError(
            f"plan_json.shots[{index}] must deliver at least one frame"
        )
    return delivered


def split_context_loop_plan(
    plan_json: str,
    *,
    scene_start: int,
    scene_length: int,
) -> SceneDebugPlanSlice:
    """Keep a one-based contiguous Scene range and return its PCM frame window."""

    if not isinstance(plan_json, str):
        raise ValueError("plan_json must be a string")
    _positive_integer(scene_start, "scene_start")
    _positive_integer(scene_length, "scene_length")
    try:
        plan = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan_json is not valid JSON: {exc.msg}") from exc
    if not isinstance(plan, dict):
        raise ValueError("plan_json root must be an object")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("plan_json.shots must be a non-empty array")

    delivered_frames = tuple(
        _scene_delivered_frames(scene, index)
        for index, scene in enumerate(shots)
    )
    start_index = scene_start - 1
    end_index = start_index + scene_length
    if start_index >= len(shots):
        raise ValueError(
            f"scene_start {scene_start} exceeds Plan Scene count {len(shots)}"
        )
    if end_index > len(shots):
        raise ValueError(
            f"scene range {scene_start}..{end_index} exceeds Plan Scene count "
            f"{len(shots)}"
        )

    sliced_plan = dict(plan)
    sliced_plan["shots"] = shots[start_index:end_index]
    output_json = json.dumps(
        sliced_plan,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    return SceneDebugPlanSlice(
        plan_json=output_json,
        scene_start=scene_start,
        scene_length=scene_length,
        skipped_frames=sum(delivered_frames[:start_index]),
        selected_frames=sum(delivered_frames[start_index:end_index]),
        # The first selected Scene has no preceding local Context Loop Scene.
        # Its context frames therefore remain in the H3 render, while the
        # original source timeline advances by delivered frames only.
        output_frames=sum(delivered_frames[start_index:end_index])
        + (shots[start_index]["length"] - delivered_frames[start_index]),
    )


def slice_audio_frame_window(
    audio: Mapping[str, Any],
    *,
    skipped_frames: int,
    selected_frames: int,
    output_frames: int | None = None,
    fps: int,
    name: str,
) -> tuple[dict[str, Any], int]:
    """Slice delivered source audio and silence-pad to the H3 render duration."""

    if not isinstance(audio, Mapping):
        raise ValueError(f"{name} must be a ComfyUI AUDIO object")
    waveform = audio.get("waveform")
    sample_rate = audio.get("sample_rate")
    shape = getattr(waveform, "shape", None)
    if shape is None or len(shape) < 1:
        raise ValueError(f"{name}.waveform must have a sample dimension")
    if not hasattr(waveform, "new_zeros"):
        raise ValueError(f"{name}.waveform does not support PCM slicing")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
        raise ValueError(f"{name}.sample_rate must be an integer")
    if sample_rate < 1:
        raise ValueError(f"{name}.sample_rate must be positive")
    for field, value in (
        ("skipped_frames", skipped_frames),
        ("selected_frames", selected_frames),
        ("fps", fps),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
    if skipped_frames < 0 or selected_frames < 1 or fps < 1:
        raise ValueError("frame offsets must be valid and fps must be positive")
    if output_frames is None:
        output_frames = selected_frames
    if isinstance(output_frames, bool) or not isinstance(output_frames, int):
        raise ValueError("output_frames must be an integer")
    if output_frames < selected_frames:
        raise ValueError("output_frames cannot be shorter than selected_frames")

    source_samples = int(shape[-1])
    start_sample = round(Fraction(skipped_frames * sample_rate, fps))
    end_sample = round(
        Fraction((skipped_frames + selected_frames) * sample_rate, fps)
    )
    target_samples = round(
        Fraction((skipped_frames + output_frames) * sample_rate, fps)
    ) - start_sample
    if target_samples < 1:
        raise ValueError(f"{name} frame window resolves to zero samples")

    source_start = min(max(start_sample, 0), source_samples)
    source_end = min(max(end_sample, source_start), source_samples)
    source_window = waveform[..., source_start:source_end]
    copied_samples = int(source_window.shape[-1])
    output_waveform = waveform.new_zeros(
        (*tuple(waveform.shape[:-1]), target_samples)
    )
    if copied_samples:
        output_waveform[..., :copied_samples] = source_window
    result = dict(audio)
    result["waveform"] = output_waveform
    return result, target_samples - copied_samples

