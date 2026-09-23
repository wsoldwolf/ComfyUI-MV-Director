"""One-pass Direction Enhancer using MVD_LLM_RECORDS_V1."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from ..artifacts import (
    DirectionArtifact,
    ProvenanceRecord,
    canonical_json,
    normalize_newlines,
    sha256_text,
)
from ..emd import parse_scene_emd_fragment, render_scene_emd_fragment
from ..inference import LlamaRuntimeConfig
from ..protocols import LLMRecord, LLMRecordIssue, parse_llm_records
from .profiles import (
    CAMERA_PROFILES,
    LOCKED_STYLE_PROFILES,
    MOTION_PROFILES,
    STYLE_PROFILES,
)
from .passthrough import DirectionPassthrough, parse_direction_passthrough


DIRECTION_PROMPT_VERSION = "mvd-direction-enhancer-v25-user-emd-priority"
PASSTHROUGH_PROFILE = "passthrough"
RETENTION_POLICIES = ("profile", "compiler_default", "passthrough")
_MAX_STAGING_CANDIDATES = 12
_MAX_STAGING_CANDIDATE_CHARS = 500
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


def split_staging_directives(user_request: str) -> tuple[str, tuple[str, ...]]:
    """Keep plan-only EMD directives out of the global Direction prompt.

    This only parses line structure. The Planner LLM judges scene relevance;
    Python does not select a lyric, object, action, or preferred candidate.
    """

    lines: list[str] = []
    candidates: list[str] = []
    in_staging_section = False
    saw_staging_section = False

    def add_candidate(candidate: str, line_number: int) -> None:
        candidate = candidate.strip()
        if not candidate or "｜" in candidate:
            raise DirectionEnhancerError(
                f"user_request line {line_number}: invalid 演出候補"
            )
        if len(candidate) > _MAX_STAGING_CANDIDATE_CHARS:
            raise DirectionEnhancerError(
                f"user_request line {line_number}: 演出候補 exceeds "
                f"{_MAX_STAGING_CANDIDATE_CHARS} characters"
            )
        candidates.append(candidate)
        if len(candidates) > _MAX_STAGING_CANDIDATES:
            raise DirectionEnhancerError(
                f"user_request has more than {_MAX_STAGING_CANDIDATES} 演出候補"
            )

    for line_number, line in enumerate(normalize_newlines(user_request).split("\n"), 1):
        stripped = line.strip()
        if stripped == "# 演出候補":
            if saw_staging_section:
                raise DirectionEnhancerError(
                    f"user_request line {line_number}: duplicate # 演出候補"
                )
            saw_staging_section = True
            in_staging_section = True
            continue
        if stripped.startswith("# "):
            in_staging_section = False
        if stripped.startswith("* `演出候補`"):
            raise DirectionEnhancerError(
                f"user_request line {line_number}: use # 演出候補 with plain list items"
            )
        if in_staging_section:
            if not stripped:
                continue
            if not stripped.startswith("* "):
                raise DirectionEnhancerError(
                    f"user_request line {line_number}: # 演出候補 requires list items"
                )
            add_candidate(stripped[2:], line_number)
            continue
        lines.append(line)
    if saw_staging_section and not candidates:
        raise DirectionEnhancerError("# 演出候補 requires at least one list item")
    return "\n".join(lines).strip(), tuple(candidates)


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
    scene_emd: str = ""
    user_request: str = ""
    style_profile: str = "anime_emotional_mv"
    motion_profile: str = "anime_emotional_mv"
    camera_profile: str = "anime_emotional_mv"
    retention_policy: str = "profile"
    direction_emd_passthrough: str = ""

    def validate(self) -> None:
        for name in (
            "concept_emd",
            "scene_emd",
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
        split_staging_directives(self.normalized_user_request)
        concept = self.normalized_concept_emd
        if concept:
            headings = [line for line in concept.split("\n") if line.startswith("# ")]
            if headings != ["# サブジェクト"]:
                raise DirectionEnhancerError(
                    "concept_emd must be one # サブジェクト fragment"
                )
        if self.normalized_scene_emd:
            try:
                parse_scene_emd_fragment(self.normalized_scene_emd)
            except ValueError as exc:
                raise DirectionEnhancerError(f"invalid scene_emd: {exc}") from exc
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
    def normalized_scene_emd(self) -> str:
        normalized = normalize_newlines(self.scene_emd).strip()
        if not normalized:
            return ""
        return render_scene_emd_fragment(parse_scene_emd_fragment(normalized)).strip()

    @property
    def normalized_user_request(self) -> str:
        return normalize_newlines(self.user_request).strip()

    @property
    def user_direction_text(self) -> str:
        return split_staging_directives(self.normalized_user_request)[0]

    @property
    def staging_candidates(self) -> tuple[str, ...]:
        return split_staging_directives(self.normalized_user_request)[1]

    @property
    def normalized_direction_emd_passthrough(self) -> str:
        return normalize_newlines(self.direction_emd_passthrough).strip()

    @property
    def passthrough(self) -> DirectionPassthrough:
        from_socket = parse_direction_passthrough(
            self.normalized_direction_emd_passthrough,
            concept_emd=self.normalized_concept_emd,
        )
        from_request = self.user_common
        fields = (
            "style", "environment", "time_lighting",
            "motion", "camera", "other",
        )
        overlapping = [
            field for field in fields
            if getattr(from_socket, field) and getattr(from_request, field)
        ]
        if overlapping:
            raise DirectionEnhancerError(
                "same user EMD subsection is defined in user_request and "
                "direction_emd_passthrough: " + ",".join(overlapping)
            )
        return DirectionPassthrough(
            retention=from_socket.retention,
            **{
                field: getattr(from_request, field) or getattr(from_socket, field)
                for field in fields
            },
        )

    @property
    def user_common(self) -> DirectionPassthrough:
        text = self.user_direction_text
        if not text.startswith("# 共通プロンプト\n## "):
            return DirectionPassthrough()
        return parse_direction_passthrough(text)

    def effective_profile(self, kind: str) -> str:
        if getattr(self.passthrough, kind):
            return PASSTHROUGH_PROFILE
        return getattr(self, f"{kind}_profile")

    @property
    def requested_record_types(self) -> tuple[str, ...]:
        if (
            not self.passthrough.style
            and self.style_profile != PASSTHROUGH_PROFILE
            and self.style_profile not in LOCKED_STYLE_PROFILES
        ):
            return ("STYLE",)
        return ()

    @property
    def requires_inference(self) -> bool:
        return any(
            self.effective_profile(kind) != PASSTHROUGH_PROFILE
            for kind in ("style", "motion", "camera")
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
        "authority_order": ["user", "scene_emd", "vision_concept", "profile", "generated"],
        "user_request": value.user_direction_text,
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
    if value.normalized_scene_emd:
        setting = parse_scene_emd_fragment(value.normalized_scene_emd)
        payload["scene_context"] = {
            "environment": list(setting.environment),
            "time_lighting": list(setting.time_lighting),
            "background_picture": setting.picture_ref or "",
            "authority": (
                "Observed baseline only. Explicit user direction overrides its "
                "time, lighting, weather, season, and staging."
            ),
        }
    profiles = payload["profiles"]
    if value.effective_profile("style") != PASSTHROUGH_PROFILE:
        profiles["style"] = {
            "id": value.style_profile,
            "text": STYLE_PROFILES[value.style_profile],
            "locked": value.style_profile in LOCKED_STYLE_PROFILES,
        }
    if value.effective_profile("motion") != PASSTHROUGH_PROFILE:
        profiles["motion"] = {
            "id": value.motion_profile,
            "text": MOTION_PROFILES[value.motion_profile],
        }
    if value.effective_profile("camera") != PASSTHROUGH_PROFILE:
        profiles["camera"] = {
            "id": value.camera_profile,
            "text": CAMERA_PROFILES[value.camera_profile],
        }
    return canonical_json(payload)


def _input_provenance(value: DirectionEnhancerInput) -> list[ProvenanceRecord]:
    items: list[tuple[str, str, str]] = []
    if value.normalized_user_request:
        items.append(("user", "user_request", value.normalized_user_request))
    if value.normalized_concept_emd:
        items.append(("vision", "concept_emd", value.normalized_concept_emd))
    if value.normalized_scene_emd:
        items.append(("vision", "scene_emd", value.normalized_scene_emd))
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
    for kind, field in (
        ("style", "style_direction"),
        ("motion", "motion_direction"),
        ("camera", "camera_direction"),
    ):
        profile_id = getattr(value, f"{kind}_profile")
        if profile_id != PASSTHROUGH_PROFILE and getattr(passthrough, kind):
            source = {
                "style": STYLE_PROFILES,
                "motion": MOTION_PROFILES,
                "camera": CAMERA_PROFILES,
            }[kind][profile_id]
            provenance.append(
                ProvenanceRecord(
                    record_id=f"drop_profile_{kind}",
                    record_kind="discard",
                    source="profile",
                    source_ref=profile_id,
                    source_position=0,
                    target=None,
                    disposition="discarded",
                    reason="profile_overridden",
                    sha256=sha256_text(source),
                )
            )
    output_counts = {field: 0 for field in values}
    for field, passthrough_values in (
        ("style_direction", passthrough.style),
        ("environment_direction", passthrough.environment),
        ("time_lighting_direction", passthrough.time_lighting),
        ("motion_direction", passthrough.motion),
        ("camera_direction", passthrough.camera),
        ("other_direction", passthrough.other),
    ):
        kind = field.removesuffix("_direction")
        source_ref = (
            "user_request"
            if getattr(value.user_common, kind)
            else "direction_emd_passthrough"
        )
        for index, text in enumerate(passthrough_values):
            output_counts[field] += 1
            provenance.append(
                ProvenanceRecord(
                    record_id=f"out_{field}_{output_counts[field]:04d}",
                    record_kind="output",
                    source="user",
                    source_ref=source_ref,
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
    for index, text in enumerate(value.staging_candidates):
        provenance.append(
            ProvenanceRecord(
                record_id=f"out_staging_{index + 1:04d}",
                record_kind="output",
                source="user",
                source_ref="user_request",
                source_position=index,
                target=f"staging_candidates[{index}]",
                disposition="accepted",
                reason="planning_directive",
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
        style_profile_id=value.effective_profile("style"),
        motion_profile_id=value.effective_profile("motion"),
        motion_policy_profile_id=(
            value.motion_profile
            if passthrough.motion and value.motion_profile != PASSTHROUGH_PROFILE
            else ""
        ),
        camera_profile_id=value.effective_profile("camera"),
        retention_policy=value.retention_policy,
        retention_lines=passthrough.retention,
        staging_candidates=value.staging_candidates,
        provenance=tuple(provenance),
    )
    direction.validate()
    return DirectionEnhancerResult(
        direction=direction,
        direction_emd_preview=render_direction_emd_preview(direction),
        issues=tuple(all_issues),
        retried_missing=retried_missing,
    )
