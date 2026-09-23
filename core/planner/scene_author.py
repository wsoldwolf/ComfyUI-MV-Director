"""Opt-in Scene-local authorship path with explicit user-owned fields.

The three LLM passes author event, performance, then camera in that order.
No semantic natural-language repair is performed. Explicit motion templates
may be composed separately, preserving the LLM-authored text.
"""

from __future__ import annotations

import logging
import json
import re
from typing import Any, Mapping, Sequence

from ..artifacts import DirectionArtifact
from ..emd.ast import Scene, Shot
from ..inference import LlamaRuntimeConfig
from .template import PlannerTemplate
from .section_context import section_context_by_scene
from .motion_composition import select_motion_composition


_LOGGER = logging.getLogger("mv_director.nodes")
_EVENT_ASSIGNMENT = re.compile(
    r"SHOT=([1-9][0-9]*)(?:｜|[ \t\u3000]+)(.+)\Z"
)
_END_STATE_SUFFIX = re.compile(
    r"END_STATE(?:\s*[=:：]\s*|[ \u3000]+)([^\t\n]+)\Z"
)
_MAX_END_STATE_LENGTH = 240


def _split_terminal_state(value: str) -> tuple[str, str]:
    """Separate transport metadata without changing the authored prose."""
    matched = _END_STATE_SUFFIX.search(value)
    if matched:
        prefix = value[:matched.start()]
        state = matched.group(1).strip()
        if (prefix and prefix[-1] in "｜|。．. \u3000" and state
                and len(state) <= _MAX_END_STATE_LENGTH):
            prose = prefix.rstrip("｜| \u3000")
            if prose:
                return prose, state
    return value, ""


def build_scene_author_grammar(
    task: str, slots: Sequence[Mapping[str, object]],
) -> str:
    """Constrain only transport and Shot assignment, never generated prose."""
    kinds = {
        "scene-author-event": "EVENT",
        "scene-author-performance": "PERFORMANCE",
        "scene-author-camera": "CAMERA",
    }
    if task not in kinds or not slots:
        raise ValueError("unknown Scene author task or no slots")
    numbers = [slot.get("slot") for slot in slots]
    if any(type(number) is not int or number < 1 for number in numbers):
        raise ValueError("invalid Scene author slot")
    if len(set(numbers)) != len(numbers):
        raise ValueError("duplicate Scene author slot")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    if task == "scene-author-event":
        if numbers != [1]:
            raise ValueError("Scene event requires slot 1")
        positions = slots[0].get("shot_numbers")
        if not isinstance(positions, list) or not positions:
            raise ValueError("Scene event needs Shot positions")
        if any(type(position) is not int or position < 1 for position in positions):
            raise ValueError("invalid Scene event Shot position")
        shots = " | ".join(quote(str(position)) for position in positions)
        root = quote("EVENT\t1\tSHOT=") + f" ({shots}) " + quote("｜") + " char+"
    else:
        root = ' "\\n" '.join(
            quote(f"{kinds[task]}\t{slot}\t") + " char+"
            for slot in numbers
        )
    return "root ::= " + root + ' "\\n"?\n' + r"char ::= [^\x00-\x1f]" + "\n"


def _fixed(shot: Shot, kind: str) -> str:
    return " ".join(value.text for value in shot.directives if value.kind == kind)


def _lyrics(scene: Scene) -> list[dict[str, object]]:
    return [
        {
            "shot": index,
            "lyrics": [
                {
                    "section": lyric.section or "", "text": lyric.text,
                    "source_line": lyric.line_number,
                    "start_ms": lyric.start_ms, "end_ms": lyric.end_ms,
                }
                for lyric in shot.lyric_annotations
            ],
        }
        for index, shot in enumerate(scene.shots, 1)
    ]


def _shot_positions(scene: Scene) -> list[dict[str, object]]:
    return [
        {
            "shot": index,
            "start_ms": shot.start_ms,
            "end_ms": (
                scene.shots[index].start_ms
                if index < len(scene.shots)
                else scene.end_ms
            ),
            "fixed_event": _fixed(shot, "演出"),
            "fixed_performance": _fixed(shot, "演技"),
            "fixed_camera": _fixed(shot, "カメラ"),
            "author_body": [
                text for text in shot.body
                if text != "未計画" and not text.startswith(("`演出` ", "`演技` ", "`カメラ` "))
            ],
        }
        for index, shot in enumerate(scene.shots, 1)
    ]


def generate_scene_author_content(
    backend: Any,
    *,
    template: PlannerTemplate,
    concept_emd: str,
    scene_emd: str,
    direction: DirectionArtifact,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any = None,
) -> tuple[Any | None, tuple[tuple[str, int, int], ...]]:
    """Keep hand-authored Shot fields; generate only absent Scene-local fields."""
    from .engine import PlannerContent, _Entity, _request_entities

    prompts = {
        stage: system_prompts[f"scene-author-{stage}"]
        for stage in ("event", "performance", "camera")
    }
    events: list[tuple[int, int, str]] = []
    actions: list[tuple[int, int, str]] = []
    cameras: list[tuple[int, int, str]] = []
    motion_compositions: list[tuple[int, int, str, int, str]] = []
    terminal_states: list[tuple[int, str, str, str]] = []
    issue_count = 0
    retried_scenes: set[int] = set()
    recovered_count = 0
    previous_terminal: dict[str, str] = {}
    section_contexts = section_context_by_scene(template)
    for scene in template.scenes:
        if interrupt_callback is not None:
            interrupt_callback()
        positions = _shot_positions(scene)
        composition, composition_skip = select_motion_composition(
            scene, positions, direction, concept_emd)
        if composition:
            _LOGGER.info(
                "[MV Director - Timeline Planner] motion composition scheduled; "
                "scene=%d; shot=%d; source=%s; template=%d",
                *composition[:4],
            )
        elif composition_skip != "disabled":
            _LOGGER.info("[MV Director - Timeline Planner] motion composition skipped; scene=%d; reason=%s",
                         scene.scene_number, composition_skip)
        shared = {
            "scene_number": scene.scene_number,
            "scene_start_ms": scene.start_ms,
            "scene_end_ms": scene.end_ms,
            "continuation": scene.continuation,
            "scene_descriptions": list(scene.descriptions),
            "original_lyrics": _lyrics(scene),
            "section_lyric_context": section_contexts[scene.scene_number],
            "scene_environment": list(direction.environment_direction),
            "scene_time_lighting": list(direction.time_lighting_direction),
            "subject_emd": concept_emd,
            "scene_emd": scene_emd,
            "shot_positions": positions,
        }
        # An explicit event in any Shot owns the Scene's event selection.
        # Other Shots may have their own explicit event; none is overwritten.
        fixed_events = {
            index: _fixed(shot, "演出")
            for index, shot in enumerate(scene.shots, 1)
            if _fixed(shot, "演出")
        }
        scene_event = " / ".join(f"Shot{index}: {value}" for index, value in fixed_events.items())
        if not scene_event:
            for attempt in range(2):
                result, issues, retries, missing, recovered = _request_entities(
                    backend,
                    task="scene-author-event",
                    record_type="EVENT",
                    entities=[_Entity(scene.scene_number, (1,), {
                        "scene_number": scene.scene_number,
                        "scene": scene.scene_number,
                        "scope": "one_scene_event",
                        "shot_numbers": list(range(1, len(scene.shots) + 1)),
                    })],
                    shared={
                        **shared,
                        "scene_environment": list(direction.environment_direction),
                        "scene_time_lighting": list(direction.time_lighting_direction),
                        "scene_other": list(direction.other_direction),
                        "staging_candidates_optional": list(direction.staging_candidates),
                        "event_position_retry": attempt > 0,
                        "previous_scene_state": (
                            previous_terminal.get("event", "") if scene.continuation else ""
                        ),
                    },
                    system_prompt=prompts["event"],
                    runtime_config=runtime_config,
                    interrupt_callback=interrupt_callback,
                )
                issue_count += len(issues)
                retried_scenes.update(retries)
                recovered_count += recovered
                if missing:
                    return None, tuple(missing)
                event_prose, event_state = _split_terminal_state(result[(1,)])
                matched = _EVENT_ASSIGNMENT.fullmatch(event_prose)
                if matched and int(matched.group(1)) <= len(scene.shots):
                    event_shot = int(matched.group(1))
                    scene_event = matched.group(2)
                    if scene_event != "なし":
                        events.append((scene.scene_number, event_shot, scene_event))
                    break
                _LOGGER.warning(
                    "[MV Director - Timeline Planner] Scene event slot invalid; "
                    "scene=%d; attempt=%d",
                    scene.scene_number, attempt + 1,
                )
            else:
                return None, (("EVENT_POSITION", scene.scene_number, 1),)
        shared["accepted_event"] = scene_event
        shared["event_source"] = "author" if fixed_events else "llm"
        shared["accepted_event_shot"] = (
            event_shot if not fixed_events else min(fixed_events)
        )

        fixed_actions = {
            index: _fixed(shot, "演技")
            for index, shot in enumerate(scene.shots, 1)
            if _fixed(shot, "演技")
        }
        pending_actions = [
            index for index in range(1, len(scene.shots) + 1)
            if index not in fixed_actions
        ]
        action_texts = dict(fixed_actions)
        if composition:
            shared["scheduled_motion_composition"] = {
                "shot": composition[1], "source": composition[2],
                "template": composition[3], "text": composition[4],
            }
        if pending_actions:
            result, issues, retries, missing, recovered = _request_entities(
                backend,
                task="scene-author-performance",
                record_type="PERFORMANCE",
                entities=[
                    _Entity(scene.scene_number, (index,), {
                        "scene_number": scene.scene_number,
                        "scene": scene.scene_number,
                        "shot": index,
                        "position": positions[index - 1],
                    })
                    for index in pending_actions
                ],
                shared={
                    **shared,
                    "scene_motion": list(direction.motion_direction),
                    "staging_candidates_optional": list(direction.staging_candidates),
                    "scene_other": list(direction.other_direction),
                    "fixed_performances": {
                        str(index): value for index, value in fixed_actions.items()
                    },
                    "previous_scene_state": (
                        previous_terminal.get("performance", "") if scene.continuation else ""
                    ),
                },
                system_prompt=prompts["performance"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            issue_count += len(issues)
            retried_scenes.update(retries)
            recovered_count += recovered
            if missing:
                return None, tuple(missing)
            action_states: dict[int, str] = {}
            for index in pending_actions:
                action_texts[index], action_states[index] = _split_terminal_state(
                    result[(index,)]
                )
            actions.extend(
                (scene.scene_number, index, action_texts[index])
                for index in pending_actions
            )
        if composition:
            motion_compositions.append(composition)
            target = composition[1]
            action_texts[target] = action_texts[target] + " " + composition[4]
        shared["accepted_performances"] = {
            str(index): value for index, value in action_texts.items()
        }

        fixed_cameras = {
            index: _fixed(shot, "カメラ")
            for index, shot in enumerate(scene.shots, 1)
            if _fixed(shot, "カメラ")
        }
        pending_cameras = [
            index for index in range(1, len(scene.shots) + 1)
            if index not in fixed_cameras
        ]
        camera_texts = dict(fixed_cameras)
        if pending_cameras:
            result, issues, retries, missing, recovered = _request_entities(
                backend,
                task="scene-author-camera",
                record_type="CAMERA",
                entities=[
                    _Entity(scene.scene_number, (index,), {
                        "scene_number": scene.scene_number,
                        "scene": scene.scene_number,
                        "shot": index,
                        "position": positions[index - 1],
                    })
                    for index in pending_cameras
                ],
                shared={
                    **shared,
                    "scene_camera": list(direction.camera_direction),
                    "scene_other": list(direction.other_direction),
                    "fixed_cameras": {
                        str(index): value for index, value in fixed_cameras.items()
                    },
                    "previous_scene_state": (
                        previous_terminal.get("camera", "") if scene.continuation else ""
                    ),
                },
                system_prompt=prompts["camera"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            issue_count += len(issues)
            retried_scenes.update(retries)
            recovered_count += recovered
            if missing:
                return None, tuple(missing)
            camera_states: dict[int, str] = {}
            for index in pending_cameras:
                camera_texts[index], camera_states[index] = _split_terminal_state(
                    result[(index,)]
                )
            cameras.extend(
                (scene.scene_number, index, camera_texts[index])
                for index in pending_cameras
            )
        last = len(scene.shots)
        previous_terminal = {
            "event": event_state if not fixed_events else "",
            "performance": action_states.get(last, "") if pending_actions else "",
            "camera": camera_states.get(last, "") if pending_cameras else "",
        }
        terminal_states.append((
            scene.scene_number,
            previous_terminal["event"],
            previous_terminal["performance"],
            previous_terminal["camera"],
        ))
        _LOGGER.info(
            "[MV Director - Timeline Planner] Scene authorship completed; "
            "scene=%d; shots=%d; authored_fields=%d; terminal_state=%s",
            scene.scene_number,
            last,
            len(fixed_events) + len(fixed_actions) + len(fixed_cameras),
            ",".join(key for key, value in previous_terminal.items() if value) or "none",
        )
    return PlannerContent(
        visual_beats=(),
        song_direction="",
        shot_layouts=(),
        actions=tuple(actions),
        cameras=tuple(cameras),
        issue_count=issue_count,
        retried_scenes=tuple(sorted(retried_scenes)),
        removed_generated_dialogue_count=0,
        unused_protected_dialogue_ids=(),
        protocol_recovered_count=recovered_count,
        events=tuple(events),
        typed_output=True,
        motion_compositions=tuple(motion_compositions),
        terminal_states=tuple(terminal_states),
    ), ()
