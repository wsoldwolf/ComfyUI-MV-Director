"""Finite multi-task Timeline Planner orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Protocol

from ..artifacts import DirectionArtifact, EMDTextArtifact, canonical_json, normalize_newlines
from ..inference import LlamaRuntimeConfig
from ..protocols import LLMRecordIssue, parse_llm_records
from .dialogue import DialogueFilter, DialogueProtector
from .errors import TimelinePlannerError
from .renderer import render_completed_emd
from .template import PlannerTemplate, normalize_concept_emd, parse_template_emd


PLANNER_ALGORITHM_VERSION = "mvd-timeline-planner-v3"
TASKS = ("lyric-notes", "song-direction", "actions", "cameras")


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
    lyric_notes: tuple[tuple[int, str], ...]
    song_direction: str
    actions: tuple[tuple[int, int, str], ...]
    cameras: tuple[tuple[int, int, str], ...]
    issue_count: int
    retried_scenes: tuple[int, ...]
    removed_generated_dialogue_count: int
    unused_protected_dialogue_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "lyric_notes": [list(value) for value in self.lyric_notes],
            "song_direction": self.song_direction,
            "actions": [list(value) for value in self.actions],
            "cameras": [list(value) for value in self.cameras],
            "issue_count": self.issue_count,
            "retried_scenes": list(self.retried_scenes),
            "removed_generated_dialogue_count": self.removed_generated_dialogue_count,
            "unused_protected_dialogue_ids": list(self.unused_protected_dialogue_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannerContent":
        return cls(
            lyric_notes=tuple((int(row[0]), str(row[1])) for row in value["lyric_notes"]),
            song_direction=str(value["song_direction"]),
            actions=tuple((int(row[0]), int(row[1]), str(row[2])) for row in value["actions"]),
            cameras=tuple((int(row[0]), int(row[1]), str(row[2])) for row in value["cameras"]),
            issue_count=int(value["issue_count"]),
            retried_scenes=tuple(int(item) for item in value["retried_scenes"]),
            removed_generated_dialogue_count=int(value["removed_generated_dialogue_count"]),
            unused_protected_dialogue_ids=tuple(str(item) for item in value["unused_protected_dialogue_ids"]),
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
) -> tuple[dict[tuple[int, ...], str], list[LLMRecordIssue], tuple[int, ...], tuple[tuple[str, int, int], ...]]:
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

    missing_slots = [slot for kind, slot in parsed.missing if kind == record_type]
    for scene_number in sorted({slot_entities[slot].scene_number for slot in missing_slots}):
        scene_slots = [
            slot for slot in missing_slots if slot_entities[slot].scene_number == scene_number
        ]
        retry_payload = canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": task,
                "retry": "missing_slots_only",
                **dict(shared),
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
        records.update({record.slot: record.text for record in retry.records})
        retried_scenes.append(scene_number)

    unresolved = tuple(
        (record_type, slot_entities[slot].scene_number, slot)
        for slot in slot_entities
        if slot not in records
    )
    values = {entity.key: records[slot] for slot, entity in slot_entities.items() if slot in records}
    return values, issues, tuple(retried_scenes), unresolved


def _protected_context(
    template: PlannerTemplate,
    concept_emd: str,
    direction: DirectionArtifact,
) -> tuple[DialogueProtector, str, dict[tuple[int, int], dict[str, object]], dict[str, list[str]]]:
    protector = DialogueProtector()
    protected_concept = protector.protect(concept_emd, source_ref="concept_emd")
    shots: dict[tuple[int, int], dict[str, object]] = {}
    for scene in template.scenes:
        for shot_index, shot in enumerate(scene.shots, 1):
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
                "shot_start_ms": shot.start_ms,
                "lyrics": lyrics,
                "author_body": author_body,
            }
    directions = {
        "style": [protector.protect(value, source_ref="direction:style") for value in direction.style_direction],
        "motion": [protector.protect(value, source_ref="direction:motion") for value in direction.motion_direction],
        "camera": [protector.protect(value, source_ref="direction:camera") for value in direction.camera_direction],
        "other": [protector.protect(value, source_ref="direction:other") for value in direction.other_direction],
    }
    return protector, protected_concept, shots, directions


def generate_planner_content(
    backend: TimelinePlannerBackend,
    *,
    template: PlannerTemplate,
    concept_emd: str,
    direction: DirectionArtifact,
    lip_sync_target: str,
    scenes_per_batch: int,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any = None,
) -> tuple[PlannerContent | None, tuple[tuple[str, int, int], ...]]:
    if not 1 <= scenes_per_batch <= 6:
        raise TimelinePlannerError("scenes_per_batch must be in 1..6")
    if set(system_prompts) != set(TASKS) or any(not value.strip() for value in system_prompts.values()):
        raise TimelinePlannerError("all four Planner system prompts are required")
    direction.validate()
    runtime_config.validate()
    protector, protected_concept, shot_context, directions = _protected_context(
        template, concept_emd, direction
    )
    dialogue_filter = DialogueFilter(protector.records)
    all_issues: list[LLMRecordIssue] = []
    all_retries: set[int] = set()

    note_values: dict[tuple[int, ...], str] = {}
    for scene_batch in _chunks(list(template.scenes), 6):
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
                    {"scene_number": scene.scene_number, "lyrics": scene_lyrics},
                )
            )
        values, issues, retries, missing = _request_entities(
            backend,
            task="lyric-notes",
            record_type="NOTE",
            entities=entities,
            shared={},
            system_prompt=system_prompts["lyric-notes"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(issues)
        all_retries.update(retries)
        if missing:
            return None, missing
        note_values.update({key: dialogue_filter.filter(text) for key, text in values.items()})

    direction_entity = _Entity(0, (1,), {"notes": [
        {"scene_number": key[0], "text": value} for key, value in sorted(note_values.items())
    ]})
    song_values, issues, retries, missing = _request_entities(
        backend,
        task="song-direction",
        record_type="DIRECTION",
        entities=[direction_entity],
        shared={},
        system_prompt=system_prompts["song-direction"],
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    all_issues.extend(issues)
    all_retries.update(retries)
    if missing:
        return None, missing
    song_direction = dialogue_filter.filter(song_values[(1,)])

    action_values: dict[tuple[int, ...], str] = {}
    previous_action = ""
    for scene_batch in _chunks(list(template.scenes), scenes_per_batch):
        keys = [
            key for key in template.shot_keys if key[0] in {scene.scene_number for scene in scene_batch}
        ]
        entities = []
        prior_key: tuple[int, int] | None = None
        for key in keys:
            context = dict(shot_context[key])
            context["previous_shot"] = (
                None
                if prior_key is None
                else {"scene_number": prior_key[0], "shot_index": prior_key[1]}
            )
            if prior_key is None:
                context["previous_batch_action"] = previous_action
            entities.append(_Entity(key[0], key, context))
            prior_key = key
        values, issues, retries, missing = _request_entities(
            backend,
            task="actions",
            record_type="ACTION",
            entities=entities,
            shared={
                "concept_emd": protected_concept,
                "direction": {"motion": directions["motion"], "other": directions["other"]},
                "song_direction": song_direction,
                "primary_action_concept": lip_sync_target,
            },
            system_prompt=system_prompts["actions"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(issues)
        all_retries.update(retries)
        if missing:
            return None, missing
        for key, text in values.items():
            action_values[key] = dialogue_filter.filter(text)
        if keys:
            previous_action = action_values.get(keys[-1], previous_action)

    camera_values: dict[tuple[int, ...], str] = {}
    for scene_batch in _chunks(list(template.scenes), scenes_per_batch):
        keys = [
            key for key in template.shot_keys if key[0] in {scene.scene_number for scene in scene_batch}
        ]
        entities = [
            _Entity(
                key[0],
                key,
                {
                    **shot_context[key],
                    "locked_action": action_values[key],
                },
            )
            for key in keys
        ]
        values, issues, retries, missing = _request_entities(
            backend,
            task="cameras",
            record_type="CAMERA",
            entities=entities,
            shared={"direction": {"camera": directions["camera"]}},
            system_prompt=system_prompts["cameras"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(issues)
        all_retries.update(retries)
        if missing:
            return None, missing
        camera_values.update({key: dialogue_filter.filter(text) for key, text in values.items()})

    empty_shots = [
        key
        for key in template.shot_keys
        if not action_values.get(key, "")
        and not camera_values.get(key, "")
        and not shot_context[key]["author_body"]
    ]
    if empty_shots:
        return None, tuple(("FILTERED", scene, shot) for scene, shot in empty_shots)

    content = PlannerContent(
        lyric_notes=tuple((key[0], value) for key, value in sorted(note_values.items())),
        song_direction=song_direction,
        actions=tuple((key[0], key[1], value) for key, value in sorted(action_values.items())),
        cameras=tuple((key[0], key[1], value) for key, value in sorted(camera_values.items())),
        issue_count=len(all_issues),
        retried_scenes=tuple(sorted(all_retries)),
        removed_generated_dialogue_count=dialogue_filter.removed_count,
        unused_protected_dialogue_ids=dialogue_filter.unused_ids,
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
) -> EMDTextArtifact:
    return render_completed_emd(
        concept_emd=concept_emd,
        template=template,
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
    interrupt_callback: Any = None,
) -> TimelinePlannerResult:
    template = parse_template_emd(template_emd)
    concept = normalize_concept_emd(concept_emd)
    selected_direction = direction or DirectionArtifact()
    content, missing = generate_planner_content(
        backend,
        template=template,
        concept_emd=concept,
        direction=selected_direction,
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
        template=template,
        direction=selected_direction,
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        lip_sync_audio_slot=lip_sync_audio_slot,
    )
    return TimelinePlannerResult(emd, content, True, ())
