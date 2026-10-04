"""Versioned, advisory source-clock activity metadata shared by EMD and Planner."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Mapping

STATES = frozenset({"vocal_candidate", "no_vocal_candidate", "instrumental_candidate",
                    "fullmix_silence_candidate", "unknown"})


@dataclass(frozen=True, slots=True)
class ActivityRange:
    start_sample: int
    end_sample: int
    state: str


@dataclass(frozen=True, slots=True)
class ReferenceCopy:
    source_start_sample: int
    source_end_sample: int
    destination_start_sample: int


@dataclass(frozen=True, slots=True)
class AudioActivity:
    sample_rate: int
    source_samples: int
    audio_sha256: str
    intervals: tuple[ActivityRange, ...]
    reference_copies: tuple[ReferenceCopy, ...] = ()
    method: str = "energy_vad_sample_refined"

    def validate(self) -> None:
        if self.method not in {"energy_vad_sample_refined", "author"}:
            raise ValueError("unknown audio activity method")
        for value in (self.sample_rate, self.source_samples):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("activity sample rate and size must be positive integers")
        if not re.fullmatch(r"[0-9a-f]{64}", self.audio_sha256):
            raise ValueError("activity audio fingerprint must be SHA-256")
        cursor = 0
        for item in self.intervals:
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (item.start_sample, item.end_sample)):
                raise ValueError("activity boundaries must be integer samples")
            if item.start_sample != cursor or not cursor < item.end_sample <= self.source_samples or item.state not in STATES:
                raise ValueError("activity intervals must cover source PCM once, in order")
            cursor = item.end_sample
        if cursor != self.source_samples:
            raise ValueError("activity intervals do not cover source PCM")
        source_cursor, destination_end = 0, 0
        for item in self.reference_copies:
            if any(isinstance(v, bool) or not isinstance(v, int) for v in
                   (item.source_start_sample, item.source_end_sample, item.destination_start_sample)):
                raise ValueError("reference copy positions must be integer samples")
            if (item.source_start_sample != source_cursor
                    or not source_cursor < item.source_end_sample <= self.source_samples
                    or item.destination_start_sample < destination_end):
                raise ValueError("reference copy ranges must be contiguous in source and non-overlapping in destination")
            source_cursor = item.source_end_sample
            destination_end = item.destination_start_sample + item.source_end_sample - item.source_start_sample
        if self.reference_copies and source_cursor != self.source_samples:
            raise ValueError("reference copies do not cover source PCM")

    @classmethod
    def from_diagnostic(cls, value: Mapping) -> "AudioActivity":
        if value.get("schema") != "MVD_AUDIO_ACTIVITY_DIAGNOSTIC_V1":
            raise ValueError("unsupported diagnostic activity schema")
        compact = []
        for row in value["source_intervals"]:
            item = ActivityRange(row["start_sample"], row["end_sample"], row["state"])
            if compact and compact[-1].state == item.state and compact[-1].end_sample == item.start_sample:
                compact[-1] = ActivityRange(compact[-1].start_sample, item.end_sample, item.state)
            else:
                compact.append(item)
        copies = tuple(ReferenceCopy(p["source_start_sample"], p["source_end_sample"], p["destination_start_sample"])
                       for p in value.get("aligned_reference", {}).get("placements", [])
                       if p["source_end_sample"] > p["source_start_sample"])
        result = cls(value["sample_rate"], value["source_samples"], value["audio_sha256"], tuple(compact), copies)
        result.validate()
        return result

    def to_dict(self) -> dict:
        self.validate()
        return {"schema": "MVD_AUDIO_ACTIVITY_V1", "timebase": "source_samples",
                "sample_rate": self.sample_rate, "source_samples": self.source_samples,
                "audio_sha256": self.audio_sha256, "method": self.method,
                "intervals": [{"start_sample": i.start_sample, "end_sample": i.end_sample, "state": i.state}
                              for i in self.intervals],
                "reference_copies": [{"source_start_sample": p.source_start_sample,
                                      "source_end_sample": p.source_end_sample,
                                      "destination_start_sample": p.destination_start_sample}
                                     for p in self.reference_copies]}

    def render_lines(self) -> list[str]:
        self.validate()
        return ["# 音声活動",
                f"* `音声活動v1` sample_rate={self.sample_rate} source_samples={self.source_samples} "
                f"sha256={self.audio_sha256} method={self.method}",
                *(f"* `ボーカル区間` {i.start_sample} {i.end_sample} {i.state}" for i in self.intervals),
                *(f"* `参照PCM配置` {p.source_start_sample} {p.source_end_sample} {p.destination_start_sample}"
                  for p in self.reference_copies)]

    def scene_payload(self, *, start_ms: int, end_ms: int, audio_mode: str) -> dict:
        """Clip to actual PCM clock; no Scene-index offset approximation."""
        self.validate()
        if audio_mode == "audio_reference" and not self.reference_copies:
            return {"schema": "MVD_SCENE_AUDIO_ACTIVITY_V1", "advisory": True,
                    "timebase": "unmapped_source", "intervals": [],
                    "warning": "No reference PCM mapping; retain normal authoring without guessing offsets"}
        ranges = []
        if audio_mode == "audio_reference":
            cursor = 0
            for p in self.reference_copies:
                if p.destination_start_sample > cursor:
                    ranges.append((cursor, p.destination_start_sample, "padding"))
                for i in self.intervals:
                    a, b = max(i.start_sample, p.source_start_sample), min(i.end_sample, p.source_end_sample)
                    if b > a:
                        offset = p.destination_start_sample - p.source_start_sample
                        ranges.append((a + offset, b + offset, i.state))
                cursor = p.destination_start_sample + p.source_end_sample - p.source_start_sample
            timebase = "aligned_reference_pcm"
        else:
            ranges = [(i.start_sample, i.end_sample, i.state) for i in self.intervals]
            cursor = self.source_samples
            timebase = "end_padded_source_pcm"
        window_start = Fraction(start_ms * self.sample_rate, 1000)
        window_end = Fraction(end_ms * self.sample_rate, 1000)
        if window_end > cursor:
            ranges.append((cursor, window_end, "padding"))
        voices = [(a, b) for a, b, state in ranges if state == "vocal_candidate"]
        local = []
        for a, b, state in ranges:
            clipped_a, clipped_b = max(a, window_start), min(b, window_end)
            if clipped_b <= clipped_a:
                continue
            absolute_start = float(clipped_a * 1000 / self.sample_rate)
            absolute_end = float(clipped_b * 1000 / self.sample_rate)
            local.append({"state": state, "start_ms": round(absolute_start, 3), "end_ms": round(absolute_end, 3),
                          "local_start_ms": round(absolute_start - start_ms, 3),
                          "local_end_ms": round(absolute_end - start_ms, 3)})
        previous = max((b for a, b in voices if b <= window_start), default=None)
        following = min((a for a, b in voices if a >= window_end), default=None)
        return {"schema": "MVD_SCENE_AUDIO_ACTIVITY_V1", "advisory": True, "timebase": timebase,
                "method": self.method, "intervals": local,
                "previous_vocal_end_ms": None if previous is None else round(float(previous * 1000 / self.sample_rate), 3),
                "next_vocal_start_ms": None if following is None else round(float(following * 1000 / self.sample_rate), 3),
                "song_position": "intro" if previous is None and voices and window_start < voices[0][0] else
                                 "outro" if voices and window_start >= voices[-1][1] else "internal"}
