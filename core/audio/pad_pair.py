"""Pair-wise end padding without resampling, mixing, or truncation."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AudioShape:
    sample_rate: int
    samples: int

    def validate(self) -> None:
        if isinstance(self.sample_rate, bool) or not isinstance(self.sample_rate, int):
            raise ValueError("sample_rate must be an integer")
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise ValueError("samples must be an integer")
        if self.sample_rate < 1:
            raise ValueError("sample_rate must be positive")
        if self.samples < 1:
            raise ValueError("audio waveform must contain samples")


@dataclass(frozen=True, slots=True)
class SceneAudioWindow:
    source_start_ms: int
    source_end_ms: int
    delivered_frames: int

    def validate(self) -> None:
        for name in ("source_start_ms", "source_end_ms", "delivered_frames"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.source_start_ms < 0:
            raise ValueError("source_start_ms must be non-negative")
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("source_end_ms must be greater than source_start_ms")
        if self.delivered_frames < 1:
            raise ValueError("delivered_frames must be positive")


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _round_fraction(value: Fraction) -> int:
    return round(value)


def plan_delivered_frames(plan_json: str) -> int:
    """Return the exact delivered-frame duration of a Context Loop Plan."""

    if not isinstance(plan_json, str):
        raise ValueError("plan_json must be a string")
    try:
        plan = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan_json is not valid JSON: {exc.msg}") from exc
    if not isinstance(plan, Mapping):
        raise ValueError("plan_json root must be an object")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("plan_json.shots must be a non-empty array")

    total = 0
    for index, scene in enumerate(shots, 1):
        if not isinstance(scene, Mapping):
            raise ValueError(f"plan_json.shots[{index}] must be an object")
        length = scene.get("length")
        context = scene.get("context_length", 0)
        for name, value in (("length", length), ("context_length", context)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"plan_json.shots[{index}].{name} must be an integer"
                )
        delivered = length - context
        if delivered < 1:
            raise ValueError(
                f"plan_json.shots[{index}] must deliver at least one frame"
            )
        total += delivered
    return total


def target_sample_counts(
    audio_a: AudioShape,
    audio_b: AudioShape,
    *,
    plan_duration_ms: int = 0,
    target_h3_frames: int = 0,
    fps: int = 24,
    extra_padding_ms: int = 0,
) -> tuple[int, int]:
    """Return target samples for each rate using one exact rational duration."""

    audio_a.validate()
    audio_b.validate()
    for name, value in (
        ("plan_duration_ms", plan_duration_ms),
        ("target_h3_frames", target_h3_frames),
        ("fps", fps),
        ("extra_padding_ms", extra_padding_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
    if plan_duration_ms < 0 or target_h3_frames < 0 or extra_padding_ms < 0:
        raise ValueError("duration, frame target, and padding must be non-negative")
    if fps < 1:
        raise ValueError("fps must be positive")

    duration = max(
        Fraction(audio_a.samples, audio_a.sample_rate),
        Fraction(audio_b.samples, audio_b.sample_rate),
        Fraction(plan_duration_ms, 1000),
        Fraction(target_h3_frames, fps),
    ) + Fraction(extra_padding_ms, 1000)
    return (
        _ceil_fraction(duration * audio_a.sample_rate),
        _ceil_fraction(duration * audio_b.sample_rate),
    )


def _audio_parts(audio: Mapping[str, Any], name: str) -> tuple[Any, AudioShape]:
    if not isinstance(audio, Mapping):
        raise ValueError(f"{name} must be a ComfyUI AUDIO object")
    waveform = audio.get("waveform")
    sample_rate = audio.get("sample_rate")
    shape = getattr(waveform, "shape", None)
    if shape is None or len(shape) < 1:
        raise ValueError(f"{name}.waveform must have a sample dimension")
    result = AudioShape(sample_rate=sample_rate, samples=int(shape[-1]))
    result.validate()
    if not hasattr(waveform, "new_zeros"):
        raise ValueError(f"{name}.waveform does not support PCM padding")
    return waveform, result


def _pad_end(waveform: Any, target_samples: int) -> Any:
    source_samples = int(waveform.shape[-1])
    if target_samples <= source_samples:
        return waveform
    output = waveform.new_zeros((*tuple(waveform.shape[:-1]), target_samples))
    output[..., :source_samples] = waveform
    return output


def align_audio_to_plan_scenes(
    audio: Mapping[str, Any],
    scene_windows: tuple[SceneAudioWindow, ...],
    *,
    target_samples: int,
    fps: int = 24,
) -> tuple[dict[str, Any], tuple[int, ...]]:
    """Place source PCM on the cumulative H3 grid without altering samples.

    A Scene's delivered interval can be shorter than its source interval when
    an earlier Scene already accumulated H3 quantization surplus. Defer silence
    insertion until it cannot cause a later Scene to overflow. This may put the
    beginning of a source Scene in the preceding Plan Scene's unused tail, but
    never overlaps, resamples, or drops source PCM.
    """

    waveform, shape = _audio_parts(audio, "audio")
    if not scene_windows:
        raise ValueError("scene_windows must not be empty")
    if isinstance(target_samples, bool) or not isinstance(target_samples, int):
        raise ValueError("target_samples must be an integer")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise ValueError("fps must be a positive integer")
    if target_samples < shape.samples:
        raise ValueError("target_samples must not truncate the source audio")

    previous_source_end = 0
    delivered_start_frame = 0
    windows: list[tuple[int, int, int, int]] = []
    for index, window in enumerate(scene_windows, 1):
        window.validate()
        if window.source_start_ms != previous_source_end:
            raise ValueError("source Scene windows must be contiguous from zero")
        source_start = _round_fraction(
            Fraction(window.source_start_ms * shape.sample_rate, 1000)
        )
        source_end = _round_fraction(
            Fraction(window.source_end_ms * shape.sample_rate, 1000)
        )
        source_start = min(max(source_start, 0), shape.samples)
        source_end = min(max(source_end, source_start), shape.samples)
        if index == len(scene_windows) and shape.samples - source_end < _ceil_fraction(
            Fraction(shape.sample_rate, 1000)
        ):
            # The artifact serializes integer milliseconds, while the PCM may
            # contain a final fractional millisecond. Preserve those samples.
            source_end = shape.samples

        destination_start = _round_fraction(
            Fraction(delivered_start_frame * shape.sample_rate, fps)
        )
        delivered_end_frame = delivered_start_frame + window.delivered_frames
        destination_end = _round_fraction(
            Fraction(delivered_end_frame * shape.sample_rate, fps)
        )
        if source_end > destination_end:
            raise ValueError(
                f"source Scene {index} ends at {source_end} samples but its "
                f"cumulative Plan boundary holds {destination_end}; "
                "audio is not truncated"
            )
        windows.append((source_start, source_end, destination_start, destination_end))
        previous_source_end = window.source_end_ms
        delivered_start_frame = delivered_end_frame

    if previous_source_end * shape.sample_rate < shape.samples * 1000:
        # The artifact duration may be ceil-rounded by less than one ms. Only
        # reject when at least one complete millisecond of source is uncovered.
        uncovered = shape.samples - _round_fraction(
            Fraction(previous_source_end * shape.sample_rate, 1000)
        )
        if uncovered >= _ceil_fraction(Fraction(shape.sample_rate, 1000)):
            raise ValueError("source Scene windows do not cover the source audio")

    if windows[-1][3] > target_samples:
        raise ValueError("target_samples is shorter than the cumulative Plan")

    # At boundary i, at most (Plan end - source end) samples of silence may
    # have been inserted. The suffix minimum is the greatest safe cumulative
    # padding that still leaves room for every later source Scene.
    surplus = [0, *(plan_end - source_end for _, source_end, _, plan_end in windows)]
    cumulative_padding = [0] * (len(windows) + 1)
    future_minimum = surplus[-1]
    for index in range(len(windows), 0, -1):
        future_minimum = min(future_minimum, surplus[index])
        cumulative_padding[index] = future_minimum

    aligned = waveform.new_zeros((*tuple(waveform.shape[:-1]), target_samples))
    gap_samples: list[int] = []
    for index, (source_start, source_end, _plan_start, plan_end) in enumerate(windows):
        destination_start = source_start + cumulative_padding[index]
        copy_end = destination_start + source_end - source_start
        if copy_end > plan_end or copy_end > target_samples:
            raise ValueError("aligned Scene exceeds its cumulative Plan boundary")
        aligned[..., destination_start:copy_end] = waveform[..., source_start:source_end]
        gap_samples.append(cumulative_padding[index + 1] - cumulative_padding[index])

    result = dict(audio)
    result["waveform"] = aligned
    return result, tuple(gap_samples)


def pad_audio_pair(
    audio_a: Mapping[str, Any],
    audio_b: Mapping[str, Any],
    *,
    plan_duration_ms: int = 0,
    target_h3_frames: int = 0,
    fps: int = 24,
    extra_padding_ms: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], tuple[int, int]]:
    """Pad both inputs to a common exact duration and preserve their metadata."""

    waveform_a, shape_a = _audio_parts(audio_a, "audio_a")
    waveform_b, shape_b = _audio_parts(audio_b, "audio_b")
    targets = target_sample_counts(
        shape_a,
        shape_b,
        plan_duration_ms=plan_duration_ms,
        target_h3_frames=target_h3_frames,
        fps=fps,
        extra_padding_ms=extra_padding_ms,
    )
    padded_a = dict(audio_a)
    padded_b = dict(audio_b)
    padded_a["waveform"] = _pad_end(waveform_a, targets[0])
    padded_b["waveform"] = _pad_end(waveform_b, targets[1])
    return padded_a, padded_b, targets
