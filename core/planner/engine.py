"""Finite multi-task Timeline Planner orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import re
from typing import Any, Mapping, Protocol

from ..artifacts import DirectionArtifact, EMDTextArtifact, canonical_json, normalize_newlines
from ..direction.profiles import CAMERA_PLANNER_POLICIES
from ..emd import parse_scene_emd_fragment
from ..h3_contract import (
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
    FACE_PERFORMANCE_CUT_ACTION,
    FACE_PERFORMANCE_CUT_CAMERA,
)
from ..inference import LlamaRuntimeConfig
from ..protocols import LLMRecordIssue, parse_llm_records
from .dialogue import DialogueFilter, DialogueProtector
from .errors import TimelinePlannerError
from .layout import (
    apply_scene_continuations,
    apply_shot_layouts,
    build_layout_candidates,
    parse_scene_layout_selection,
    repair_scene_layout_selection,
)
from .renderer import render_completed_emd
from .template import (
    PlannerTemplate,
    normalize_concept_emd,
    normalize_scene_emd,
    parse_template_emd,
)


PLANNER_ALGORITHM_VERSION = "mvd-timeline-planner-v37"
TASKS = ("visual-beats", "song-direction", "shot-layout", "actions", "cameras")
_CAMERA_MOTION_TYPES = (
    "Roll Counterclockwise",
    "Roll Clockwise",
    "Shake Slightly",
    "Shake Strongly",
    "Pedestal Down",
    "Pedestal Up",
    "Tracking Shot",
    "Static Shot",
    "Arc Shot",
    "Truck Right",
    "Truck Left",
    "Push In",
    "Pull Out",
    "Zoom In",
    "Zoom Out",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "POV",
)
_LOWER_BODY_DETAIL_RE = re.compile(
    r"足元|足先|左足|右足|両足|足袋|履物|下駄|草履|toe|foot|feet|footwear",
    re.IGNORECASE,
)
_SLOW_CAMERA_RE = re.compile(r"at slow speed|ゆっくり|緩やか", re.IGNORECASE)
_LARGE_FAST_ARC_RE = re.compile(
    r"^Arc Shot\s+with large amplitude\s+at fast speed\b",
    re.IGNORECASE,
)
_SLOW_ACTION_RE = re.compile(
    r"ゆっくり|緩やか|そっと|静かに|徐々に|slowly|gently|gradually",
    re.IGNORECASE,
)
_GENERIC_HAND_ACTION_RE = re.compile(
    r"(?:両手|片手|手|腕)(?:を|が)?"
    r"(?:(?:ゆっくり|そっと|静かに)\s*)?"
    r"(?:上げ(?:る|た|ている)?|下げ(?:る|た|ている)?|上下(?:させる|する)?)。?$",
    re.IGNORECASE,
)
_RUNNING_ACTION_RE = re.compile(
    r"走(?:る|り|った|って)|駆け(?:る|出す|抜ける|寄る)?|疾走|全力疾走|"
    r"\brun(?:ning|s)?\b|\bsprint(?:ing|s)?\b",
    re.IGNORECASE,
)


class TimelinePlannerBackend(Protocol):
    def complete_planner(
        self,
        *,
        task: str,
        system_prompt: str,
        payload: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> str:
        ...


@dataclass(frozen=True, slots=True)
class PlannerContent:
    visual_beats: tuple[tuple[int, str], ...]
    song_direction: str
    shot_layouts: tuple[tuple[int, tuple[int, ...]], ...]
    actions: tuple[tuple[int, int, str], ...]
    cameras: tuple[tuple[int, int, str], ...]
    issue_count: int
    retried_scenes: tuple[int, ...]
    removed_generated_dialogue_count: int
    unused_protected_dialogue_ids: tuple[str, ...]
    scene_continuations: tuple[tuple[int, bool], ...] = ()
    layout_repaired_scenes: tuple[int, ...] = ()
    layout_fallback_scenes: tuple[int, ...] = ()
    layout_mix_retry: bool = False
    protocol_recovered_count: int = 0
    repetition_warning_count: int = 0
    beat_repetition_warning_count: int = 0
    action_repetition_warning_count: int = 0
    camera_repetition_warning_count: int = 0
    song_direction_fallback: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "visual_beats": [list(value) for value in self.visual_beats],
            "song_direction": self.song_direction,
            "shot_layouts": [
                [scene, list(starts)] for scene, starts in self.shot_layouts
            ],
            "scene_continuations": [
                [scene, continuation]
                for scene, continuation in self.scene_continuations
            ],
            "actions": [list(value) for value in self.actions],
            "cameras": [list(value) for value in self.cameras],
            "issue_count": self.issue_count,
            "retried_scenes": list(self.retried_scenes),
            "removed_generated_dialogue_count": self.removed_generated_dialogue_count,
            "unused_protected_dialogue_ids": list(self.unused_protected_dialogue_ids),
            "layout_repaired_scenes": list(self.layout_repaired_scenes),
            "layout_fallback_scenes": list(self.layout_fallback_scenes),
            "layout_mix_retry": self.layout_mix_retry,
            "protocol_recovered_count": self.protocol_recovered_count,
            "repetition_warning_count": self.repetition_warning_count,
            "beat_repetition_warning_count": self.beat_repetition_warning_count,
            "action_repetition_warning_count": self.action_repetition_warning_count,
            "camera_repetition_warning_count": self.camera_repetition_warning_count,
            "song_direction_fallback": self.song_direction_fallback,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannerContent":
        return cls(
            visual_beats=tuple(
                (int(row[0]), str(row[1])) for row in value["visual_beats"]
            ),
            song_direction=str(value["song_direction"]),
            shot_layouts=tuple(
                (int(row[0]), tuple(int(item) for item in row[1]))
                for row in value["shot_layouts"]
            ),
            scene_continuations=tuple(
                (int(row[0]), bool(row[1]))
                for row in value.get("scene_continuations", ())
            ),
            actions=tuple((int(row[0]), int(row[1]), str(row[2])) for row in value["actions"]),
            cameras=tuple((int(row[0]), int(row[1]), str(row[2])) for row in value["cameras"]),
            issue_count=int(value["issue_count"]),
            retried_scenes=tuple(int(item) for item in value["retried_scenes"]),
            removed_generated_dialogue_count=int(value["removed_generated_dialogue_count"]),
            unused_protected_dialogue_ids=tuple(str(item) for item in value["unused_protected_dialogue_ids"]),
            layout_repaired_scenes=tuple(
                int(item) for item in value.get("layout_repaired_scenes", ())
            ),
            layout_fallback_scenes=tuple(
                int(item) for item in value["layout_fallback_scenes"]
            ),
            layout_mix_retry=bool(value.get("layout_mix_retry", False)),
            protocol_recovered_count=int(
                value.get("protocol_recovered_count", 0)
            ),
            repetition_warning_count=int(
                value.get("repetition_warning_count", 0)
            ),
            beat_repetition_warning_count=int(
                value.get("beat_repetition_warning_count", 0)
            ),
            action_repetition_warning_count=int(
                value.get("action_repetition_warning_count", 0)
            ),
            camera_repetition_warning_count=int(
                value.get("camera_repetition_warning_count", 0)
            ),
            song_direction_fallback=bool(
                value.get("song_direction_fallback", False)
            ),
        )


@dataclass(frozen=True, slots=True)
class TimelinePlannerResult:
    emd: EMDTextArtifact
    content: PlannerContent | None
    complete: bool
    missing: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class _Entity:
    scene_number: int
    key: tuple[int, ...]
    value: dict[str, object]


def _chunks(values: list[Any], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _normalize_small_model_response(response: str, record_type: str) -> str:
    """Normalize observed Qwen3-4B protocol spelling without changing slots."""

    normalized = normalize_newlines(response)
    normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.DOTALL)
    labelled_slot_line = re.compile(
        rf"^{re.escape(record_type)}\t(?:TAB\t)?slot\s*([0-9]+)\t(?:TAB\t)?(.+)$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    normalized = labelled_slot_line.sub(
        lambda match: f"{record_type}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    labelled_tab_line = re.compile(
        r"^[^\n\t]*\tTAB\t([0-9]+)\tTAB\t(.+)$",
        flags=re.MULTILINE,
    )
    normalized = labelled_tab_line.sub(
        lambda match: f"{record_type}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    literal_marker = re.compile(
        rf"(^|<TAB>){re.escape(record_type)}<TAB>([0-9]+)<TAB>",
        flags=re.MULTILINE,
    )
    normalized = literal_marker.sub(
        lambda match: (
            ("" if match.group(1) == "" else "\n")
            + f"{record_type}\t{match.group(2)}\t"
        ),
        normalized,
    )
    normalized = re.sub(
        rf"\t{re.escape(record_type)}\t([0-9]+)\t",
        rf"\n{record_type}\t\1\t",
        normalized,
    )
    return normalized


def _recover_unframed_records(
    response: str,
    record_type: str,
    expected_slots: list[int],
    *,
    allow_single_positional: bool = False,
) -> dict[int, str]:
    """Recover only unambiguous line wrappers while preserving TEXT AS IS."""

    if not expected_slots:
        return {}
    normalized = normalize_newlines(response)
    normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.DOTALL)
    lines = [
        line.strip()
        for line in normalized.split("\n")
        if line.strip() and not line.strip().startswith("```")
    ]
    expected = set(expected_slots)
    labelled = re.compile(
        rf"^(?:[-*]\s*)?(?:{re.escape(record_type)}\s*)?"
        r"(?:slot\s*)?([0-9]+)\s*(?:\t+|[:：.)]\s*|[-–—]\s+|\s+)"
        r"(.+)$",
        flags=re.IGNORECASE,
    )
    recovered: dict[int, str] = {}
    for line in lines:
        match = labelled.fullmatch(line)
        if not match:
            continue
        slot = int(match.group(1))
        text = match.group(2).strip()
        if slot in expected and slot not in recovered and text:
            recovered[slot] = text
    if recovered:
        return recovered

    # Isolated retries have a unique side-table mapping.  Small models often
    # wrap that single record in JSON, a Markdown table, or slot/text labels
    # even when instructed to emit TSV.  Accept only wrappers that identify
    # one unambiguous text value; never synthesize or rewrite the value.
    if allow_single_positional and len(expected_slots) == 1:
        expected_slot = expected_slots[0]

        json_candidates: list[str] = []
        json_text = normalized.strip()
        if json_text.startswith("```") and json_text.endswith("```"):
            json_text = re.sub(r"^```(?:json)?\s*", "", json_text)
            json_text = re.sub(r"\s*```$", "", json_text)
        try:
            decoded = json.loads(json_text)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        objects = decoded if isinstance(decoded, list) else [decoded]
        for item in objects:
            if not isinstance(item, dict):
                continue
            item_type = item.get("record_type", item.get("type", record_type))
            item_slot = item.get("slot", expected_slot)
            item_text = item.get("text")
            if (
                str(item_type).upper() == record_type.upper()
                and str(item_slot).isascii()
                and str(item_slot).isdecimal()
                and int(item_slot) == expected_slot
                and isinstance(item_text, str)
                and item_text.strip()
            ):
                json_candidates.append(item_text.strip())
        if len(json_candidates) == 1:
            return {expected_slot: json_candidates[0]}

        pipe_candidates: list[str] = []
        pipe_line = re.compile(
            rf"^\|?\s*{re.escape(record_type)}\s*\|\s*"
            rf"{expected_slot}\s*\|\s*(.+?)\s*\|?$",
            flags=re.IGNORECASE,
        )
        for line in lines:
            match = pipe_line.fullmatch(line)
            if match and match.group(1).strip():
                pipe_candidates.append(match.group(1).strip())
        if len(pipe_candidates) == 1:
            return {expected_slot: pipe_candidates[0]}

        labelled_texts: list[str] = []
        labelled_slots: list[int] = []
        labelled_types: list[str] = []
        for line in lines:
            field = re.fullmatch(
                r"(?:[-*]\s*)?(record_type|type|slot|text)\s*[:：]\s*(.+)",
                line,
                flags=re.IGNORECASE,
            )
            if not field:
                continue
            name, value = field.group(1).lower(), field.group(2).strip()
            if name in {"record_type", "type"}:
                labelled_types.append(value)
            elif name == "slot" and value.isascii() and value.isdecimal():
                labelled_slots.append(int(value))
            elif name == "text" and value:
                labelled_texts.append(value)
        type_matches = not labelled_types or all(
            value.upper() == record_type.upper() for value in labelled_types
        )
        slot_matches = not labelled_slots or all(
            value == expected_slot for value in labelled_slots
        )
        if type_matches and slot_matches and len(labelled_texts) == 1:
            return {expected_slot: labelled_texts[0]}

        # The isolated request itself is the slot side table.  If the model
        # answers with several plain prose lines, preserve every line in order
        # and only normalize the forbidden physical newlines to spaces.  This
        # is deliberately unavailable to normal or multi-slot batches.
        wrapper_line = re.compile(
            rf"^(?:{re.escape(record_type)}|MVD_LLM_RECORDS_V1|"
            rf"slot\s*[:：]?\s*{expected_slot}|{expected_slot})$",
            flags=re.IGNORECASE,
        )
        prose_lines = [line for line in lines if not wrapper_line.fullmatch(line)]
        if type_matches and slot_matches and len(prose_lines) > 1 and not any(
            line.startswith(("#", "{", "[", "|")) for line in prose_lines
        ):
            text = " ".join(
                re.sub(r"^[-*]\s+", "", line, count=1).strip()
                for line in prose_lines
            ).strip()
            if text:
                return {expected_slot: text}

    # With multiple requested slots, an exact line count gives a deterministic
    # side-table mapping. Only Markdown bullet syntax is removed; TEXT is kept.
    if (
        len(expected_slots) < 2
        and not (allow_single_positional and len(expected_slots) == 1)
    ) or len(lines) != len(expected_slots):
        return {}
    positional: dict[int, str] = {}
    for slot, line in zip(expected_slots, lines):
        text = re.sub(r"^[-*]\s+", "", line, count=1).strip()
        if not text or text.startswith(("#", "{", "[")):
            return {}
        positional[slot] = text
    return positional


def _request_entities(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[_Entity],
    shared: Mapping[str, object],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], str],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
]:
    slot_entities = {index: entity for index, entity in enumerate(entities, 1)}
    slots = [dict(entity.value, slot=slot) for slot, entity in slot_entities.items()]
    payload = canonical_json(
        {"protocol": "MVD_LLM_RECORDS_V1", "task": task, **dict(shared), "slots": slots}
    )
    response = backend.complete_planner(
        task=task,
        system_prompt=system_prompt,
        payload=payload,
        config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    allowed = {record_type: frozenset(slot_entities)}
    required = frozenset((record_type, slot) for slot in slot_entities)
    parsed = parse_llm_records(
        _normalize_small_model_response(response, record_type),
        allowed_slots=allowed,
        required=required,
    )
    records = {record.slot: record.text for record in parsed.records}
    issues = list(parsed.issues)
    retried_scenes: list[int] = []
    recovered_count = 0

    first_missing = [slot for slot in slot_entities if slot not in records]
    recovered = _recover_unframed_records(
        response, record_type, first_missing
    )
    records.update(recovered)
    recovered_count += len(recovered)

    missing_slots = [slot for slot in slot_entities if slot not in records]
    for scene_number in sorted({slot_entities[slot].scene_number for slot in missing_slots}):
        scene_slots = [
            slot for slot in missing_slots if slot_entities[slot].scene_number == scene_number
        ]
        retry_payload = canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": task,
                **dict(shared),
                "retry": "missing_slots_only",
                "slots": [dict(slot_entities[slot].value, slot=slot) for slot in scene_slots],
            }
        )
        retry_response = backend.complete_planner(
            task=task,
            system_prompt=system_prompt,
            payload=retry_payload,
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        retry_allowed = {record_type: frozenset(scene_slots)}
        retry_required = frozenset((record_type, slot) for slot in scene_slots)
        retry = parse_llm_records(
            _normalize_small_model_response(retry_response, record_type),
            allowed_slots=retry_allowed,
            required=retry_required,
        )
        issues.extend(retry.issues)
        retry_records = {record.slot: record.text for record in retry.records}
        records.update(retry_records)
        retry_missing = [
            slot for slot in scene_slots if slot not in retry_records
        ]
        recovered = _recover_unframed_records(
            retry_response, record_type, retry_missing
        )
        records.update(recovered)
        recovered_count += len(recovered)
        retried_scenes.append(scene_number)

    # A small model can still omit one of several records in the scene-local
    # retry. Isolate each remaining slot so its side-table mapping is unique.
    # No natural-language content is synthesized or rewritten here.
    isolated_missing = [slot for slot in slot_entities if slot not in records]
    for slot in isolated_missing:
        entity = slot_entities[slot]
        isolated_payload = canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": task,
                **dict(shared),
                "retry": "isolated_missing_slot",
                "slots": [dict(entity.value, slot=slot)],
            }
        )
        isolated_response = backend.complete_planner(
            task=task,
            system_prompt=system_prompt,
            payload=isolated_payload,
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        isolated_allowed = {record_type: frozenset({slot})}
        isolated_required = frozenset({(record_type, slot)})
        isolated = parse_llm_records(
            _normalize_small_model_response(isolated_response, record_type),
            allowed_slots=isolated_allowed,
            required=isolated_required,
        )
        issues.extend(isolated.issues)
        isolated_records = {
            record.slot: record.text for record in isolated.records
        }
        records.update(isolated_records)
        if slot not in isolated_records:
            recovered = _recover_unframed_records(
                isolated_response,
                record_type,
                [slot],
                allow_single_positional=True,
            )
            records.update(recovered)
            recovered_count += len(recovered)
        retried_scenes.append(entity.scene_number)

    unresolved = tuple(
        (record_type, slot_entities[slot].scene_number, slot)
        for slot in slot_entities
        if slot not in records
    )
    values = {entity.key: records[slot] for slot, entity in slot_entities.items() if slot in records}
    return (
        values,
        issues,
        tuple(sorted(set(retried_scenes))),
        unresolved,
        recovered_count,
    )


def _request_entity_batches(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[_Entity],
    batch_size: int,
    shared: Mapping[str, object],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], str],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
]:
    """Request a long entity list without duplicating the whole timeline.

    Each entity already carries its immediately preceding lyric and visual-beat
    context.  Keeping the batch boundary identical to the other Planner tasks
    therefore preserves the editorial context while bounding prompt growth.
    """

    values: dict[tuple[int, ...], str] = {}
    issues: list[LLMRecordIssue] = []
    retried_scenes: set[int] = set()
    missing: list[tuple[str, int, int]] = []
    recovered_count = 0
    for entity_batch in _chunks(entities, batch_size):
        (
            batch_values,
            batch_issues,
            batch_retries,
            batch_missing,
            batch_recovered,
        ) = _request_entities(
            backend,
            task=task,
            record_type=record_type,
            entities=entity_batch,
            shared=shared,
            system_prompt=system_prompt,
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        values.update(batch_values)
        issues.extend(batch_issues)
        retried_scenes.update(batch_retries)
        missing.extend(batch_missing)
        recovered_count += batch_recovered
    return (
        values,
        issues,
        tuple(sorted(retried_scenes)),
        tuple(missing),
        recovered_count,
    )


def _comparison_text(value: str) -> str:
    """Return a language-neutral surface form for repetition validation."""

    if "__MVD_LOCKED_DIALOGUE_" in value:
        return ""
    return re.sub(r"[^\w]+", "", value.casefold(), flags=re.UNICODE)


def _is_near_duplicate(left: str, right: str) -> bool:
    left_key = _comparison_text(left)
    right_key = _comparison_text(right)
    # Short protocol-test fragments and dialogue-only remnants do not contain
    # enough semantic surface to support a quality decision.
    if min(len(left_key), len(right_key)) < 16:
        return False
    if left_key == right_key:
        return True
    if min(len(left_key), len(right_key)) < 48:
        return False
    return (
        SequenceMatcher(None, left_key, right_key, autojunk=False).ratio()
        >= 0.92
    )


def _repeated_entities(
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
    history: list[str],
) -> tuple[list[_Entity], dict[tuple[int, ...], str]]:
    """Find later repeated records without modifying any accepted LLM text."""

    accepted = [text for text in history if text.strip()]
    repeated: list[_Entity] = []
    matched: dict[tuple[int, ...], str] = {}
    for entity in entities:
        text = values.get(entity.key, "").strip()
        if not text:
            continue
        prior = next(
            (
                candidate
                for candidate in reversed(accepted)
                if _is_near_duplicate(text, candidate)
            ),
            "",
        )
        if prior:
            repeated.append(entity)
            matched[entity.key] = prior
        else:
            accepted.append(text)
    return repeated, matched


def _request_distinct_entities(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[_Entity],
    shared: Mapping[str, object],
    history: list[str],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], str],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
    int,
]:
    """Request records and retry only repeated TEXT while keeping output AS IS."""

    values, issues, retries, missing, recovered = _request_entities(
        backend,
        task=task,
        record_type=record_type,
        entities=entities,
        shared=shared,
        system_prompt=system_prompt,
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    if missing:
        return values, issues, retries, missing, recovered, 0
    merged = dict(values)
    retry_scenes_all: set[int] = set(retries)
    for diversity_attempt in range(1, 3):
        repeated, matched = _repeated_entities(entities, merged, history)
        if not repeated:
            return (
                merged,
                issues,
                tuple(sorted(retry_scenes_all)),
                (),
                recovered,
                0,
            )
        forbidden_outputs: list[str] = []
        for candidate in [
            *history,
            *(merged[entity.key] for entity in entities if entity.key in merged),
        ]:
            candidate = candidate.strip()
            if candidate and candidate not in forbidden_outputs:
                forbidden_outputs.append(candidate)
        retry_missing_all: list[tuple[str, int, int]] = []
        retry_scene_numbers = sorted(
            {entity.scene_number for entity in repeated}
        )
        for scene_number in retry_scene_numbers:
            retry_entities = [
                _Entity(
                    entity.scene_number,
                    entity.key,
                    {
                        **entity.value,
                        "rejected_output": merged[entity.key],
                        "must_differ_from": matched[entity.key],
                    },
                )
                for entity in repeated
                if entity.scene_number == scene_number
            ]
            (
                retry_values,
                retry_issues,
                retry_scenes,
                retry_missing,
                retry_recovered,
            ) = _request_entities(
                backend,
                task=task,
                record_type=record_type,
                entities=retry_entities,
                shared={
                    **dict(shared),
                    "retry": "repeated_slots_only",
                    "diversity_retry_attempt": diversity_attempt,
                    "diversity_retry": (
                        "Replace every rejected output with a genuinely different "
                        "creative choice. Do not merely change left/right, word "
                        "order, or synonyms."
                    ),
                    "forbidden_recent_outputs": forbidden_outputs[-12:],
                },
                system_prompt=system_prompt,
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            issues.extend(retry_issues)
            retry_scenes_all.update(retry_scenes)
            retry_scenes_all.add(scene_number)
            retry_missing_all.extend(retry_missing)
            recovered += retry_recovered
            merged.update(retry_values)
        if retry_missing_all:
            return (
                merged,
                issues,
                tuple(sorted(retry_scenes_all)),
                tuple(retry_missing_all),
                recovered,
                0,
            )

    repeated_after_retry, _ = _repeated_entities(entities, merged, history)
    return (
        merged,
        issues,
        tuple(sorted(retry_scenes_all)),
        (),
        recovered,
        len(repeated_after_retry),
    )


def _camera_motion_type(text: str) -> str:
    return next(
        (motion for motion in _CAMERA_MOTION_TYPES if text.startswith(motion)),
        "",
    )


def _camera_budget_violations(
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
    *,
    arc_maximum: int,
) -> dict[tuple[int, ...], tuple[str, ...]]:
    """Select Camera slots that need an LLM quality retry without rewriting TEXT."""

    motion_counts: dict[str, int] = {}
    slow_count = 0
    slow_maximum = max(1, len(entities) // 4)
    violations: dict[tuple[int, ...], list[str]] = {}
    for entity in entities:
        text = values.get(entity.key, "").strip()
        if not text:
            continue
        motion = _camera_motion_type(text)
        if not motion:
            violations.setdefault(entity.key, []).append(
                "required_h3_motion_type"
            )
        else:
            motion_counts[motion] = motion_counts.get(motion, 0) + 1
            maximum = (
                1
                if motion == "Tracking Shot"
                else arc_maximum
                if motion == "Arc Shot"
                else 2
            )
            if motion_counts[motion] > maximum:
                violations.setdefault(entity.key, []).append(
                    f"motion_budget:{motion}"
                )
        if (
            entity.value.get("face_arc_transition")
            and motion != "Arc Shot"
        ):
            violations.setdefault(entity.key, []).append(
                "required_face_arc_transition"
            )
        if entity.value.get("long_arc_emphasis"):
            if motion != "Arc Shot":
                violations.setdefault(entity.key, []).append(
                    "required_long_arc_emphasis"
                )
            elif not _LARGE_FAST_ARC_RE.search(text):
                violations.setdefault(entity.key, []).append(
                    "required_long_arc_energy"
                )
        if entity.value.get("face_zoom_emphasis") and motion != "Zoom In":
            violations.setdefault(entity.key, []).append(
                "required_face_zoom_emphasis"
            )
        if _SLOW_CAMERA_RE.search(text):
            slow_count += 1
            if slow_count > slow_maximum:
                violations.setdefault(entity.key, []).append("slow_speed_budget")
        if "at fast speed" in text and re.search(
            r"ゆっくり|緩やか|at slow speed", text, re.IGNORECASE
        ):
            violations.setdefault(entity.key, []).append(
                "conflicting_camera_speed"
            )
        source_text = canonical_json(
            {
                "lyrics": entity.value.get("lyrics", []),
                "author_body": entity.value.get("author_body", []),
            }
        )
        if (
            _LOWER_BODY_DETAIL_RE.search(text)
            and not _LOWER_BODY_DETAIL_RE.search(source_text)
        ):
            violations.setdefault(entity.key, []).append(
                "unrequested_lower_body_detail"
            )
    return {key: tuple(value) for key, value in violations.items()}


def _anime_story_mv_long_arc_keys(entities: list[_Entity]) -> set[tuple[int, ...]]:
    """Choose a sparse, deterministic set of long Arc slots for anime_story_mv."""

    if not entities:
        return set()
    target = max(1, (len(entities) + 2) // 3)
    selected_indices = {
        index
        for index, entity in enumerate(entities)
        if entity.value.get("face_arc_transition")
    }
    role_priority = {
        "spatial_reveal_or_interaction_coverage": 0,
        "continuity_bridge": 1,
        "new_scene_establishing_edit": 2,
        "upper_body_performance_coverage": 3,
        "expressive_result_coverage": 4,
    }
    candidates = sorted(
        range(len(entities)),
        key=lambda index: (
            -int(entities[index].value.get("shot_duration_ms", 0)),
            role_priority.get(str(entities[index].value.get("editorial_role")), 9),
            index,
        ),
    )
    for index in candidates:
        if len(selected_indices) >= target:
            break
        if index in selected_indices:
            continue
        if any(abs(index - selected) == 1 for selected in selected_indices):
            continue
        selected_indices.add(index)
    if len(selected_indices) < target:
        for index in candidates:
            if len(selected_indices) >= target:
                break
            if index not in selected_indices:
                selected_indices.add(index)
    return {entities[index].key for index in selected_indices}


def _anime_story_mv_face_zoom_key(
    entities: list[_Entity],
    long_arc_keys: set[tuple[int, ...]],
) -> tuple[int, ...] | None:
    """Select one non-Arc performance slot for a readable face Zoom In."""

    role_priority = {
        "expressive_result_coverage": 0,
        "upper_body_performance_coverage": 1,
        "continuity_bridge": 2,
        "new_scene_establishing_edit": 3,
    }
    candidates = [
        entity
        for entity in entities
        if entity.key not in long_arc_keys
        and str(entity.value.get("editorial_role")) in role_priority
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda entity: (
            role_priority[str(entity.value.get("editorial_role"))],
            -int(entity.value.get("shot_duration_ms", 0)),
            entity.key,
        ),
    )
    return selected.key


def _anime_emotional_mv_camera_emphasis(
    entities: list[_Entity],
    *,
    face_target: int | None = None,
) -> tuple[
    set[tuple[int, ...]],
    set[tuple[int, ...]],
    dict[tuple[int, ...], str],
]:
    """Select long Arcs and a sparse face phrase without Camera prose."""

    if not entities:
        return set(), set(), {}
    role_priority = {
        "expressive_result_coverage": 0,
        "upper_body_performance_coverage": 1,
        "continuity_bridge": 2,
        "spatial_reveal_or_interaction_coverage": 3,
        "new_scene_establishing_edit": 4,
    }
    if face_target is None:
        face_target = max(1, (len(entities) + 11) // 12)
    face_target = max(0, min(face_target, len(entities)))
    face_indices: list[int] = []
    face_scenes: set[int] = set()
    ordered_face_candidates = sorted(
        range(len(entities)),
        key=lambda value: (
            role_priority.get(
                str(entities[value].value.get("editorial_role")), 9
            ),
            value,
        ),
    )
    for index in ordered_face_candidates if face_target else ():
        scene_number = entities[index].scene_number
        if scene_number in face_scenes:
            continue
        if any(abs(index - selected) < 3 for selected in face_indices):
            continue
        face_indices.append(index)
        face_scenes.add(scene_number)
        if len(face_indices) >= face_target:
            break
    if 0 < len(face_indices) < face_target:
        for index in range(len(entities)):
            if index not in face_indices:
                face_indices.append(index)
                if len(face_indices) >= face_target:
                    break

    arc_indices: set[int] = set()
    transitions: dict[tuple[int, ...], str] = {}
    for face_index in sorted(face_indices):
        neighbours = (
            (face_index - 1, "arc_into_next_face_cut"),
            (face_index + 1, "arc_out_of_previous_face_cut"),
        )
        for candidate, relation in neighbours:
            if not 0 <= candidate < len(entities):
                continue
            if entities[candidate].scene_number != entities[face_index].scene_number:
                continue
            if candidate in face_indices or candidate in arc_indices:
                continue
            arc_indices.add(candidate)
            transitions[entities[candidate].key] = relation
            break

    arc_target = max(len(arc_indices), (len(entities) * 2 + 2) // 3)
    arc_target = min(arc_target, len(entities) - len(face_indices))
    candidates = sorted(
        (
            index
            for index in range(len(entities))
            if index not in face_indices and index not in arc_indices
        ),
        key=lambda index: (
            -int(entities[index].value.get("shot_duration_ms", 0)),
            role_priority.get(
                str(entities[index].value.get("editorial_role")), 9
            ),
            index,
        ),
    )
    for index in candidates:
        if len(arc_indices) >= arc_target:
            break
        arc_indices.add(index)

    return (
        {entities[index].key for index in arc_indices},
        {entities[index].key for index in face_indices},
        transitions,
    )


def _action_budget_violations(
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
) -> dict[tuple[int, ...], tuple[str, ...]]:
    """Select Action slots for one semantic retry without rewriting their TEXT."""

    slow_count = 0
    slow_maximum = max(1, len(entities) // 4)
    violations: dict[tuple[int, ...], list[str]] = {}
    for entity in entities:
        text = values.get(entity.key, "").strip()
        if not text:
            continue
        if _SLOW_ACTION_RE.search(text):
            slow_count += 1
            if slow_count > slow_maximum:
                violations.setdefault(entity.key, []).append("slow_action_budget")
        if _GENERIC_HAND_ACTION_RE.search(text):
            violations.setdefault(entity.key, []).append("generic_hand_raise_or_lower")
        source_text = canonical_json(
            {
                "lyrics": entity.value.get("lyrics", []),
                "author_body": entity.value.get("author_body", []),
            }
        )
        if (
            _LOWER_BODY_DETAIL_RE.search(text)
            and not _LOWER_BODY_DETAIL_RE.search(source_text)
        ):
            violations.setdefault(entity.key, []).append(
                "unrequested_lower_body_primary_action"
            )
        if (
            _RUNNING_ACTION_RE.search(text)
            and not _RUNNING_ACTION_RE.search(source_text)
        ):
            violations.setdefault(entity.key, []).append(
                "unrequested_running"
            )
    return {key: tuple(value) for key, value in violations.items()}


def _shot_context(
    template: PlannerTemplate,
    protector: DialogueProtector,
) -> dict[tuple[int, int], dict[str, object]]:
    shots: dict[tuple[int, int], dict[str, object]] = {}
    seen_sections: set[str] = set()
    for scene in template.scenes:
        for shot_index, shot in enumerate(scene.shots, 1):
            shot_sections = {
                lyric.section
                for lyric in shot.lyric_annotations
                if lyric.section
            }
            section_entry = bool(shot_sections - seen_sections)
            seen_sections.update(shot_sections)
            shot_end_ms = (
                scene.shots[shot_index].start_ms
                if shot_index < len(scene.shots)
                else scene.end_ms
            )
            lyrics = [
                {
                    "section": lyric.section or "",
                    "text": protector.protect(
                        lyric.text,
                        source_ref=f"scene:{scene.scene_number}:shot:{shot_index}:lyric",
                    ),
                }
                for lyric in shot.lyric_annotations
            ]
            author_body = [
                protector.protect(
                    text,
                    source_ref=f"scene:{scene.scene_number}:shot:{shot_index}:body",
                )
                for text in shot.body
                if text != "未計画"
            ]
            shots[(scene.scene_number, shot_index)] = {
                "scene_number": scene.scene_number,
                "shot_index": shot_index,
                "scene_continuation": scene.continuation,
                "section_entry": section_entry,
                "scene_shot_count": len(scene.shots),
                "shot_start_ms": shot.start_ms,
                "shot_end_ms": shot_end_ms,
                "shot_duration_ms": shot_end_ms - shot.start_ms,
                "lyrics": lyrics,
                "author_body": author_body,
            }
    return shots


def _performance_role(
    context: Mapping[str, object],
    *,
    lip_sync_active: bool,
) -> str:
    """Assign a structural performance purpose without writing action prose."""

    shot_index = int(context["shot_index"])
    shot_count = int(context["scene_shot_count"])
    continuation = bool(context["scene_continuation"])
    if (
        lip_sync_active
        and not continuation
        and bool(context.get("section_entry"))
    ):
        return "face_and_upper_body_accent"
    if shot_count == 1:
        return "lyric_driven_full_body_performance"
    if shot_index == 1:
        if continuation:
            return "continuity_transformation"
        return "new_scene_physical_hook"
    if shot_index == 2:
        return "expressive_hand_arm_performance"
    if shot_index == 3:
        return "environment_interaction_or_body_turn"
    return "expressive_resolution"


def _camera_editorial_role(
    context: Mapping[str, object],
    *,
    lip_sync_active: bool,
) -> str:
    """Assign edit coverage while leaving the final camera sentence to the LLM."""

    shot_index = int(context["shot_index"])
    continuation = bool(context["scene_continuation"])
    if (
        lip_sync_active
        and not continuation
        and bool(context.get("section_entry"))
    ):
        return "face_performance_cut"
    if shot_index == 1:
        if continuation:
            return "continuity_bridge"
        return "new_scene_establishing_edit"
    if shot_index == 2:
        return "upper_body_performance_coverage"
    if shot_index == 3:
        return "spatial_reveal_or_interaction_coverage"
    return "expressive_result_coverage"


def _face_arc_transitions(
    shot_keys: list[tuple[int, int]],
    face_cut_keys: set[tuple[int, int]],
) -> dict[tuple[int, int], str]:
    """Pair each structural face insert with one same-Scene Arc coverage Shot."""

    transitions: dict[tuple[int, int], str] = {}
    for index, face_key in enumerate(shot_keys):
        if face_key not in face_cut_keys:
            continue
        candidates: list[tuple[tuple[int, int], str]] = []
        if index + 1 < len(shot_keys):
            next_key = shot_keys[index + 1]
            if next_key[0] == face_key[0] and next_key not in face_cut_keys:
                candidates.append((next_key, "arc_out_of_previous_face_cut"))
        if index > 0:
            previous_key = shot_keys[index - 1]
            if previous_key[0] == face_key[0] and previous_key not in face_cut_keys:
                candidates.append((previous_key, "arc_into_next_face_cut"))
        if face_key[1] > 1:
            candidates.reverse()
        for candidate, relation in candidates:
            if candidate not in transitions:
                transitions[candidate] = relation
                break
    return transitions


def _protected_context(
    template: PlannerTemplate,
    concept_emd: str,
    scene_emd: str,
    direction: DirectionArtifact,
) -> tuple[
    DialogueProtector,
    str,
    dict[str, object],
    dict[tuple[int, int], dict[str, object]],
    dict[str, list[str]],
]:
    protector = DialogueProtector()
    protected_concept = protector.protect(concept_emd, source_ref="concept_emd")
    scene_setting = (
        parse_scene_emd_fragment(scene_emd) if scene_emd.strip() else None
    )
    scene_context: dict[str, object] = {}
    if scene_setting is not None:
        scene_context = {
            "environment": [
                protector.protect(value, source_ref="scene_emd:environment")
                for value in scene_setting.environment
            ],
            "time_lighting": [
                protector.protect(value, source_ref="scene_emd:time_lighting")
                for value in scene_setting.time_lighting
            ],
            "background_picture": scene_setting.picture_ref or "",
            "authority": (
                "Observed baseline only. Explicit Direction and user instructions "
                "override time, lighting, weather, season, and staging. The Picture "
                "is environment evidence, never a performer or composition template."
            ),
        }
    shots = _shot_context(template, protector)
    directions = {
        "style": [protector.protect(value, source_ref="direction:style") for value in direction.style_direction],
        "environment": [
            protector.protect(value, source_ref="direction:environment")
            for value in direction.environment_direction
        ],
        "time_lighting": [
            protector.protect(value, source_ref="direction:time_lighting")
            for value in direction.time_lighting_direction
        ],
        "motion": [protector.protect(value, source_ref="direction:motion") for value in direction.motion_direction],
        "camera": [protector.protect(value, source_ref="direction:camera") for value in direction.camera_direction],
        "other": [protector.protect(value, source_ref="direction:other") for value in direction.other_direction],
    }
    return protector, protected_concept, scene_context, shots, directions


def _decode_layout_texts(
    template: PlannerTemplate,
    candidate_map: Mapping[int, tuple[Any, ...]],
    layout_texts: Mapping[tuple[int, ...], str],
) -> tuple[
    dict[int, tuple[int, ...]],
    dict[int, bool],
    list[int],
    list[int],
]:
    layouts: dict[int, tuple[int, ...]] = {}
    continuations: dict[int, bool] = {}
    repaired: list[int] = []
    fallback: list[int] = []
    for scene in template.scenes:
        try:
            continuation, starts = parse_scene_layout_selection(
                layout_texts[(scene.scene_number,)],
                candidate_map[scene.scene_number],
                scene_end_ms=scene.end_ms,
                first_scene=scene.scene_number == 1,
            )
        except TimelinePlannerError:
            try:
                continuation, starts = repair_scene_layout_selection(
                    layout_texts[(scene.scene_number,)],
                    candidate_map[scene.scene_number],
                    scene_end_ms=scene.end_ms,
                    first_scene=scene.scene_number == 1,
                )
                repaired.append(scene.scene_number)
            except TimelinePlannerError:
                continuation = False
                starts = (scene.start_ms,)
                fallback.append(scene.scene_number)
        continuations[scene.scene_number] = continuation
        layouts[scene.scene_number] = starts
    return layouts, continuations, repaired, fallback


def _satisfies_boundary_contract(
    template: PlannerTemplate,
    continuations: Mapping[int, bool],
    *,
    planner_policy: str = "",
) -> bool:
    """Validate the structural boundary contract sent on the mix retry."""

    if not template.scenes:
        return False
    first_scene = template.scenes[0]
    if continuations.get(first_scene.scene_number, True):
        return False
    later = [
        continuations[scene.scene_number]
        for scene in template.scenes[1:]
    ]
    if not later:
        return True
    if planner_policy == "anime_emotional_mv":
        minimum_continuations = (len(later) * 3 + 3) // 4
        return later.count(True) >= minimum_continuations
    minimum_cuts = max(1, len(later) // 4)
    minimum_continuations = max(1, (len(later) + 1) // 2)
    later_cut_capacity = len(later) - minimum_continuations
    section_cut_scenes = set(
        [
            number
            for number in _section_entry_scene_numbers(template)
            if number != first_scene.scene_number
        ][:later_cut_capacity]
    )
    if any(continuations.get(scene_number, True) for scene_number in section_cut_scenes):
        return False
    if later.count(False) < minimum_cuts:
        return False
    if later.count(True) < minimum_continuations:
        return False
    maximum_transitions = max(2, (len(later) * 2 + 2) // 3)
    transition_count = sum(
        current != previous for previous, current in zip(later, later[1:])
    )
    if transition_count > maximum_transitions:
        return False
    run_length = 1
    for previous, current in zip(later, later[1:]):
        run_length = run_length + 1 if current == previous else 1
        if run_length > 3:
            return False
    return True


def _repair_boundary_contract(
    template: PlannerTemplate,
    continuations: Mapping[int, bool],
    *,
    planner_policy: str = "",
) -> tuple[dict[int, bool], tuple[int, ...]]:
    """Minimally repair only the structural CUT/CONTINUE sequence."""

    scene_numbers = [scene.scene_number for scene in template.scenes]
    if not scene_numbers:
        return {}, ()
    original = [bool(continuations.get(number, False)) for number in scene_numbers]
    later_original = original[1:]
    later_count = len(later_original)
    if later_count == 0:
        repaired = {scene_numbers[0]: False}
        changed = () if not original[0] else (scene_numbers[0],)
        return repaired, changed

    if planner_policy == "anime_emotional_mv":
        repaired_values = [False, *later_original]
        minimum_continuations = (later_count * 3 + 3) // 4
        needed = minimum_continuations - later_original.count(True)
        section_entries = set(_section_entry_scene_numbers(template))
        candidates = [
            index
            for index, value in enumerate(later_original, 1)
            if not value and scene_numbers[index] not in section_entries
        ]
        candidates.extend(
            index
            for index, value in enumerate(later_original, 1)
            if not value
            and scene_numbers[index] in section_entries
            and index not in candidates
        )
        for index in candidates[:max(0, needed)]:
            repaired_values[index] = True
        repaired = dict(zip(scene_numbers, repaired_values))
        changed = tuple(
            number
            for number, before, after in zip(
                scene_numbers, original, repaired_values
            )
            if before != after
        )
        return repaired, changed

    minimum_cuts = max(1, later_count // 4)
    minimum_continuations = max(1, (later_count + 1) // 2)
    maximum_transitions = max(2, (later_count * 2 + 2) // 3)
    later_cut_capacity = later_count - minimum_continuations
    section_cut_scenes = set(
        [
            number
            for number in _section_entry_scene_numbers(template)
            if number != scene_numbers[0]
        ][:later_cut_capacity]
    )
    # state -> (edit cost, transition count, sequence)
    states: dict[
        tuple[int, int, bool, int],
        tuple[int, int, tuple[bool, ...]],
    ] = {}
    for position, expected in enumerate(later_original):
        next_states: dict[
            tuple[int, int, bool, int],
            tuple[int, int, tuple[bool, ...]],
        ] = {}
        if position == 0:
            prior_items = [(None, (0, 0, ()))]
        else:
            prior_items = list(states.items())
        for state, (cost, transitions, sequence) in prior_items:
            scene_number = scene_numbers[position + 1]
            choices = (
                (False,)
                if scene_number in section_cut_scenes
                else (expected, not expected)
            )
            for choice in choices:
                if state is None:
                    cuts = int(not choice)
                    continues = int(choice)
                    run_length = 1
                else:
                    cuts, continues, previous, previous_run = state
                    run_length = previous_run + 1 if choice == previous else 1
                    if run_length > 3:
                        continue
                    cuts += int(not choice)
                    continues += int(choice)
                next_state = (cuts, continues, choice, run_length)
                candidate = (
                    cost + int(choice != expected),
                    transitions
                    + int(bool(sequence) and sequence[-1] != choice),
                    (*sequence, choice),
                )
                current = next_states.get(next_state)
                if current is None or (
                    candidate[0], candidate[1], candidate[2]
                ) < (current[0], current[1], current[2]):
                    next_states[next_state] = candidate
        states = next_states

    valid = [
        value
        for (cuts, continues, _last, _run), value in states.items()
        if cuts >= minimum_cuts
        and continues >= minimum_continuations
        and value[1] <= maximum_transitions
    ]
    if not valid:
        raise TimelinePlannerError("boundary contract cannot be repaired")
    _cost, _transitions, later_repaired = min(
        valid,
        key=lambda value: (value[0], value[1], value[2]),
    )
    repaired_values = (False, *later_repaired)
    repaired = dict(zip(scene_numbers, repaired_values))
    changed = tuple(
        number
        for number, before, after in zip(scene_numbers, original, repaired_values)
        if before != after
    )
    return repaired, changed


def _section_entry_scene_numbers(template: PlannerTemplate) -> tuple[int, ...]:
    """Return Scenes containing the first annotation of each lyric section."""

    seen_sections: set[str] = set()
    entries: list[int] = []
    for scene in template.scenes:
        scene_sections = {
            lyric.section
            for shot in scene.shots
            for lyric in shot.lyric_annotations
            if lyric.section
        }
        if scene_sections - seen_sections:
            entries.append(scene.scene_number)
        seen_sections.update(scene_sections)
    return tuple(entries)


def generate_planner_content(
    backend: TimelinePlannerBackend,
    *,
    template: PlannerTemplate,
    concept_emd: str,
    direction: DirectionArtifact,
    lip_sync_mode: str,
    lip_sync_target: str,
    scenes_per_batch: int,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    scene_emd: str = "",
    interrupt_callback: Any = None,
) -> tuple[PlannerContent | None, tuple[tuple[str, int, int], ...]]:
    if not 1 <= scenes_per_batch <= 6:
        raise TimelinePlannerError("scenes_per_batch must be in 1..6")
    if lip_sync_mode not in {"off", "context_loop", "audio_reference", "lyrics"}:
        raise TimelinePlannerError("unknown lip_sync_mode")
    if set(system_prompts) != set(TASKS) or any(not value.strip() for value in system_prompts.values()):
        raise TimelinePlannerError("all five Planner system prompts are required")
    direction.validate()
    runtime_config.validate()
    protector, _protected_concept, scene_context, shot_context, directions = _protected_context(
        template, concept_emd, scene_emd, direction
    )
    scene_shared = {"scene_context": scene_context} if scene_context else {}
    dialogue_filter = DialogueFilter(protector.records)
    subject_count = sum(
        1 for line in concept_emd.rstrip().split("\n") if line.startswith("* ")
    )
    subject_roster = [
        {
            "concept_id": f"サブジェクト{index}",
            "subject_ref": f"<Subject {index}>",
        }
        for index in range(1, subject_count + 1)
    ]
    subject_instance_policy = (
        "single_subject_exactly_one_visible_instance"
        if subject_count == 1
        else "defined_subjects_only_no_duplicate_instances"
    )
    all_issues: list[LLMRecordIssue] = []
    all_retries: set[int] = set()
    protocol_recovered_count = 0
    beat_repetition_warning_count = 0
    action_repetition_warning_count = 0
    camera_repetition_warning_count = 0
    performance_directions = {
        key: value for key, value in directions.items() if key != "camera"
    }
    planner_policy = CAMERA_PLANNER_POLICIES.get(
        direction.camera_profile_id, ""
    )
    planner_policy_contract = (
        {
            "policy_id": "anime_emotional_mv",
            "performance_mode": "lyric_specific_emotional_choreography",
            "generic_locomotion_is_support_only": True,
            "incidental_fixed_fixture_interaction": "forbidden",
            "lyric_trigger_scope": "current_scene_original_lyrics_only",
            "noun_only_lyric_visualization": "same_scene_autonomous_visual_predicate",
            "environment_inventory_is_not_action_source": True,
            "lyric_target_consumption": "one_scene_then_requires_new_trigger",
            "external_effect_mode": "autonomous_unless_current_lyric_operates_it",
            "eye_expression_mode": "vary_eyelids_with_lyric_phase",
            "whole_body_emotion_mode": "coordinated_head_torso_pelvis_limbs_weight",
            "emotional_amplitude": "exaggerated_readable_full_body",
            "pose_contrast": "large_asymmetric_silhouette_change",
            "camera_phrase": "dense_energetic_long_arc_short_face_pivot",
            "arc_density": "two_thirds_of_eligible_non_face_slots",
            "arc_energy": "large_amplitude_fast_70_90_percent",
            "face_zoom_frequency": "sparse_section_or_emotional_pivot",
            "later_scene_continue_minimum_ratio": "3/4",
            "all_later_continue_allowed": True,
        }
        if planner_policy == "anime_emotional_mv"
        else {"policy_id": planner_policy}
        if planner_policy
        else {}
    )

    beat_values: dict[tuple[int, ...], str] = {}
    previous_beat = ""
    recent_beat_history: list[str] = []
    total_scenes = len(template.scenes)
    for scene_batch in _chunks(list(template.scenes), scenes_per_batch):
        entities = []
        for scene in scene_batch:
            scene_lyrics = [
                value
                for (scene_number, _), context in shot_context.items()
                if scene_number == scene.scene_number
                for value in context["lyrics"]
            ]
            entities.append(
                _Entity(
                    scene.scene_number,
                    (scene.scene_number,),
                    {
                        "scene_number": scene.scene_number,
                        "total_scene_count": total_scenes,
                        "timeline_position": (
                            "opening"
                            if scene.scene_number <= max(1, total_scenes // 4)
                            else "closing"
                            if scene.scene_number > max(1, total_scenes * 3 // 4)
                            else "middle"
                        ),
                        "has_resolved_lyrics": bool(scene_lyrics),
                        "lyrics": scene_lyrics,
                        "previous_batch_beat": previous_beat,
                    },
                )
            )
        (
            values,
            issues,
            retries,
            missing,
            recovered,
            repetition_warnings,
        ) = _request_distinct_entities(
            backend,
            task="visual-beats",
            record_type="BEAT",
            entities=entities,
            shared={
                **scene_shared,
                "subject_roster": subject_roster,
                "direction": performance_directions,
                "planner_policy_contract": planner_policy_contract,
                "recent_visual_beat_history": recent_beat_history[-12:],
            },
            history=recent_beat_history,
            system_prompt=system_prompts["visual-beats"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(issues)
        all_retries.update(retries)
        protocol_recovered_count += recovered
        beat_repetition_warning_count += repetition_warnings
        if missing:
            return None, missing
        beat_values.update(
            {key: dialogue_filter.filter(text) for key, text in values.items()}
        )
        recent_beat_history.extend(
            beat_values[(scene.scene_number,)] for scene in scene_batch
        )
        if scene_batch:
            previous_beat = beat_values.get(
                (scene_batch[-1].scene_number,), previous_beat
            )

    direction_entity = _Entity(0, (1,), {"visual_beats": [
        {"scene_number": key[0], "text": value} for key, value in sorted(beat_values.items())
    ]})
    song_values, issues, retries, missing, recovered = _request_entities(
        backend,
        task="song-direction",
        record_type="DIRECTION",
        entities=[direction_entity],
        shared={**scene_shared},
        system_prompt=system_prompts["song-direction"],
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    all_issues.extend(issues)
    all_retries.update(retries)
    protocol_recovered_count += recovered
    song_direction_fallback = bool(missing)
    song_direction = (
        ""
        if song_direction_fallback
        else dialogue_filter.filter(song_values[(1,)])
    )

    candidate_map = {
        scene.scene_number: build_layout_candidates(scene)
        for scene in template.scenes
    }
    layout_entities: list[_Entity] = []
    previous_layout_lyrics: list[dict[str, object]] = []
    seen_layout_sections: set[str] = set()
    for scene_index, scene in enumerate(template.scenes):
        lyric_groups = [
            {
                "shot_index": shot_index,
                "lyrics": shot_context[
                    (scene.scene_number, shot_index)
                ]["lyrics"],
            }
            for shot_index, _ in enumerate(scene.shots, 1)
        ]
        current_layout_lyrics = [
            lyric
            for group in lyric_groups
            for lyric in group["lyrics"]
        ]
        current_sections = {
            str(lyric["section"])
            for lyric in current_layout_lyrics
            if lyric["section"]
        }
        unseen_sections = current_sections - seen_layout_sections
        section_entry_shot_index = next(
            (
                int(group["shot_index"])
                for group in lyric_groups
                if any(
                    str(lyric["section"]) in unseen_sections
                    for lyric in group["lyrics"]
                    if lyric["section"]
                )
            ),
            0,
        )
        previous_sections = {
            str(lyric["section"])
            for lyric in previous_layout_lyrics
            if lyric["section"]
        }
        layout_entities.append(
            _Entity(
                scene.scene_number,
                (scene.scene_number,),
                {
                    "scene_number": scene.scene_number,
                    "scene_start_ms": scene.start_ms,
                    "scene_end_ms": scene.end_ms,
                    "visual_beat": beat_values[(scene.scene_number,)],
                    "previous_visual_beat": (
                        ""
                        if scene_index == 0
                        else beat_values[(template.scenes[scene_index - 1].scene_number,)]
                    ),
                    "previous_lyrics": previous_layout_lyrics,
                    "section_changed": (
                        bool(current_sections and previous_sections)
                        and current_sections != previous_sections
                    ),
                    "first_section_appearance": bool(unseen_sections),
                    "new_sections": sorted(unseen_sections),
                    "section_entry_shot_index": section_entry_shot_index,
                    "lyric_groups": lyric_groups,
                    "candidates": [
                        candidate.to_dict()
                        for candidate in candidate_map[scene.scene_number]
                    ],
                },
            )
        )
        seen_layout_sections.update(current_sections)
        previous_layout_lyrics = current_layout_lyrics
    layout_texts, issues, retries, missing, recovered = _request_entity_batches(
        backend,
        task="shot-layout",
        record_type="LAYOUT",
        entities=layout_entities,
        batch_size=scenes_per_batch,
        shared={
            **scene_shared,
            "song_direction": song_direction,
            "planner_policy_contract": planner_policy_contract,
        },
        system_prompt=system_prompts["shot-layout"],
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    all_issues.extend(issues)
    all_retries.update(retries)
    protocol_recovered_count += recovered
    if missing:
        return None, missing
    (
        layouts,
        continuations,
        layout_repaired_scenes,
        layout_fallback_scenes,
    ) = _decode_layout_texts(template, candidate_map, layout_texts)
    layout_mix_retry = False
    if (
        len(template.scenes) >= 4
        and not _satisfies_boundary_contract(
            template,
            continuations,
            planner_policy=planner_policy,
        )
    ):
        layout_mix_retry = True
        later_values = [
            continuations[scene.scene_number]
            for scene in template.scenes[1:]
        ]
        if planner_policy == "anime_emotional_mv":
            retry_reason = (
                "The emotional choreography profile requires at least three "
                "quarters of later Scene boundaries to remain CONTINUE. Keep "
                "the uninterrupted performance and camera path unless a CUT "
                "is a purposeful emotional or spatial reset."
            )
        elif later_values and all(later_values):
            retry_reason = (
                "Every later boundary was CONTINUE. Keep CONTINUE only for an "
                "uninterrupted action and introduce lyric-driven CUT edits."
            )
        elif later_values and not any(later_values):
            retry_reason = (
                "Every boundary was CUT. Compare each Scene with previous_lyrics "
                "and previous_visual_beat; keep emotional pivots as CUT, but use "
                "CONTINUE for genuinely uninterrupted action phases."
            )
        else:
            retry_reason = (
                "The boundary mix did not meet the minimum CUT and CONTINUE "
                "counts, exceeded the maximum same-mode run, or alternated "
                "CUT and CONTINUE too mechanically. Re-evaluate "
                "every adjacent Scene against the supplied boundary contract."
            )
        later_count = len(template.scenes) - 1
        (
            retry_texts,
            retry_issues,
            retry_scenes,
            retry_missing,
            recovered,
        ) = _request_entity_batches(
            backend,
            task="shot-layout",
            record_type="LAYOUT",
            entities=layout_entities,
            batch_size=scenes_per_batch,
            shared={
                **scene_shared,
                "song_direction": song_direction,
                "planner_policy_contract": planner_policy_contract,
                "boundary_mix_retry_reason": retry_reason,
                "boundary_contract": {
                    "first_scene": "CUT",
                    "later_cut_minimum": (
                        0
                        if planner_policy == "anime_emotional_mv"
                        else max(1, (len(template.scenes) - 1) // 4)
                    ),
                    "later_continue_minimum": max(
                        1,
                        (
                            (later_count * 3 + 3) // 4
                            if planner_policy == "anime_emotional_mv"
                            else len(template.scenes) // 2
                        ),
                    ),
                    "maximum_consecutive_same_mode": (
                        later_count
                        if planner_policy == "anime_emotional_mv"
                        else 3
                    ),
                    "maximum_mode_transitions": max(
                        2, (later_count * 2 + 2) // 3
                    ),
                },
            },
            system_prompt=system_prompts["shot-layout"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(retry_issues)
        all_retries.update(retry_scenes)
        protocol_recovered_count += recovered
        if not retry_missing:
            (
                retry_layouts,
                retry_continuations,
                retry_repaired,
                retry_fallback,
            ) = _decode_layout_texts(template, candidate_map, retry_texts)
            layouts = retry_layouts
            continuations = retry_continuations
            layout_repaired_scenes = retry_repaired
            layout_fallback_scenes = retry_fallback
        if not _satisfies_boundary_contract(
            template,
            continuations,
            planner_policy=planner_policy,
        ):
            continuations, boundary_repaired = _repair_boundary_contract(
                template,
                continuations,
                planner_policy=planner_policy,
            )
            layout_repaired_scenes = sorted(
                {*layout_repaired_scenes, *boundary_repaired}
            )
        layout_mix_retry = True
    planned_template = apply_shot_layouts(template, layouts)
    planned_template = apply_scene_continuations(
        planned_template, continuations
    )
    shot_context = _shot_context(planned_template, protector)
    dialogue_filter.add_records(protector.records)

    action_values: dict[tuple[int, ...], str] = {}
    previous_action = ""
    recent_action_history: list[str] = []
    for scene_batch in _chunks(list(planned_template.scenes), scenes_per_batch):
        keys = [
            key for key in planned_template.shot_keys
            if key[0] in {scene.scene_number for scene in scene_batch}
        ]
        entities = []
        prior_key: tuple[int, int] | None = None
        for key in keys:
            context = dict(shot_context[key])
            context["visual_beat"] = beat_values[(key[0],)]
            context["performance_role"] = _performance_role(
                context,
                lip_sync_active=lip_sync_mode != "off",
            )
            context["previous_shot"] = (
                None
                if prior_key is None
                else {"scene_number": prior_key[0], "shot_index": prior_key[1]}
            )
            if prior_key is None:
                context["previous_batch_action"] = previous_action
            if (
                context["performance_role"] == "face_and_upper_body_accent"
                and planner_policy != "anime_emotional_mv"
            ):
                action_values[key] = FACE_PERFORMANCE_CUT_ACTION
            else:
                entities.append(_Entity(key[0], key, context))
            prior_key = key
        if entities:
            (
                values,
                issues,
                retries,
                missing,
                recovered,
                repetition_warnings,
            ) = _request_distinct_entities(
                backend,
                task="actions",
                record_type="ACTION",
                entities=entities,
                shared={
                    **scene_shared,
                    "subject_roster": subject_roster,
                    "direction": performance_directions,
                    "planner_policy_contract": planner_policy_contract,
                    "song_direction": song_direction,
                    "primary_action_concept": lip_sync_target,
                    "subject_instance_policy": subject_instance_policy,
                    "action_batch_contract": {
                        "slow_or_gentle_action_maximum": max(
                            1, len(entities) // 4
                        ),
                        "generic_hand_raise_or_lower_maximum": 0,
                        "unrequested_lower_body_primary_action_maximum": 0,
                        "unrequested_running_maximum": 0,
                    },
                    "recent_action_history": recent_action_history[-18:],
                },
                history=recent_action_history,
                system_prompt=system_prompts["actions"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            if not missing:
                budget_violations = _action_budget_violations(entities, values)
                if budget_violations:
                    retry_entities = [
                        _Entity(
                            entity.scene_number,
                            entity.key,
                            {
                                **entity.value,
                                "rejected_output": values[entity.key],
                                "action_quality_violations": list(
                                    budget_violations[entity.key]
                                ),
                            },
                        )
                        for entity in entities
                        if entity.key in budget_violations
                    ]
                    (
                        retry_values,
                        retry_issues,
                        retry_scenes,
                        retry_missing,
                        retry_recovered,
                    ) = _request_entities(
                        backend,
                        task="actions",
                        record_type="ACTION",
                        entities=retry_entities,
                        shared={
                            **scene_shared,
                            "subject_roster": subject_roster,
                            "direction": performance_directions,
                            "planner_policy_contract": planner_policy_contract,
                            "song_direction": song_direction,
                            "primary_action_concept": lip_sync_target,
                            "subject_instance_policy": subject_instance_policy,
                            "action_batch_contract": {
                                "slow_or_gentle_action_maximum": max(
                                    1, len(entities) // 4
                                ),
                                "generic_hand_raise_or_lower_maximum": 0,
                                "unrequested_lower_body_primary_action_maximum": 0,
                                "unrequested_running_maximum": 0,
                            },
                            "recent_action_history": recent_action_history[-18:],
                            "retry": "action_quality_budget",
                            "action_quality_retry": (
                                "Replace the rejected Action choice. Resolve every "
                                "listed quality violation with a decisive, lyric-linked "
                                "performance and a visibly different final silhouette."
                            ),
                        },
                        system_prompt=system_prompts["actions"],
                        runtime_config=runtime_config,
                        interrupt_callback=interrupt_callback,
                    )
                    issues.extend(retry_issues)
                    all_retries.update(retry_scenes)
                    recovered += retry_recovered
                    missing = tuple(retry_missing)
                    values.update(retry_values)
                    remaining_budget_violations = _action_budget_violations(
                        entities, values
                    )
                    repetition_warnings += len(remaining_budget_violations)
        else:
            values, issues, retries, missing = {}, [], (), ()
            recovered = repetition_warnings = 0
        all_issues.extend(issues)
        all_retries.update(retries)
        protocol_recovered_count += recovered
        action_repetition_warning_count += repetition_warnings
        if missing:
            return None, missing
        for key, text in values.items():
            action_values[key] = dialogue_filter.filter(text)
        recent_action_history.extend(
            action_values[key] for key in keys if key in action_values
        )
        if keys:
            previous_action = action_values.get(keys[-1], previous_action)

    camera_values: dict[tuple[int, ...], str] = {}
    recent_camera_history: list[str] = []
    all_shot_keys = list(planned_template.shot_keys)
    face_cut_keys = {
        key
        for key in all_shot_keys
        if _camera_editorial_role(
            shot_context[key], lip_sync_active=lip_sync_mode != "off"
        )
        == "face_performance_cut"
    }
    face_arc_transitions = _face_arc_transitions(
        all_shot_keys, face_cut_keys
    )
    emotional_face_zoom_remaining = (
        max(
            0,
            max(1, (len(planned_template.scenes) + 7) // 8)
            - len(face_cut_keys),
        )
        if planner_policy == "anime_emotional_mv"
        else 0
    )
    for scene_batch in _chunks(list(planned_template.scenes), scenes_per_batch):
        keys = [
            key for key in planned_template.shot_keys
            if key[0] in {scene.scene_number for scene in scene_batch}
        ]
        entities = []
        for key in keys:
            context = {
                **shot_context[key],
                "visual_beat": beat_values[(key[0],)],
                "locked_action": action_values[key],
                "lip_sync_active": lip_sync_mode != "off",
                "lip_sync_target": lip_sync_target,
                "editorial_role": _camera_editorial_role(
                    shot_context[key],
                    lip_sync_active=lip_sync_mode != "off",
                ),
                "face_arc_transition": face_arc_transitions.get(key, ""),
            }
            if context["editorial_role"] == "face_performance_cut":
                camera_values[key] = (
                    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA
                    if planner_policy == "anime_emotional_mv"
                    else FACE_PERFORMANCE_CUT_CAMERA
                )
            else:
                entities.append(_Entity(key[0], key, context))
        if entities:
            anime_story_mv = planner_policy == "anime_story_mv"
            anime_emotional_mv = planner_policy == "anime_emotional_mv"
            emotional_transitions: dict[tuple[int, ...], str] = {}
            face_zoom_keys: set[tuple[int, ...]] = set()
            batch_has_face_cut = any(key in face_cut_keys for key in keys)
            if anime_emotional_mv:
                batch_face_target = (
                    1
                    if emotional_face_zoom_remaining > 0
                    and not batch_has_face_cut
                    else 0
                )
                (
                    long_arc_keys,
                    face_zoom_keys,
                    emotional_transitions,
                ) = _anime_emotional_mv_camera_emphasis(
                    entities,
                    face_target=batch_face_target,
                )
                emotional_face_zoom_remaining -= len(face_zoom_keys)
            else:
                long_arc_keys = (
                    _anime_story_mv_long_arc_keys(entities)
                    if anime_story_mv
                    else set()
                )
            face_zoom_key = (
                _anime_story_mv_face_zoom_key(entities, long_arc_keys)
                if anime_story_mv
                and lip_sync_mode != "off"
                and not batch_has_face_cut
                else None
            )
            if face_zoom_key is not None:
                face_zoom_keys.add(face_zoom_key)
            if long_arc_keys or face_zoom_keys:
                entities = [
                    _Entity(
                        entity.scene_number,
                        entity.key,
                        {
                            **entity.value,
                            "face_arc_transition": (
                                emotional_transitions.get(entity.key)
                                or entity.value.get("face_arc_transition", "")
                            ),
                            "long_arc_emphasis": entity.key in long_arc_keys,
                            "long_arc_duration_fraction": "70-90%",
                            "face_zoom_emphasis": entity.key in face_zoom_keys,
                            "face_zoom_duration_fraction": (
                                "35-55%"
                                if anime_emotional_mv
                                else "70-90%"
                            ),
                        },
                    )
                    for entity in entities
                ]
            face_arc_count = sum(
                bool(entity.value.get("face_arc_transition"))
                for entity in entities
            )
            arc_required = (
                not (anime_story_mv or anime_emotional_mv)
                and face_arc_count == 0
                and not any(
                    re.search(r"(?i)\barc(?: shot)?\b", value)
                    for value in recent_camera_history[-4:]
                )
            )
            arc_maximum = max(
                face_arc_count,
                len(long_arc_keys),
                int(arc_required),
            )
            camera_batch_contract = {
                "camera_profile_id": direction.camera_profile_id,
                "arc_shot_maximum": arc_maximum,
                "face_arc_transition_count": face_arc_count,
                "long_arc_emphasis_count": len(long_arc_keys),
                "long_arc_duration_fraction": "70-90%" if long_arc_keys else "none",
                "face_zoom_emphasis_count": len(face_zoom_keys),
                "tracking_shot_maximum": 1,
                "same_other_motion_type_maximum": 2,
                "slow_speed_maximum": max(1, len(entities) // 4),
                "unrequested_lower_body_detail_maximum": 0,
            }
            (
                values,
                issues,
                retries,
                missing,
                recovered,
                repetition_warnings,
            ) = _request_distinct_entities(
                backend,
                task="cameras",
                record_type="CAMERA",
                entities=entities,
                shared={
                    **scene_shared,
                    "direction": directions,
                    "planner_policy_contract": planner_policy_contract,
                    "song_direction": song_direction,
                    "subject_instance_policy": subject_instance_policy,
                    "arc_required": arc_required,
                    "camera_batch_contract": camera_batch_contract,
                    "recent_camera_history": recent_camera_history[-12:],
                },
                history=recent_camera_history,
                system_prompt=system_prompts["cameras"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            if not missing:
                budget_violations = _camera_budget_violations(
                    entities,
                    values,
                    arc_maximum=arc_maximum,
                )
                if budget_violations:
                    retry_entities = [
                        _Entity(
                            entity.scene_number,
                            entity.key,
                            {
                                **entity.value,
                                "rejected_output": values[entity.key],
                                "camera_quality_violations": list(
                                    budget_violations[entity.key]
                                ),
                                "disallowed_motion_types": sorted(
                                    {
                                        reason.split(":", 1)[1]
                                        for reason in budget_violations[entity.key]
                                        if reason.startswith("motion_budget:")
                                    }
                                ),
                            },
                        )
                        for entity in entities
                        if entity.key in budget_violations
                    ]
                    (
                        retry_values,
                        retry_issues,
                        retry_scenes,
                        retry_missing,
                        retry_recovered,
                    ) = _request_entities(
                        backend,
                        task="cameras",
                        record_type="CAMERA",
                        entities=retry_entities,
                        shared={
                            **scene_shared,
                            "direction": directions,
                            "planner_policy_contract": planner_policy_contract,
                            "song_direction": song_direction,
                            "subject_instance_policy": subject_instance_policy,
                            "arc_required": False,
                            "camera_batch_contract": camera_batch_contract,
                            "recent_camera_history": recent_camera_history[-12:],
                            "retry": "camera_quality_budget",
                            "camera_quality_retry": (
                                "Replace the rejected Camera choice. Obey every "
                                "listed budget and do not paraphrase the same "
                                "framing, body-region focus, path, or speed."
                            ),
                        },
                        system_prompt=system_prompts["cameras"],
                        runtime_config=runtime_config,
                        interrupt_callback=interrupt_callback,
                    )
                    issues.extend(retry_issues)
                    all_retries.update(retry_scenes)
                    recovered += retry_recovered
                    missing = tuple(retry_missing)
                    values.update(retry_values)
                    remaining_budget_violations = _camera_budget_violations(
                        entities,
                        values,
                        arc_maximum=arc_maximum,
                    )
                    repetition_warnings += len(remaining_budget_violations)
        else:
            values, issues, retries, missing = {}, [], (), ()
            recovered = repetition_warnings = 0
        all_issues.extend(issues)
        all_retries.update(retries)
        protocol_recovered_count += recovered
        camera_repetition_warning_count += repetition_warnings
        if missing:
            return None, missing
        camera_values.update(
            {key: dialogue_filter.filter(text) for key, text in values.items()}
        )
        recent_camera_history.extend(
            camera_values[key] for key in keys if key in camera_values
        )

    empty_shots = [
        key
        for key in planned_template.shot_keys
        if not action_values.get(key, "")
        and not camera_values.get(key, "")
        and not shot_context[key]["author_body"]
    ]
    if empty_shots:
        return None, tuple(("FILTERED", scene, shot) for scene, shot in empty_shots)

    content = PlannerContent(
        visual_beats=tuple(
            (key[0], value) for key, value in sorted(beat_values.items())
        ),
        song_direction=song_direction,
        shot_layouts=tuple(sorted(layouts.items())),
        scene_continuations=tuple(sorted(continuations.items())),
        actions=tuple((key[0], key[1], value) for key, value in sorted(action_values.items())),
        cameras=tuple((key[0], key[1], value) for key, value in sorted(camera_values.items())),
        issue_count=(
            len(all_issues)
            + len(layout_repaired_scenes)
            + len(layout_fallback_scenes)
            + (1 if layout_mix_retry else 0)
            + (1 if song_direction_fallback else 0)
        ),
        retried_scenes=tuple(sorted(all_retries)),
        removed_generated_dialogue_count=dialogue_filter.removed_count,
        unused_protected_dialogue_ids=dialogue_filter.unused_ids,
        layout_repaired_scenes=tuple(layout_repaired_scenes),
        layout_fallback_scenes=tuple(layout_fallback_scenes),
        layout_mix_retry=layout_mix_retry,
        protocol_recovered_count=protocol_recovered_count,
        repetition_warning_count=(
            beat_repetition_warning_count
            + action_repetition_warning_count
            + camera_repetition_warning_count
        ),
        beat_repetition_warning_count=beat_repetition_warning_count,
        action_repetition_warning_count=action_repetition_warning_count,
        camera_repetition_warning_count=camera_repetition_warning_count,
        song_direction_fallback=song_direction_fallback,
    )
    return content, ()


def render_planner_content(
    *,
    content: PlannerContent,
    concept_emd: str,
    template: PlannerTemplate,
    direction: DirectionArtifact,
    lip_sync_mode: str,
    lip_sync_target: str,
    lip_sync_audio_slot: int,
    scene_emd: str = "",
) -> EMDTextArtifact:
    planned_template = apply_shot_layouts(
        template,
        {scene: starts for scene, starts in content.shot_layouts},
    )
    planned_template = apply_scene_continuations(
        planned_template,
        {scene: value for scene, value in content.scene_continuations},
    )
    return render_completed_emd(
        concept_emd=concept_emd,
        scene_emd=scene_emd,
        template=planned_template,
        direction=direction,
        actions={(scene, shot): text for scene, shot, text in content.actions},
        cameras={(scene, shot): text for scene, shot, text in content.cameras},
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        lip_sync_audio_slot=lip_sync_audio_slot,
    )


def plan_timeline(
    backend: TimelinePlannerBackend,
    *,
    template_emd: str,
    concept_emd: str,
    direction: DirectionArtifact | None,
    lip_sync_mode: str,
    lip_sync_target: str,
    lip_sync_audio_slot: int,
    scenes_per_batch: int,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    scene_emd: str = "",
    interrupt_callback: Any = None,
) -> TimelinePlannerResult:
    template = parse_template_emd(template_emd)
    concept = normalize_concept_emd(concept_emd)
    scene = normalize_scene_emd(scene_emd)
    selected_direction = direction or DirectionArtifact()
    content, missing = generate_planner_content(
        backend,
        template=template,
        concept_emd=concept,
        scene_emd=scene,
        direction=selected_direction,
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        scenes_per_batch=scenes_per_batch,
        system_prompts=system_prompts,
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    if content is None:
        return TimelinePlannerResult(
            EMDTextArtifact.create("MVD_EMD_TEMPLATE_V1", template_emd),
            None,
            False,
            missing,
        )
    emd = render_planner_content(
        content=content,
        concept_emd=concept,
        scene_emd=scene,
        template=template,
        direction=selected_direction,
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        lip_sync_audio_slot=lip_sync_audio_slot,
    )
    return TimelinePlannerResult(emd, content, True, ())
