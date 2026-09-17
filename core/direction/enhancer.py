"""One-pass Direction Enhancer using MVD_LLM_RECORDS_V1."""

from __future__ import annotations

import json
import re
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
from .profiles import (
    CAMERA_PROFILES,
    LOCKED_STYLE_PROFILES,
    MOTION_PROFILES,
    STYLE_PROFILES,
)
from .passthrough import DirectionPassthrough, parse_direction_passthrough


DIRECTION_PROMPT_VERSION = "mvd-direction-enhancer-v18"
PASSTHROUGH_PROFILE = "passthrough"
RETENTION_POLICIES = ("profile", "compiler_default", "passthrough")
_ALLOWED = {
    "STYLE": frozenset({1}),
    "ENVIRONMENT": frozenset({1}),
    "TIME_LIGHTING": frozenset({1}),
    "MOTION": frozenset({1}),
    "CAMERA": frozenset({1}),
    "OTHER": frozenset({1}),
}
_FIELD_BY_TYPE = {
    "STYLE": "style_direction",
    "ENVIRONMENT": "environment_direction",
    "TIME_LIGHTING": "time_lighting_direction",
    "MOTION": "motion_direction",
    "CAMERA": "camera_direction",
    "OTHER": "other_direction",
}
_DIRECTION_RECORD_TYPES = tuple(_ALLOWED)


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
    retention_policy: str = "profile"
    direction_emd_passthrough: str = ""

    def validate(self) -> None:
        for name in (
            "concept_emd",
            "observations_json",
            "user_request",
            "direction_emd_passthrough",
        ):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise DirectionEnhancerError(f"{name} must be a string")
            if "\x00" in value:
                raise DirectionEnhancerError(f"{name} contains NUL")
        if self.style_profile not in {*STYLE_PROFILES, PASSTHROUGH_PROFILE}:
            raise DirectionEnhancerError("unknown style_profile")
        if self.motion_profile not in {*MOTION_PROFILES, PASSTHROUGH_PROFILE}:
            raise DirectionEnhancerError("unknown motion_profile")
        if self.camera_profile not in {*CAMERA_PROFILES, PASSTHROUGH_PROFILE}:
            raise DirectionEnhancerError("unknown camera_profile")
        if self.retention_policy not in RETENTION_POLICIES:
            raise DirectionEnhancerError("unknown retention_policy")
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
        passthrough = self.passthrough
        selected = {
            "style": self.style_profile == PASSTHROUGH_PROFILE,
            "motion": self.motion_profile == PASSTHROUGH_PROFILE,
            "camera": self.camera_profile == PASSTHROUGH_PROFILE,
        }
        for name, enabled in selected.items():
            values = getattr(passthrough, name)
            if enabled and not values:
                raise DirectionEnhancerError(
                    f"{name}_profile=passthrough requires ## {_PASSTHROUGH_HEADING[name]}"
                )
            if values and not enabled:
                raise DirectionEnhancerError(
                    f"## {_PASSTHROUGH_HEADING[name]} requires {name}_profile=passthrough"
                )
        if self.retention_policy == "passthrough" and not passthrough.retention:
            raise DirectionEnhancerError(
                "retention_policy=passthrough requires # 保持分析"
            )
        if passthrough.retention and self.retention_policy != "passthrough":
            raise DirectionEnhancerError(
                "# 保持分析 requires retention_policy=passthrough"
            )

    @property
    def normalized_concept_emd(self) -> str:
        return normalize_newlines(self.concept_emd).strip()

    @property
    def normalized_observations_json(self) -> str:
        return normalize_newlines(self.observations_json).strip()

    @property
    def normalized_user_request(self) -> str:
        return normalize_newlines(self.user_request).strip()

    @property
    def normalized_direction_emd_passthrough(self) -> str:
        return normalize_newlines(self.direction_emd_passthrough).strip()

    @property
    def passthrough(self) -> DirectionPassthrough:
        return parse_direction_passthrough(
            self.normalized_direction_emd_passthrough,
            concept_emd=self.normalized_concept_emd,
        )

    @property
    def requested_record_types(self) -> tuple[str, ...]:
        if (
            self.style_profile != PASSTHROUGH_PROFILE
            and self.style_profile not in LOCKED_STYLE_PROFILES
        ):
            return ("STYLE",)
        return ()

    @property
    def requires_inference(self) -> bool:
        return any(
            profile != PASSTHROUGH_PROFILE
            for profile in (
                self.style_profile,
                self.motion_profile,
                self.camera_profile,
            )
        )


_PASSTHROUGH_HEADING = {
    "style": "スタイル",
    "motion": "モーション",
    "camera": "カメラ",
}


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
        "requested_records": list(value.requested_record_types),
        "profiles": {},
        "passthrough_context": {
            "style": list(value.passthrough.style),
            "environment": list(value.passthrough.environment),
            "time_lighting": list(value.passthrough.time_lighting),
            "motion": list(value.passthrough.motion),
            "camera": list(value.passthrough.camera),
            "other": list(value.passthrough.other),
        },
    }
    profiles = payload["profiles"]
    if value.style_profile != PASSTHROUGH_PROFILE:
        profiles["style"] = {
            "id": value.style_profile,
            "text": STYLE_PROFILES[value.style_profile],
            "locked": value.style_profile in LOCKED_STYLE_PROFILES,
        }
    if value.motion_profile != PASSTHROUGH_PROFILE:
        profiles["motion"] = {
            "id": value.motion_profile,
            "text": MOTION_PROFILES[value.motion_profile],
        }
    if value.camera_profile != PASSTHROUGH_PROFILE:
        profiles["camera"] = {
            "id": value.camera_profile,
            "text": CAMERA_PROFILES[value.camera_profile],
        }
    if value.normalized_observations_json:
        observations = ObservationsArtifact.from_dict(
            json.loads(value.normalized_observations_json)
        )
        # Direction may use the photographed place and ambient conditions, but
        # never the reference-sheet pose or composition. Passing the complete
        # observation made small models promote a presentation pose into a
        # whole-video direction, which then forced every Scene to repeat it.
        payload["vision_scene_context"] = {
            "setting": observations.scene_setting,
            "elements": list(observations.scene_elements),
            "lighting": observations.lighting,
            "time_weather": observations.time_weather,
        }
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
    for profile_id, profiles in (
        (value.style_profile, STYLE_PROFILES),
        (value.motion_profile, MOTION_PROFILES),
        (value.camera_profile, CAMERA_PROFILES),
    ):
        if profile_id != PASSTHROUGH_PROFILE:
            items.append(("profile", profile_id, profiles[profile_id]))
    if value.normalized_direction_emd_passthrough:
        items.append(
            (
                "user",
                "direction_emd_passthrough",
                value.normalized_direction_emd_passthrough,
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


def _normalize_small_model_response(response: str) -> str:
    """Normalize two observed Qwen3-4B formatting slips for this task only."""

    normalized = normalize_newlines(response)
    for record_type in _DIRECTION_RECORD_TYPES:
        normalized = re.sub(
            rf"\t{record_type}\t([0-9]+)\t",
            rf"\n{record_type}\t\1\t",
            normalized,
        )
    lines = []
    record_pattern = re.compile(
        rf"^({'|'.join(_DIRECTION_RECORD_TYPES)})\t[0-9]+\t"
    )
    for line in normalized.split("\n"):
        if line.strip() in {"<think>", "</think>"}:
            continue
        lines.append(record_pattern.sub(r"\1\t1\t", line, count=1))
    return "\n".join(lines)


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
        ("環境", direction.environment_direction),
        ("時間・照明", direction.time_lighting_direction),
        ("モーション", direction.motion_direction),
        ("カメラ", direction.camera_direction),
        ("その他", direction.other_direction),
    )
    lines: list[str] = []
    if direction.retention_lines:
        lines.extend(
            ("# 保持分析", *(f"* {item}" for item in direction.retention_lines))
        )
    if any(values for _, values in sections):
        if lines:
            lines.append("")
        lines.append("# 共通プロンプト")
    for heading, values in sections:
        if values:
            lines.extend((f"## {heading}", *(f"* {item}" for item in values)))
    return "\n".join(lines) + ("\n" if lines else "")


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
    if value.requires_inference and not system_prompt.strip():
        raise DirectionEnhancerError("Direction system prompt is empty")
    payload = build_direction_payload(value)
    passthrough = value.passthrough
    requested = value.requested_record_types
    required = frozenset((record_type, 1) for record_type in requested)
    allowed_types = set(requested)
    if not passthrough.environment:
        allowed_types.add("ENVIRONMENT")
    if not passthrough.time_lighting:
        allowed_types.add("TIME_LIGHTING")
    if not passthrough.other:
        allowed_types.add("OTHER")
    allowed = {
        record_type: _ALLOWED[record_type]
        for record_type in _DIRECTION_RECORD_TYPES
        if record_type in allowed_types
    }
    first_records: tuple[LLMRecord, ...] = ()
    all_issues: list[LLMRecordIssue] = []
    retried_missing: tuple[tuple[str, int], ...] = ()
    remaining: tuple[tuple[str, int], ...] = ()
    if value.requires_inference:
        first_response = backend.complete_direction(
            system_prompt=system_prompt,
            payload=payload,
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        first = parse_llm_records(
            _normalize_small_model_response(first_response),
            allowed_slots=allowed,
            required=required,
        )
        first_records = first.records
        all_issues.extend(first.issues)
        retried_missing = first.missing
        remaining = first.missing
    retry_records: tuple[LLMRecord, ...] = ()
    if retried_missing:
        retry_response = backend.complete_direction(
            system_prompt=system_prompt,
            payload=_retry_payload(payload, retried_missing),
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        retry_result = parse_llm_records(
            _normalize_small_model_response(retry_response),
            allowed_slots={
                record_type: frozenset({slot})
                for record_type, slot in retried_missing
            },
            required=frozenset(retried_missing),
        )
        all_issues.extend(retry_result.issues)
        retry_records = retry_result.records
        recovered = {
            (record.record_type, record.slot)
            for record in retry_records
            if (record.record_type, record.slot) in set(retried_missing)
        }
        remaining = tuple(item for item in retried_missing if item not in recovered)
    if remaining:
        labels = ", ".join(f"{kind}:{slot}" for kind, slot in remaining)
        raise DirectionEnhancerError(
            f"Direction Enhancer is missing required records after one retry: {labels}"
        )

    records = _merge_records(first_records, retry_records, retried_missing)
    values: dict[str, list[str]] = {
        "style_direction": list(passthrough.style),
        "environment_direction": list(passthrough.environment),
        "time_lighting_direction": list(passthrough.time_lighting),
        "motion_direction": list(passthrough.motion),
        "camera_direction": list(passthrough.camera),
        "other_direction": list(passthrough.other),
    }
    profile_owned: dict[str, tuple[str, str]] = {}
    if (
        not values["style_direction"]
        and value.style_profile in LOCKED_STYLE_PROFILES
    ):
        profile_owned["style_direction"] = (
            value.style_profile,
            STYLE_PROFILES[value.style_profile],
        )
    if (
        not values["motion_direction"]
        and value.motion_profile != PASSTHROUGH_PROFILE
    ):
        profile_owned["motion_direction"] = (
            value.motion_profile,
            MOTION_PROFILES[value.motion_profile],
        )
    if (
        not values["camera_direction"]
        and value.camera_profile != PASSTHROUGH_PROFILE
    ):
        profile_owned["camera_direction"] = (
            value.camera_profile,
            CAMERA_PROFILES[value.camera_profile],
        )
    for field, (_, text) in profile_owned.items():
        values[field].append(text)
    provenance = _input_provenance(value)
    provenance.extend(_discard_provenance(all_issues))
    output_counts = {field: 0 for field in values}
    for field, passthrough_values in (
        ("style_direction", passthrough.style),
        ("environment_direction", passthrough.environment),
        ("time_lighting_direction", passthrough.time_lighting),
        ("motion_direction", passthrough.motion),
        ("camera_direction", passthrough.camera),
        ("other_direction", passthrough.other),
    ):
        for index, text in enumerate(passthrough_values):
            output_counts[field] += 1
            provenance.append(
                ProvenanceRecord(
                    record_id=f"out_{field}_{output_counts[field]:04d}",
                    record_kind="output",
                    source="user",
                    source_ref="direction_emd_passthrough",
                    source_position=index,
                    target=f"{field}[{index}]",
                    disposition="accepted",
                    reason="passthrough_enforced",
                    sha256=sha256_text(text),
                )
            )
    for field, (profile_id, text) in profile_owned.items():
        output_counts[field] += 1
        provenance.append(
            ProvenanceRecord(
                record_id=f"out_{field}_{output_counts[field]:04d}",
                record_kind="output",
                source="profile",
                source_ref=profile_id,
                source_position=0,
                target=f"{field}[0]",
                disposition="accepted",
                reason="profile_enforced",
                sha256=sha256_text(text),
            )
        )
    for record in records:
        field = _FIELD_BY_TYPE[record.record_type]
        if values[field]:
            continue
        output_text = record.text
        output_source = "generated"
        output_source_ref = f"{record.record_type}:{record.slot}"
        output_reason = "valid_line_record"
        target_index = len(values[field])
        values[field].append(output_text)
        output_counts[field] += 1
        provenance.append(
            ProvenanceRecord(
                record_id=f"out_{record.record_type.casefold()}_{output_counts[field]:04d}",
                record_kind="output",
                source=output_source,
                source_ref=output_source_ref,
                source_position=record.line_number - 1,
                target=f"{field}[{target_index}]",
                disposition="accepted",
                reason=output_reason,
                sha256=sha256_text(output_text),
            )
        )
    for index, text in enumerate(passthrough.retention):
        provenance.append(
            ProvenanceRecord(
                record_id=f"out_retention_{index + 1:04d}",
                record_kind="output",
                source="user",
                source_ref="direction_emd_passthrough",
                source_position=index,
                target=f"retention_lines[{index}]",
                disposition="accepted",
                reason="passthrough_enforced",
                sha256=sha256_text(text),
            )
        )
    direction = DirectionArtifact(
        style_direction=tuple(values["style_direction"]),
        environment_direction=tuple(values["environment_direction"]),
        time_lighting_direction=tuple(values["time_lighting_direction"]),
        motion_direction=tuple(values["motion_direction"]),
        camera_direction=tuple(values["camera_direction"]),
        other_direction=tuple(values["other_direction"]),
        style_profile_id=value.style_profile,
        motion_profile_id=value.motion_profile,
        camera_profile_id=value.camera_profile,
        retention_policy=value.retention_policy,
        retention_lines=passthrough.retention,
        provenance=tuple(provenance),
    )
    direction.validate()
    return DirectionEnhancerResult(
        direction=direction,
        direction_emd_preview=render_direction_emd_preview(direction),
        issues=tuple(all_issues),
        retried_missing=retried_missing,
    )
