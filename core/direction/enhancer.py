"""One-pass Direction Enhancer using MVD_LLM_RECORDS_V1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..artifacts import (
    DirectionArtifact,
    ObservationsArtifact,
    ProvenanceRecord,
    canonical_json,
    normalize_newlines,
    sha256_text,
)
from ..inference import LlamaRuntimeConfig
from ..protocols import LLMRecord, LLMRecordIssue, parse_llm_records
from .profiles import CAMERA_PROFILES, MOTION_PROFILES, STYLE_PROFILES


DIRECTION_PROMPT_VERSION = "mvd-direction-enhancer-v1"
_ALLOWED = {
    "STYLE": frozenset({1}),
    "MOTION": frozenset({1}),
    "CAMERA": frozenset({1}),
    "OTHER": frozenset({1}),
}
_REQUIRED = frozenset({("STYLE", 1), ("MOTION", 1), ("CAMERA", 1)})
_FIELD_BY_TYPE = {
    "STYLE": "style_direction",
    "MOTION": "motion_direction",
    "CAMERA": "camera_direction",
    "OTHER": "other_direction",
}


class DirectionEnhancerError(ValueError):
    pass


class DirectionEnhancerBackend(Protocol):
    def complete_direction(
        self,
        *,
        system_prompt: str,
        payload: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> str:
        ...


@dataclass(frozen=True, slots=True)
class DirectionEnhancerInput:
    concept_emd: str = ""
    observations_json: str = ""
    user_request: str = ""
    style_profile: str = "reference_anime"
    motion_profile: str = "natural_performance"
    camera_profile: str = "readable_depth"

    def validate(self) -> None:
        for name in ("concept_emd", "observations_json", "user_request"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise DirectionEnhancerError(f"{name} must be a string")
            if "\x00" in value:
                raise DirectionEnhancerError(f"{name} contains NUL")
        if self.style_profile not in STYLE_PROFILES:
            raise DirectionEnhancerError("unknown style_profile")
        if self.motion_profile not in MOTION_PROFILES:
            raise DirectionEnhancerError("unknown motion_profile")
        if self.camera_profile not in CAMERA_PROFILES:
            raise DirectionEnhancerError("unknown camera_profile")
        concept = self.normalized_concept_emd
        if concept:
            headings = [line for line in concept.split("\n") if line.startswith("# ")]
            if headings != ["# サブジェクト"]:
                raise DirectionEnhancerError(
                    "concept_emd must be one # サブジェクト fragment"
                )
        if self.normalized_observations_json:
            try:
                value = json.loads(self.normalized_observations_json)
            except json.JSONDecodeError as exc:
                raise DirectionEnhancerError("observations_json is invalid JSON") from exc
            if not isinstance(value, dict):
                raise DirectionEnhancerError("observations_json must contain an object")
            ObservationsArtifact.from_dict(value)

    @property
    def normalized_concept_emd(self) -> str:
        return normalize_newlines(self.concept_emd).strip()

    @property
    def normalized_observations_json(self) -> str:
        return normalize_newlines(self.observations_json).strip()

    @property
    def normalized_user_request(self) -> str:
        return normalize_newlines(self.user_request).strip()


@dataclass(frozen=True, slots=True)
class DirectionEnhancerResult:
    direction: DirectionArtifact
    direction_emd_preview: str
    issues: tuple[LLMRecordIssue, ...]
    retried_missing: tuple[tuple[str, int], ...]


def build_direction_payload(value: DirectionEnhancerInput) -> str:
    value.validate()
    payload: dict[str, object] = {
        "protocol": "MVD_LLM_RECORDS_V1",
        "task": DIRECTION_PROMPT_VERSION,
        "authority_order": ["user", "vision_concept", "profile", "generated"],
        "user_request": value.normalized_user_request,
        "concept_emd": value.normalized_concept_emd,
        "profiles": {
            "style": {
                "id": value.style_profile,
                "text": STYLE_PROFILES[value.style_profile],
            },
            "motion": {
                "id": value.motion_profile,
                "text": MOTION_PROFILES[value.motion_profile],
            },
            "camera": {
                "id": value.camera_profile,
                "text": CAMERA_PROFILES[value.camera_profile],
            },
        },
    }
    if value.normalized_observations_json:
        payload["vision_observations"] = json.loads(
            value.normalized_observations_json
        )
    return canonical_json(payload)


def _input_provenance(value: DirectionEnhancerInput) -> list[ProvenanceRecord]:
    items: list[tuple[str, str, str]] = []
    if value.normalized_user_request:
        items.append(("user", "user_request", value.normalized_user_request))
    if value.normalized_concept_emd:
        items.append(("vision", "concept_emd", value.normalized_concept_emd))
    if value.normalized_observations_json:
        items.append(
            ("vision", "observations_json", value.normalized_observations_json)
        )
    items.extend(
        (
            ("profile", value.style_profile, STYLE_PROFILES[value.style_profile]),
            ("profile", value.motion_profile, MOTION_PROFILES[value.motion_profile]),
            ("profile", value.camera_profile, CAMERA_PROFILES[value.camera_profile]),
        )
    )
    return [
        ProvenanceRecord(
            record_id=f"src_{index:04d}",
            record_kind="input",
            source=source,
            source_ref=source_ref,
            source_position=index - 1,
            target=None,
            disposition="supplied",
            reason="direct_input",
            sha256=sha256_text(text),
        )
        for index, (source, source_ref, text) in enumerate(items, 1)
    ]


def _discard_provenance(
    issues: list[LLMRecordIssue], start: int = 1
) -> list[ProvenanceRecord]:
    records = []
    for index, issue in enumerate(issues, start):
        if issue.reason == "empty_text":
            reason = "empty"
        else:
            reason = "invalid_line_record"
        records.append(
            ProvenanceRecord(
                record_id=f"drop_{index:04d}",
                record_kind="discard",
                source="generated",
                source_ref=f"response_line:{issue.line_number}",
                source_position=issue.line_number - 1,
                target=None,
                disposition="discarded",
                reason=reason,
                sha256=issue.raw_sha256,
            )
        )
    return records


def _retry_payload(
    original_payload: str, missing: tuple[tuple[str, int], ...]
) -> str:
    return canonical_json(
        {
            "protocol": "MVD_LLM_RECORDS_V1",
            "task": DIRECTION_PROMPT_VERSION,
            "retry": "missing_slots_only",
            "missing": [list(item) for item in missing],
            "original_input": json.loads(original_payload),
        }
    )


def _merge_records(
    first: tuple[LLMRecord, ...],
    retry: tuple[LLMRecord, ...],
    missing: tuple[tuple[str, int], ...],
) -> tuple[LLMRecord, ...]:
    required_retry = set(missing)
    accepted_retry = [
        record
        for record in retry
        if (record.record_type, record.slot) in required_retry
    ]
    return (*first, *accepted_retry)


def render_direction_emd_preview(direction: DirectionArtifact) -> str:
    direction.validate()
    sections = (
        ("スタイル", direction.style_direction),
        ("モーション", direction.motion_direction),
        ("カメラ", direction.camera_direction),
        ("その他", direction.other_direction),
    )
    lines = ["# 共通プロンプト"]
    for heading, values in sections:
        if values:
            lines.extend((f"## {heading}", *(f"* {item}" for item in values)))
    return "\n".join(lines) + "\n"


def enhance_direction(
    backend: DirectionEnhancerBackend,
    *,
    value: DirectionEnhancerInput,
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any = None,
) -> DirectionEnhancerResult:
    value.validate()
    runtime_config.validate()
    if not system_prompt.strip():
        raise DirectionEnhancerError("Direction system prompt is empty")
    payload = build_direction_payload(value)
    first_response = backend.complete_direction(
        system_prompt=system_prompt,
        payload=payload,
        config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    first = parse_llm_records(
        first_response, allowed_slots=_ALLOWED, required=_REQUIRED
    )
    all_issues = list(first.issues)
    retried_missing = first.missing
    retry_records: tuple[LLMRecord, ...] = ()
    remaining = first.missing
    if first.missing:
        retry_response = backend.complete_direction(
            system_prompt=system_prompt,
            payload=_retry_payload(payload, first.missing),
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        retry_result = parse_llm_records(
            retry_response,
            allowed_slots={
                record_type: frozenset({slot})
                for record_type, slot in first.missing
            },
            required=frozenset(first.missing),
        )
        all_issues.extend(retry_result.issues)
        retry_records = retry_result.records
        recovered = {
            (record.record_type, record.slot)
            for record in retry_records
            if (record.record_type, record.slot) in set(first.missing)
        }
        remaining = tuple(item for item in first.missing if item not in recovered)
    if remaining:
        labels = ", ".join(f"{kind}:{slot}" for kind, slot in remaining)
        raise DirectionEnhancerError(
            f"Direction Enhancer is missing required records after one retry: {labels}"
        )

    records = _merge_records(first.records, retry_records, first.missing)
    values: dict[str, list[str]] = {
        "style_direction": [],
        "motion_direction": [],
        "camera_direction": [],
        "other_direction": [],
    }
    provenance = _input_provenance(value)
    provenance.extend(_discard_provenance(all_issues))
    output_counts = {field: 0 for field in values}
    for record in records:
        field = _FIELD_BY_TYPE[record.record_type]
        if values[field]:
            continue
        target_index = len(values[field])
        values[field].append(record.text)
        output_counts[field] += 1
        provenance.append(
            ProvenanceRecord(
                record_id=f"out_{record.record_type.casefold()}_{output_counts[field]:04d}",
                record_kind="output",
                source="generated",
                source_ref=f"{record.record_type}:{record.slot}",
                source_position=record.line_number - 1,
                target=f"{field}[{target_index}]",
                disposition="accepted",
                reason="valid_line_record",
                sha256=sha256_text(record.text),
            )
        )
    direction = DirectionArtifact(
        style_direction=tuple(values["style_direction"]),
        motion_direction=tuple(values["motion_direction"]),
        camera_direction=tuple(values["camera_direction"]),
        other_direction=tuple(values["other_direction"]),
        provenance=tuple(provenance),
    )
    direction.validate()
    return DirectionEnhancerResult(
        direction=direction,
        direction_emd_preview=render_direction_emd_preview(direction),
        issues=tuple(all_issues),
        retried_missing=retried_missing,
    )
