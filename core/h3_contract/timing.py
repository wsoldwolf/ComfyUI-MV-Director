"""Typed H3 timing contract shared by segmentation and compilation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from ..artifacts.base import canonical_json

from .context_loop_0_6_6 import CONTRACT_ID


TIMING_SCHEMA = "MVD_H3_TIMING_PROFILE_V1"


@dataclass(frozen=True, slots=True)
class H3TimingProfile:
    schema: str = TIMING_SCHEMA
    contract: str = CONTRACT_ID
    fps: int = 24
    anchor_mode: str = "head"
    first_scene_context_length: int = 0
    continuation_context_length: int = 22
    audio_context_length: int = 22
    length_modulus: int = 17
    length_remainder: int = 5
    min_raw_length: int = 5
    max_raw_length: int = 3592

    def validate(self) -> None:
        if self.schema != TIMING_SCHEMA:
            raise ValueError("H3 timing profile schema mismatch")
        if self.contract != CONTRACT_ID:
            raise ValueError("unsupported H3 timing contract")
        for name in (
            "fps",
            "first_scene_context_length",
            "continuation_context_length",
            "audio_context_length",
            "length_modulus",
            "length_remainder",
            "min_raw_length",
            "max_raw_length",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
        if self.fps < 1 or self.length_modulus < 1:
            raise ValueError("fps and length_modulus must be positive")
        if not 0 <= self.length_remainder < self.length_modulus:
            raise ValueError("length_remainder must be inside the modulus")
        if not 0 <= self.first_scene_context_length:
            raise ValueError("first_scene_context_length must be non-negative")
        if not 0 <= self.continuation_context_length:
            raise ValueError("continuation_context_length must be non-negative")
        if not 0 <= self.audio_context_length:
            raise ValueError("audio_context_length must be non-negative")
        if self.min_raw_length < 1 or self.max_raw_length < self.min_raw_length:
            raise ValueError("raw length bounds are invalid")

    def validate_raw_length(self, value: int) -> None:
        self.validate()
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("raw H3 length must be an integer")
        if not self.min_raw_length <= value <= self.max_raw_length:
            raise ValueError(
                f"raw H3 length must be in {self.min_raw_length}..{self.max_raw_length}"
            )
        if value % self.length_modulus != self.length_remainder:
            raise ValueError(
                "raw H3 length must match "
                f"{self.length_modulus}k+{self.length_remainder}"
            )

    def quantize_duration_ms(
        self, duration_ms: int, *, first_scene: bool
    ) -> tuple[int, int, int]:
        """Return ``raw_length, delivered_frames, context_length`` by ceiling."""

        self.validate()
        if not isinstance(duration_ms, int) or isinstance(duration_ms, bool):
            raise ValueError("duration_ms must be an integer")
        if duration_ms < 1:
            raise ValueError("duration_ms must be positive")
        required_delivered = math.ceil(duration_ms * self.fps / 1000)
        return self.quantize_delivered_frames(
            required_delivered, first_scene=first_scene
        )

    def quantize_delivered_frames(
        self, required_delivered: int, *, first_scene: bool
    ) -> tuple[int, int, int]:
        """Ceil a required delivered-frame count onto the raw H3 grid."""

        self.validate()
        if (
            not isinstance(required_delivered, int)
            or isinstance(required_delivered, bool)
            or required_delivered < 1
        ):
            raise ValueError("required_delivered must be a positive integer")
        context = (
            self.first_scene_context_length
            if first_scene
            else self.continuation_context_length
        )
        required_raw = required_delivered + context
        k = max(
            0,
            math.ceil((required_raw - self.length_remainder) / self.length_modulus),
        )
        raw_length = k * self.length_modulus + self.length_remainder
        while raw_length < self.min_raw_length:
            raw_length += self.length_modulus
        self.validate_raw_length(raw_length)
        delivered = raw_length - context
        if delivered < 1:
            raise ValueError("timing profile produces no delivered frames")
        return raw_length, delivered, context

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    def to_json(self) -> str:
        return canonical_json(self)


DEFAULT_H3_TIMING_PROFILE = H3TimingProfile()
