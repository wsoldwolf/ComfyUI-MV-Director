"""Deterministic energy VAD with sample-domain edge refinement."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import math
from typing import Any, Iterable

from .errors import LyricSegmentationError


@dataclass(frozen=True, slots=True)
class VoicedInterval:
    start_sample: int
    end_sample: int


def _runs(flags: list[bool], total_samples: int, window_samples: int):
    if not flags:
        return []
    result: list[tuple[bool, int, int]] = []
    state = flags[0]
    start_index = 0
    for index in range(1, len(flags) + 1):
        if index < len(flags) and flags[index] == state:
            continue
        start = start_index * window_samples
        end = min(index * window_samples, total_samples)
        if end > start:
            result.append((state, start, end))
        if index < len(flags):
            state = flags[index]
            start_index = index
    return result


def coarse_voiced_ranges(
    window_dbfs: Iterable[float],
    *,
    total_samples: int,
    sample_rate: int,
    window_samples: int,
    threshold_dbfs: float = -45.0,
    min_voiced_ms: int = 120,
    min_silence_ms: int = 300,
) -> tuple[VoicedInterval, ...]:
    values = [float(value) for value in window_dbfs]
    if total_samples < 1 or sample_rate < 1 or window_samples < 1:
        raise LyricSegmentationError("VAD sample counts must be positive")
    if len(values) != math.ceil(total_samples / window_samples):
        raise LyricSegmentationError("VAD window count does not cover the PCM timeline")
    if any(not math.isfinite(value) for value in values):
        raise LyricSegmentationError("VAD values must be finite")
    flags = [value >= threshold_dbfs for value in values]

    minimum_silence = round(min_silence_ms * sample_rate / 1000)
    for state, start, end in _runs(flags, total_samples, window_samples):
        if state or end - start >= minimum_silence or start == 0 or end == total_samples:
            continue
        first = start // window_samples
        final = math.ceil(end / window_samples)
        flags[first:final] = [True] * (final - first)

    minimum_voice = round(min_voiced_ms * sample_rate / 1000)
    for state, start, end in _runs(flags, total_samples, window_samples):
        if not state or end - start >= minimum_voice:
            continue
        first = start // window_samples
        final = math.ceil(end / window_samples)
        flags[first:final] = [False] * (final - first)
    return tuple(
        VoicedInterval(start, end)
        for state, start, end in _runs(flags, total_samples, window_samples)
        if state
    )


def _import_torch() -> Any:
    try:
        return importlib.import_module("torch")
    except Exception as exc:
        raise LyricSegmentationError(
            "PyTorch is required at Lyric Segmentation execution time"
        ) from exc


def refine_voiced_ranges(
    envelope: Any,
    coarse: tuple[VoicedInterval, ...],
    *,
    total_samples: int,
    sample_rate: int,
    window_samples: int,
    threshold_dbfs: float = -45.0,
    padding_ms: int = 80,
) -> tuple[VoicedInterval, ...]:
    """Refine coarse edges against a per-sample RMS envelope with hysteresis."""

    enter = 10.0 ** (threshold_dbfs / 20.0)
    leave = 10.0 ** ((threshold_dbfs - 3.0) / 20.0)
    search = window_samples * 2
    padding = round(padding_ms * sample_rate / 1000)
    refined: list[VoicedInterval] = []
    for interval in coarse:
        left = max(0, interval.start_sample - search)
        right = min(total_samples, interval.start_sample + search)
        active_start = [
            index for index in range(left, right) if float(envelope[index]) >= enter
        ]
        start = active_start[0] if active_start else interval.start_sample
        left_end = max(start + 1, interval.end_sample - search)
        right_end = min(total_samples, interval.end_sample + search)
        active_end = [
            index for index in range(left_end, right_end) if float(envelope[index]) >= leave
        ]
        end = active_end[-1] + 1 if active_end else interval.end_sample
        start = max(0, start - padding)
        end = min(total_samples, end + padding)
        if refined and start <= refined[-1].end_sample:
            refined[-1] = VoicedInterval(
                refined[-1].start_sample, max(refined[-1].end_sample, end)
            )
        elif end > start:
            refined.append(VoicedInterval(start, end))
    return tuple(refined)


def validate_comfy_audio(audio: Any) -> tuple[Any, int, int]:
    if not isinstance(audio, dict):
        raise LyricSegmentationError("vocal_audio must be a ComfyUI AUDIO object")
    waveform = audio.get("waveform")
    sample_rate = audio.get("sample_rate")
    if waveform is None or not hasattr(waveform, "shape"):
        raise LyricSegmentationError("vocal_audio.waveform must be a tensor")
    shape = tuple(waveform.shape)
    if len(shape) != 3 or shape[0] != 1 or shape[1] < 1 or shape[2] < 1:
        raise LyricSegmentationError(
            "vocal_audio.waveform must have shape [1, channels>=1, samples>=1]"
        )
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate < 1:
        raise LyricSegmentationError("vocal_audio.sample_rate must be a positive integer")
    return waveform, sample_rate, int(shape[2])


def analyze_waveform(
    waveform: Any,
    *,
    sample_rate: int,
    total_samples: int,
    hop_ms: int = 20,
    threshold_dbfs: float = -45.0,
    min_voiced_ms: int = 120,
    min_silence_ms: int = 300,
    padding_ms: int = 80,
) -> tuple[VoicedInterval, ...]:
    """Use max per-channel RMS, then refine threshold crossings at sample resolution."""

    torch = _import_torch()
    try:
        channels = waveform.detach()[0].to(dtype=torch.float32, device="cpu")
        if not bool(torch.isfinite(channels).all().item()):
            raise LyricSegmentationError("vocal_audio contains NaN or infinity")
        window_samples = max(1, round(hop_ms * sample_rate / 1000))
        dbfs: list[float] = []
        for start in range(0, total_samples, window_samples):
            frame = channels[..., start : min(total_samples, start + window_samples)]
            rms = frame.square().mean(dim=-1).sqrt().amax()
            dbfs.append(20.0 * math.log10(max(float(rms.item()), 1e-12)))
        coarse = coarse_voiced_ranges(
            dbfs,
            total_samples=total_samples,
            sample_rate=sample_rate,
            window_samples=window_samples,
            threshold_dbfs=threshold_dbfs,
            min_voiced_ms=min_voiced_ms,
            min_silence_ms=min_silence_ms,
        )
        if not coarse:
            return ()

        # A short moving RMS is evaluated at every original sample.  Threshold
        # entry and a 3 dB lower exit threshold provide deterministic hysteresis.
        functional = importlib.import_module("torch.nn.functional")
        kernel = max(1, round(sample_rate * 0.005))
        if kernel % 2 == 0:
            kernel += 1
        envelope = functional.avg_pool1d(
            channels.square().unsqueeze(0),
            kernel_size=kernel,
            stride=1,
            padding=kernel // 2,
        ).sqrt().amax(dim=1)[0]
        return refine_voiced_ranges(
            envelope,
            coarse,
            total_samples=total_samples,
            sample_rate=sample_rate,
            window_samples=window_samples,
            threshold_dbfs=threshold_dbfs,
            padding_ms=padding_ms,
        )
    except LyricSegmentationError:
        raise
    except Exception as exc:
        raise LyricSegmentationError("failed to analyze vocal_audio with energy VAD") from exc


def prepare_whisper_audio(
    waveform: Any, *, sample_rate: int, total_samples: int
) -> Any:
    torch = _import_torch()
    try:
        mono = waveform.detach()[0].to(dtype=torch.float32).mean(dim=0)
        if sample_rate != 16000:
            functional = importlib.import_module("torch.nn.functional")
            target = max(1, round(total_samples * 16000 / sample_rate))
            mono = functional.interpolate(
                mono.reshape(1, 1, total_samples),
                size=target,
                mode="linear",
                align_corners=False,
            ).reshape(target)
        return mono.detach().cpu().contiguous()
    except Exception as exc:
        raise LyricSegmentationError("failed to prepare 16 kHz mono Whisper audio") from exc
