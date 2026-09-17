"""Pure Lyric Segmentation components."""

from .alignment import (
    AlignedLyric,
    WhisperWord,
    align_lyrics,
    build_whisper_initial_prompt,
    extract_whisper_words,
    match_similarity,
)
from .errors import LyricSegmentationError
from .plain import SourceLyricSegment, normalize_match_text, parse_plain_lyrics
from .recovery import TargetedRetryStats, recover_unplaced_lyrics
from .render import format_emd_time, format_srt_time, render_srt, render_template_emd
from .timeline_builder import ALGORITHM_VERSION, build_timeline
from .vad import (
    VoicedInterval,
    analyze_waveform,
    coarse_voiced_ranges,
    prepare_whisper_audio,
    refine_voiced_ranges,
    validate_comfy_audio,
)
from .whisper import WhisperLifecycle

__all__ = [
    "AlignedLyric",
    "ALGORITHM_VERSION",
    "LyricSegmentationError",
    "SourceLyricSegment",
    "TargetedRetryStats",
    "VoicedInterval",
    "WhisperWord",
    "WhisperLifecycle",
    "align_lyrics",
    "analyze_waveform",
    "build_timeline",
    "build_whisper_initial_prompt",
    "coarse_voiced_ranges",
    "extract_whisper_words",
    "format_emd_time",
    "format_srt_time",
    "match_similarity",
    "normalize_match_text",
    "parse_plain_lyrics",
    "prepare_whisper_audio",
    "refine_voiced_ranges",
    "recover_unplaced_lyrics",
    "render_srt",
    "render_template_emd",
    "validate_comfy_audio",
]
