"""Pair-wise end padding without resampling, mixing, or truncation."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
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
    """Place each source Scene at its cumulative H3 delivered-frame position.

    Source content is copied without resampling or truncation. Quantization
    surplus inside each delivered Scene remains PCM zero.
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

    aligned = waveform.new_zeros((*tuple(waveform.shape[:-1]), target_samples))
    previous_source_end = 0
    delivered_start_frame = 0
    gap_samples: list[int] = []
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

        destination_start = _round_fraction(
            Fraction(delivered_start_frame * shape.sample_rate, fps)
        )
        delivered_end_frame = delivered_start_frame + window.delivered_frames
        destination_end = _round_fraction(
            Fraction(delivered_end_frame * shape.sample_rate, fps)
        )
        source_length = source_end - source_start
        capacity = destination_end - destination_start
        if source_length > capacity:
            raise ValueError(
                f"source Scene {index} has {source_length} samples but its "
                f"Plan delivered interval holds {capacity}; audio is not truncated"
            )
        copy_end = destination_start + source_length
        if copy_end > target_samples:
            raise ValueError("aligned Scene exceeds target audio duration")
        aligned[..., destination_start:copy_end] = waveform[..., source_start:source_end]
        gap_samples.append(capacity - source_length)
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
