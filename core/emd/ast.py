"""Immutable EMD abstract syntax tree."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Subject:
    concept_id: str
    subject_ref: str
    description: str
    references: tuple[str, ...]
    line_number: int


@dataclass(frozen=True, slots=True)
class RetentionDirective:
    concept_id: str
    mode: str
    description: str
    line_number: int


@dataclass(frozen=True, slots=True)
class LyricAnnotation:
    text: str
    section: str | None
    start_ms: int | None
    end_ms: int | None
    line_number: int


@dataclass(frozen=True, slots=True)
class AudioDirective:
    mode: str
    target_concept_id: str | None
    audio_slot: int | None
    line_number: int


@dataclass(frozen=True, slots=True)
class Shot:
    start_ms: int
    body: tuple[str, ...]
    lyric_annotations: tuple[LyricAnnotation, ...]
    lyric_lip_sync: tuple[tuple[str, str], ...]
    line_number: int


@dataclass(frozen=True, slots=True)
class Scene:
    scene_number: int
    start_ms: int
    end_ms: int
    h3_length: int
    descriptions: tuple[str, ...]
    shots: tuple[Shot, ...]
    audio_directives: tuple[AudioDirective, ...]
    line_number: int


@dataclass(frozen=True, slots=True)
class EMDDocument:
    subjects: tuple[Subject, ...]
    retention: tuple[RetentionDirective, ...]
    common_prompt: tuple[tuple[str, tuple[str, ...]], ...]
    scenes: tuple[Scene, ...]

    def common_prompt_dict(self) -> dict[str, tuple[str, ...]]:
        return dict(self.common_prompt)
