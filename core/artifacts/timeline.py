"""MVD_TIMELINE_V1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .base import (
    canonical_json,
    require_exact_keys,
    require_integer,
    require_sequence,
    require_string,
)
from .errors import ArtifactValidationError


SCHEMA = "MVD_TIMELINE_V1"


@dataclass(frozen=True, slots=True)
class TimelineShot:
    start_ms: int
    end_ms: int

    def validate(self, path: str = "shots[]") -> None:
        require_integer(self.start_ms, schema=SCHEMA, path=f"{path}.start_ms", minimum=0)
        require_integer(self.end_ms, schema=SCHEMA, path=f"{path}.end_ms", minimum=1)
        if self.end_ms <= self.start_ms:
            raise ArtifactValidationError(
                SCHEMA, path, "end_ms must be greater than start_ms"
            )

    def to_dict(self) -> dict[str, int]:
        self.validate()
        return {"start_ms": self.start_ms, "end_ms": self.end_ms}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TimelineShot":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="shots[]",
            required={"start_ms", "end_ms"},
        )
        result = cls(start_ms=value["start_ms"], end_ms=value["end_ms"])
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class TimelineScene:
    scene_number: int
    start_ms: int
    end_ms: int
    source_start_ms: int
    source_end_ms: int
    raw_length: int
    delivered_frames: int
    context_length: int
    shots: tuple[TimelineShot, ...]

    def validate(self, path: str = "scenes[]") -> None:
        for field_name, minimum in (
            ("scene_number", 1),
            ("start_ms", 0),
            ("end_ms", 1),
            ("source_start_ms", 0),
            ("source_end_ms", 1),
            ("raw_length", 1),
            ("delivered_frames", 1),
            ("context_length", 0),
        ):
            require_integer(
                getattr(self, field_name),
                schema=SCHEMA,
                path=f"{path}.{field_name}",
                minimum=minimum,
            )
        if self.end_ms <= self.start_ms:
            raise ArtifactValidationError(
                SCHEMA, path, "end_ms must be greater than start_ms"
            )
        if self.source_end_ms <= self.source_start_ms:
            raise ArtifactValidationError(
                SCHEMA, path, "source_end_ms must be greater than source_start_ms"
            )
        if not self.shots:
            raise ArtifactValidationError(SCHEMA, f"{path}.shots", "must not be empty")
        for index, shot in enumerate(self.shots):
            if not isinstance(shot, TimelineShot):
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.shots[{index}]", "invalid shot"
                )
            shot.validate(f"{path}.shots[{index}]")
        if self.shots[0].start_ms != self.start_ms:
            raise ArtifactValidationError(
                SCHEMA, f"{path}.shots[0].start_ms", "must equal Scene start_ms"
            )
        for index, shot in enumerate(self.shots):
            if index and shot.start_ms != self.shots[index - 1].end_ms:
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.shots[{index}]", "shots must be contiguous"
                )
        if self.shots[-1].end_ms != self.end_ms:
            raise ArtifactValidationError(
                SCHEMA, f"{path}.shots[-1].end_ms", "must equal Scene end_ms"
            )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "scene_number": self.scene_number,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "source_start_ms": self.source_start_ms,
            "source_end_ms": self.source_end_ms,
            "raw_length": self.raw_length,
            "delivered_frames": self.delivered_frames,
            "context_length": self.context_length,
            "shots": [shot.to_dict() for shot in self.shots],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TimelineScene":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="scenes[]",
            required={
                "scene_number",
                "start_ms",
                "end_ms",
                "source_start_ms",
                "source_end_ms",
                "raw_length",
                "delivered_frames",
                "context_length",
                "shots",
            },
        )
        shots = require_sequence(value["shots"], schema=SCHEMA, path="scenes[].shots")
        result = cls(
            scene_number=value["scene_number"],
            start_ms=value["start_ms"],
            end_ms=value["end_ms"],
            source_start_ms=value["source_start_ms"],
            source_end_ms=value["source_end_ms"],
            raw_length=value["raw_length"],
            delivered_frames=value["delivered_frames"],
            context_length=value["context_length"],
            shots=tuple(TimelineShot.from_dict(item) for item in shots),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class LyricSegment:
    segment_id: str
    text: str
    source_line: int
    source_start: int
    source_end: int
    start_ms: int
    end_ms: int
    scene_number: int
    shot_index: int

    def validate(self, path: str = "lyrics[]") -> None:
        require_string(self.segment_id, schema=SCHEMA, path=f"{path}.segment_id")
        require_string(self.text, schema=SCHEMA, path=f"{path}.text")
        for field_name, minimum in (
            ("source_line", 1),
            ("source_start", 0),
            ("source_end", 0),
            ("start_ms", 0),
            ("end_ms", 1),
            ("scene_number", 1),
            ("shot_index", 1),
        ):
            require_integer(
                getattr(self, field_name),
                schema=SCHEMA,
                path=f"{path}.{field_name}",
                minimum=minimum,
            )
        if self.source_end <= self.source_start:
            raise ArtifactValidationError(
                SCHEMA, path, "source_end must be greater than source_start"
            )
        if self.end_ms <= self.start_ms:
            raise ArtifactValidationError(
                SCHEMA, path, "end_ms must be greater than start_ms"
            )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "segment_id": self.segment_id,
            "text": self.text,
            "source_line": self.source_line,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "scene_number": self.scene_number,
            "shot_index": self.shot_index,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LyricSegment":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="lyrics[]",
            required={
                "segment_id",
                "text",
                "source_line",
                "source_start",
                "source_end",
                "start_ms",
                "end_ms",
                "scene_number",
                "shot_index",
            },
        )
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class UnplacedLyric:
    segment_id: str
    text: str
    source_line: int
    source_start: int
    source_end: int
    reason: str

    def validate(self, path: str = "unplaced_lyrics[]") -> None:
        require_string(self.segment_id, schema=SCHEMA, path=f"{path}.segment_id")
        require_string(self.text, schema=SCHEMA, path=f"{path}.text")
        require_integer(
            self.source_line, schema=SCHEMA, path=f"{path}.source_line", minimum=1
        )
        require_integer(
            self.source_start, schema=SCHEMA, path=f"{path}.source_start", minimum=0
        )
        require_integer(
            self.source_end, schema=SCHEMA, path=f"{path}.source_end", minimum=0
        )
        if self.source_end <= self.source_start:
            raise ArtifactValidationError(
                SCHEMA, path, "source_end must be greater than source_start"
            )
        require_string(self.reason, schema=SCHEMA, path=f"{path}.reason")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "segment_id": self.segment_id,
            "text": self.text,
            "source_line": self.source_line,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnplacedLyric":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="unplaced_lyrics[]",
            required={
                "segment_id",
                "text",
                "source_line",
                "source_start",
                "source_end",
                "reason",
            },
        )
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class TimelineArtifact:
    vad_analysis_hop_ms: int
    boundary_resolution_ms: int
    boundary_method: str
    source_audio_duration_ms: int
    plan_duration_ms: int
    timing_profile: str
    lyrics: tuple[LyricSegment, ...]
    scenes: tuple[TimelineScene, ...]
    unplaced_lyrics: tuple[UnplacedLyric, ...] = ()
    schema: str = SCHEMA
    timebase: str = "source_audio"
    time_unit: str = "ms"

    def validate(self) -> None:
        if self.schema != SCHEMA:
            raise ArtifactValidationError(SCHEMA, "schema", "schema mismatch")
        if self.timebase != "source_audio":
            raise ArtifactValidationError(SCHEMA, "timebase", "must be source_audio")
        if self.time_unit != "ms":
            raise ArtifactValidationError(SCHEMA, "time_unit", "must be ms")
        for field_name, minimum in (
            ("vad_analysis_hop_ms", 1),
            ("boundary_resolution_ms", 1),
            ("source_audio_duration_ms", 1),
            ("plan_duration_ms", 1),
        ):
            require_integer(
                getattr(self, field_name),
                schema=SCHEMA,
                path=field_name,
                minimum=minimum,
            )
        require_string(
            self.boundary_method, schema=SCHEMA, path="boundary_method"
        )
        require_string(self.timing_profile, schema=SCHEMA, path="timing_profile")
        if not self.scenes:
            raise ArtifactValidationError(SCHEMA, "scenes", "must not be empty")

        previous_plan_end = 0
        previous_source_end = 0
        scene_map: dict[int, TimelineScene] = {}
        for index, scene in enumerate(self.scenes):
            path = f"scenes[{index}]"
            if not isinstance(scene, TimelineScene):
                raise ArtifactValidationError(SCHEMA, path, "invalid scene")
            scene.validate(path)
            expected_number = index + 1
            if scene.scene_number != expected_number:
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.scene_number", f"must be {expected_number}"
                )
            if scene.start_ms != previous_plan_end:
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.start_ms", "Plan scenes must be contiguous"
                )
            if scene.source_start_ms != previous_source_end:
                raise ArtifactValidationError(
                    SCHEMA,
                    f"{path}.source_start_ms",
                    "source scenes must be contiguous",
                )
            previous_plan_end = scene.end_ms
            previous_source_end = scene.source_end_ms
            scene_map[scene.scene_number] = scene
        if previous_plan_end != self.plan_duration_ms:
            raise ArtifactValidationError(
                SCHEMA, "plan_duration_ms", "must equal final Scene end_ms"
            )
        if previous_source_end != self.source_audio_duration_ms:
            raise ArtifactValidationError(
                SCHEMA,
                "source_audio_duration_ms",
                "must equal final Scene source_end_ms",
            )

        segment_ids: set[str] = set()
        for index, lyric in enumerate(self.lyrics):
            path = f"lyrics[{index}]"
            if not isinstance(lyric, LyricSegment):
                raise ArtifactValidationError(SCHEMA, path, "invalid lyric")
            lyric.validate(path)
            if lyric.segment_id in segment_ids:
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.segment_id", "duplicate segment ID"
                )
            segment_ids.add(lyric.segment_id)
            if lyric.end_ms > self.source_audio_duration_ms:
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.end_ms", "outside source audio"
                )
            scene = scene_map.get(lyric.scene_number)
            if scene is None or lyric.shot_index > len(scene.shots):
                raise ArtifactValidationError(
                    SCHEMA, path, "invalid structural Scene/Shot assignment"
                )
        for index, lyric in enumerate(self.unplaced_lyrics):
            path = f"unplaced_lyrics[{index}]"
            if not isinstance(lyric, UnplacedLyric):
                raise ArtifactValidationError(SCHEMA, path, "invalid unplaced lyric")
            lyric.validate(path)
            if lyric.segment_id in segment_ids:
                raise ArtifactValidationError(
                    SCHEMA, f"{path}.segment_id", "duplicate segment ID"
                )
            segment_ids.add(lyric.segment_id)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": self.schema,
            "timebase": self.timebase,
            "time_unit": self.time_unit,
            "vad_analysis_hop_ms": self.vad_analysis_hop_ms,
            "boundary_resolution_ms": self.boundary_resolution_ms,
            "boundary_method": self.boundary_method,
            "source_audio_duration_ms": self.source_audio_duration_ms,
            "plan_duration_ms": self.plan_duration_ms,
            "timing_profile": self.timing_profile,
            "lyrics": [lyric.to_dict() for lyric in self.lyrics],
            "scenes": [scene.to_dict() for scene in self.scenes],
            "unplaced_lyrics": [
                lyric.to_dict() for lyric in self.unplaced_lyrics
            ],
        }

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TimelineArtifact":
        require_exact_keys(
            value,
            schema=SCHEMA,
            path="$",
            required={
                "schema",
                "timebase",
                "time_unit",
                "vad_analysis_hop_ms",
                "boundary_resolution_ms",
                "boundary_method",
                "source_audio_duration_ms",
                "plan_duration_ms",
                "timing_profile",
                "lyrics",
                "scenes",
                "unplaced_lyrics",
            },
        )
        lyrics = require_sequence(value["lyrics"], schema=SCHEMA, path="lyrics")
        scenes = require_sequence(value["scenes"], schema=SCHEMA, path="scenes")
        unplaced = require_sequence(
            value["unplaced_lyrics"], schema=SCHEMA, path="unplaced_lyrics"
        )
        artifact = cls(
            schema=value["schema"],
            timebase=value["timebase"],
            time_unit=value["time_unit"],
            vad_analysis_hop_ms=value["vad_analysis_hop_ms"],
            boundary_resolution_ms=value["boundary_resolution_ms"],
            boundary_method=value["boundary_method"],
            source_audio_duration_ms=value["source_audio_duration_ms"],
            plan_duration_ms=value["plan_duration_ms"],
            timing_profile=value["timing_profile"],
            lyrics=tuple(LyricSegment.from_dict(item) for item in lyrics),
            scenes=tuple(TimelineScene.from_dict(item) for item in scenes),
            unplaced_lyrics=tuple(
                UnplacedLyric.from_dict(item) for item in unplaced
            ),
        )
        artifact.validate()
        return artifact

