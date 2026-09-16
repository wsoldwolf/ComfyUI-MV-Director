"""ComfyUI wrapper for deterministic Lyric Segmentation."""

from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path
import threading
from typing import Any

try:
    from ...core.artifacts import TimelineArtifact
    from ...core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
    from ...core.inference import SuccessCache, build_cache_key
    from ...core.lyrics import (
        ALGORITHM_VERSION,
        WhisperLifecycle,
        align_lyrics,
        analyze_waveform,
        build_timeline,
        build_whisper_initial_prompt,
        extract_whisper_words,
        parse_plain_lyrics,
        prepare_whisper_audio,
        render_srt,
        render_template_emd,
        validate_comfy_audio,
    )
except ImportError:  # Standalone repository tests.
    from core.artifacts import TimelineArtifact
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
    from core.inference import SuccessCache, build_cache_key
    from core.lyrics import (
        ALGORITHM_VERSION,
        WhisperLifecycle,
        align_lyrics,
        analyze_waveform,
        build_timeline,
        build_whisper_initial_prompt,
        extract_whisper_words,
        parse_plain_lyrics,
        prepare_whisper_audio,
        render_srt,
        render_template_emd,
        validate_comfy_audio,
    )

from ..common.whisper_discovery import (
    resolve_comfy_whisper_model,
    whisper_model_choices,
)


CACHE_MODES = ("reuse", "refresh", "disabled")
_LOGGER = logging.getLogger("mv_director.lyrics")


def _cache() -> SuccessCache | None:
    try:
        import folder_paths  # type: ignore

        root = Path(folder_paths.get_temp_directory())
    except Exception:
        return None
    return SuccessCache(root / "mv_director" / "lyric_segmentation_cache")


def _audio_digest(waveform: Any, *, sample_rate: int) -> str:
    try:
        raw = waveform.detach().cpu().contiguous().numpy().tobytes()
    except Exception as exc:
        raise ValueError("could not fingerprint vocal_audio") from exc
    digest = hashlib.sha256()
    digest.update(str(tuple(waveform.shape)).encode("ascii"))
    digest.update(str(sample_rate).encode("ascii"))
    digest.update(raw)
    return digest.hexdigest()


def _status(timeline: TimelineArtifact, *, cache: str) -> str:
    return (
        f"resolved={len(timeline.lyrics)}; "
        f"unplaced={len(timeline.unplaced_lyrics)}; "
        f"source_ms={timeline.source_audio_duration_ms}; "
        f"plan_ms={timeline.plan_duration_ms}; "
        f"scenes={len(timeline.scenes)}; cache={cache}"
    )


def _block_unplaced(
    timeline: TimelineArtifact,
    *,
    cache: str,
) -> dict[str, Any]:
    section_counts: dict[str, int] = {}
    for item in timeline.unplaced_lyrics:
        section = item.section or "(none)"
        section_counts[section] = section_counts.get(section, 0) + 1
    section_summary = ",".join(
        f"{section}:{count}" for section, count in section_counts.items()
    )
    status = (
        f"complete=no; reason=unplaced_lyrics; "
        f"unplaced_sections={section_summary}; {_status(timeline, cache=cache)}"
    )
    preview = ", ".join(
        f"{item.segment_id}:{item.text}"
        for item in timeline.unplaced_lyrics[:5]
    )
    if len(timeline.unplaced_lyrics) > 5:
        preview += f", ... (+{len(timeline.unplaced_lyrics) - 5})"
    message = (
        "Lyric Segmentation did not place every lyric segment; "
        f"unplaced={len(timeline.unplaced_lyrics)}; "
        f"sections={section_summary}; items={preview}. "
        "The Template EMD, SRT, and timeline outputs were blocked. "
        "Use vocal audio containing every supplied lyric, or remove lyrics "
        "that are not sung in this audio."
    )
    _LOGGER.error("[MV Director - Lyric Segmentation] %s", message)
    try:
        from comfy_execution.graph import ExecutionBlocker  # type: ignore
    except Exception as exc:
        raise RuntimeError(message) from exc
    blocker = ExecutionBlocker(message)
    return {
        "ui": {"status": [status]},
        "result": (blocker, blocker, blocker, status),
    }


class MVDirectorLyricSegmentation:
    RETURN_TYPES = ("STRING", "STRING", "MV_DIRECTOR_TIMELINE", "STRING")
    RETURN_NAMES = ("template_emd", "srt_text", "timeline", "status")
    FUNCTION = "segment"
    CATEGORY = "MV Director/Input"
    DESCRIPTION = "ボーカルとplain lyricsからTemplate EMD、SRT、整数ms timelineを生成します。"

    def __init__(self) -> None:
        self._whisper = WhisperLifecycle()
        self._lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        models = whisper_model_choices()
        return {
            "required": {
                "vocal_audio": ("AUDIO",),
                "lyrics_text": ("STRING", {"default": "[VERSE1]\n", "multiline": True, "forceInput": True}),
                "whisper_model": (models, {"default": models[0]}),
                "language": (["ja"], {"default": "ja"}),
                "max_scene_duration_ms": ("INT", {"default": 10000, "min": 1000, "max": 120000, "step": 1}),
                "srt_time_offset_ms": ("INT", {"default": 0, "min": -3600000, "max": 3600000, "step": 1}),
                "cache_mode": (list(CACHE_MODES), {"default": "reuse"}),
                "keep_whisper_loaded": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "h3_timing_profile": ("MV_DIRECTOR_H3_TIMING_PROFILE",),
            },
        }

    def segment(
        self,
        vocal_audio: Any,
        lyrics_text: str,
        whisper_model: str,
        language: str,
        max_scene_duration_ms: int,
        srt_time_offset_ms: int,
        cache_mode: str,
        keep_whisper_loaded: bool,
        h3_timing_profile: H3TimingProfile | None = None,
    ) -> tuple[str, str, TimelineArtifact, str] | dict[str, Any]:
        with self._lock:
            if cache_mode not in CACHE_MODES:
                raise ValueError("cache_mode must be reuse, refresh, or disabled")
            if language != "ja":
                raise ValueError("initial Lyric Segmentation language must be ja")
            profile = h3_timing_profile or DEFAULT_H3_TIMING_PROFILE
            profile.validate()
            lyrics = parse_plain_lyrics(lyrics_text)
            waveform, sample_rate, total_samples = validate_comfy_audio(vocal_audio)
            duration_ms = math.ceil(total_samples * 1000 / sample_rate)
            model = resolve_comfy_whisper_model(whisper_model)
            key = build_cache_key(
                task="lyric-segmentation",
                algorithm_version=ALGORITHM_VERSION,
                inputs={
                    "audio_sha256": _audio_digest(waveform, sample_rate=sample_rate),
                    "lyrics_text": lyrics_text.replace("\r\n", "\n").replace("\r", "\n"),
                    "model": {
                        "selection_id": model.selection_id,
                        "size": model.size,
                        "mtime_ns": model.mtime_ns,
                    },
                    "language": language,
                    "max_scene_duration_ms": max_scene_duration_ms,
                    "timing_profile": profile.to_dict(),
                },
            )
            cache = _cache()
            cached = cache.get(key) if cache_mode == "reuse" and cache else None
            if cached and isinstance(cached.get("timeline"), dict):
                timeline = TimelineArtifact.from_dict(cached["timeline"])
                template = str(cached["template_emd"])
                srt = render_srt(timeline, offset_ms=srt_time_offset_ms)
                status = _status(timeline, cache="hit")
                if not keep_whisper_loaded:
                    self._whisper.clear()
                if timeline.unplaced_lyrics:
                    return _block_unplaced(timeline, cache="hit")
                return template, srt, timeline, status

            try:
                voiced = analyze_waveform(
                    waveform,
                    sample_rate=sample_rate,
                    total_samples=total_samples,
                )
                if lyrics:
                    device = self._whisper.resolve_device()
                    self._whisper.ensure_loaded(model.path, device=device)
                    whisper_audio = prepare_whisper_audio(
                        waveform,
                        sample_rate=sample_rate,
                        total_samples=total_samples,
                    )
                    transcription = self._whisper.transcribe(
                        whisper_audio,
                        language=language,
                        device=device,
                        initial_prompt=build_whisper_initial_prompt(lyrics),
                    )
                    words = extract_whisper_words(
                        transcription, audio_duration_ms=duration_ms
                    )
                    resolved, unplaced = align_lyrics(
                        lyrics,
                        words,
                        voiced_intervals=voiced,
                        sample_rate=sample_rate,
                        audio_duration_ms=duration_ms,
                    )
                else:
                    resolved, unplaced = (), ()
                timeline = build_timeline(
                    resolved,
                    unplaced,
                    source_audio_duration_ms=duration_ms,
                    max_scene_duration_ms=max_scene_duration_ms,
                    timing_profile=profile,
                )
                if timeline.unplaced_lyrics:
                    return _block_unplaced(timeline, cache="miss")
                template = render_template_emd(timeline).text
                srt = render_srt(timeline, offset_ms=srt_time_offset_ms)
                status = _status(timeline, cache="miss")
                if cache_mode in {"reuse", "refresh"} and cache is not None:
                    cache.put_success(
                        key,
                        {
                            "timeline": timeline.to_dict(),
                            "template_emd": template,
                            "status": _status(timeline, cache="stored"),
                        },
                    )
                return template, srt, timeline, status
            finally:
                if not keep_whisper_loaded:
                    self._whisper.clear()
