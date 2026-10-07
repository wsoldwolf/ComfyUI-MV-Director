"""Scene-local authorship path with explicit user-owned fields.

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
from ..direction.profiles import (CAMERA_ARC_ROLL_POLICIES, MOTION_COMPOSITION_RESELECTIONS,
                                  MOTION_COMPOSITION_TIMINGS, MOTION_TEMPLATES)
from ..emd.ast import MouthPerformance, Scene, Shot
from ..inference import LlamaRuntimeConfig
from .template import PlannerTemplate
from .section_context import section_context_by_scene
from .motion_composition import select_motion_composition
from .candidate_policy import validate_staging_candidate_policy
from .camera_continuity import arc_directions, inspect_arc_sequence
from .requests import request_entities
from .types import PlannerContent, PlannerEntity
from .mouth_performance import mouth_scene_payload
from .prop_inventory import request_prop_inventory
from .prop_decision import request_prop_decisions


_LOGGER = logging.getLogger("mv_director.nodes")
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
    root = ' "\\n" '.join(
        quote(f"{kinds[task]}\t{slot}\t") + " char+"
        for slot in numbers
    )
    return "root ::= " + root + ' "\\n"?\n' + r"char ::= [^\x00-\x1f]" + "\n"


def build_composition_choice_grammar(candidate_count: int) -> str:
    """Constrain the transport to one existing, nonzero candidate number."""
    if not 1 <= candidate_count <= 12:
        raise ValueError("composition choice requires 1..12 candidates")
    choices = " | ".join(json.dumps(str(index)) for index in range(1, candidate_count + 1))
    return 'root ::= "CHOICE\\t1\\t" (' + choices + ') "\\n"?\n'


def _reselect_composition(
    backend: Any, *, scene: Scene, composition: tuple[int, int, str, int, str],
    direction: DirectionArtifact, event_texts: Mapping[int, str],
    action_texts: Mapping[int, str], camera_texts: Mapping[int, str],
    system_prompt: str, runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
    prop_context: Mapping[str, object] | None = None,
) -> tuple[int, int, str, int, str]:
    """Retry malformed choices once; never delete a scheduled composition."""
    profile = direction.motion_policy_profile_id or direction.motion_profile_id
    templates = (direction.motion_templates if direction.motion_templates is not None
                 else MOTION_TEMPLATES.get(profile, ()))
    if len(templates) < 2:
        return composition
    shots = [
        {
            "shot": index,
            "duration_ms": (
                scene.shots[index].start_ms if index < len(scene.shots)
                else scene.end_ms
            ) - shot.start_ms,
            "lyrics": [lyric.text for lyric in shot.lyric_annotations],
            "event": event_texts.get(index, ""),
            "performance": action_texts.get(index, ""),
            "camera": camera_texts.get(index, ""),
        }
        for index, shot in enumerate(scene.shots, 1)
    ]
    request = {
        "slots": [{"slot": 1, "scene_number": scene.scene_number}],
        "scene": scene.scene_number,
        "target_shot": composition[1],
        "shots": shots,
        "current_choice": composition[3],
        "candidates": {str(index): value for index, value in enumerate(templates, 1)},
    }
    if prop_context:
        request.update(prop_context)
    for attempt in range(2):
        if interrupt_callback is not None:
            interrupt_callback()
        if attempt:
            request["retry"] = "invalid_choice_only"
        response = backend.complete_planner(
            task="scene-author-composition-choice", system_prompt=system_prompt,
            payload=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
            config=runtime_config, interrupt_callback=interrupt_callback,
        ).strip()
        match = re.fullmatch(r"CHOICE\t1\t([1-9][0-9]*)", response)
        if match and 1 <= int(match.group(1)) <= len(templates):
            index = int(match.group(1))
            if index != composition[3]:
                _LOGGER.info(
                    "[MV Director - Timeline Planner] motion composition reselected; "
                    "scene=%d; shot=%d; from=%d; to=%d",
                    scene.scene_number, composition[1], composition[3], index,
                )
            return (*composition[:3], index, templates[index - 1])
        _LOGGER.warning(
            "[MV Director - Timeline Planner] invalid motion composition choice; "
            "scene=%d; attempt=%d; retaining=%d",
            scene.scene_number, attempt + 1, composition[3],
        )
    return composition


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


def count_motion_composition_choices(
    template: PlannerTemplate, direction: DirectionArtifact, concept_emd: str,
) -> int:
    """Count post-author choice calls for an accurate progress total."""
    profile = direction.motion_policy_profile_id or direction.motion_profile_id
    if MOTION_COMPOSITION_RESELECTIONS.get(profile) != "guarded_no_drop":
        return 0
    templates = (direction.motion_templates if direction.motion_templates is not None
                 else MOTION_TEMPLATES.get(profile, ()))
    if len(templates) < 2:
        return 0
    return sum(
        select_motion_composition(scene, _shot_positions(scene), direction, concept_emd)[0]
        is not None
        for scene in template.scenes
    )


def generate_scene_author_content(
    backend: Any,
    *,
    template: PlannerTemplate,
    concept_emd: str,
    scene_emd: str,
    direction: DirectionArtifact,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    staging_candidate_policy: str = "optional",
    lip_sync_mode: str = "off",
    mouth_performances: Mapping[int, tuple[MouthPerformance, ...]] | None = None,
    interrupt_callback: Any = None,
) -> tuple[Any | None, tuple[tuple[str, int, int], ...]]:
    """Keep hand-authored Shot fields; generate only absent Scene-local fields."""
    validate_staging_candidate_policy(staging_candidate_policy)
    _LOGGER.info(
        "[MV Director - Timeline Planner] staging candidate policy=%s; candidates=%d",
        staging_candidate_policy, len(direction.staging_candidates),
    )

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
    previous_arc_direction: str | None = None
    section_contexts = section_context_by_scene(template)
    previous_prop_state: object = ""
    inventory = ()
    prop_prompts_enabled = all(system_prompts.get(key, "").strip() for key in (
        "subject-prop-inventory", "scene-author-prop-decision", "prop-performance-addendum",
    ))
    if prop_prompts_enabled and any(
        not _fixed(shot, "演技") for scene in template.scenes for shot in scene.shots
    ):
        first = template.scenes[0]
        inventory_result = request_prop_inventory(
            backend, subject_emd=concept_emd,
            fixed_boundary={str(i): _fixed(shot, "演技")
                            for i, shot in enumerate(first.shots, 1)
                            if _fixed(shot, "演技")},
            scene_number=first.scene_number,
            system_prompt=system_prompts["subject-prop-inventory"],
            runtime_config=runtime_config, interrupt_callback=interrupt_callback,
        )
        inventory = inventory_result.props
        _LOGGER.log(
            logging.INFO if inventory_result.status == "transport_valid" else logging.WARNING,
            "[MV Director - Timeline Planner] prop inventory completed; status=%s; "
            "props=%d; attempts=%d", inventory_result.status, len(inventory),
            inventory_result.attempts,
        )
    # The inventory may be empty. Refine the progress estimate rather than
    # counting skipped Scene decisions as completed inference calls.
    configure_prop_progress = getattr(backend, "configure_prop_progress", None)
    if prop_prompts_enabled and configure_prop_progress is not None:
        configure_prop_progress(sum(
            any(not _fixed(shot, "演技") for shot in scene.shots)
            for scene in template.scenes
        ) if inventory else 0)
    for scene in template.scenes:
        if interrupt_callback is not None:
            interrupt_callback()
        positions = _shot_positions(scene)
        composition, composition_skip = select_motion_composition(
            scene, positions, direction, concept_emd)
        composition_profile = (
            direction.motion_policy_profile_id or direction.motion_profile_id
        )
        composition_timing = MOTION_COMPOSITION_TIMINGS.get(
            composition_profile, "pre_author"
        )
        if composition:
            _LOGGER.info(
                "[MV Director - Timeline Planner] motion composition scheduled; "
                "scene=%d; shot=%d; source=%s; template=%d; timing=%s",
                *composition[:4], composition_timing,
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
            "staging_candidate_policy": staging_candidate_policy,
        }
        if template.audio_activity is not None:
            shared["audio_activity"] = template.audio_activity.scene_payload(
                start_ms=scene.start_ms, end_ms=scene.end_ms, audio_mode=lip_sync_mode,
            )
        # Fixed Events own their Shots only. Other Shots remain eligible for
        # Scene-local authorship in the same LLM call.
        fixed_events = {
            index: _fixed(shot, "演出")
            for index, shot in enumerate(scene.shots, 1)
            if _fixed(shot, "演出")
        }
        event_texts = dict(fixed_events)
        pending_events = [
            index for index in range(1, len(scene.shots) + 1)
            if index not in fixed_events
            # A completed EMD has no marker for a deliberate "no Event".
            # Do not reopen an otherwise fully authored Shot on re-entry.
            and (
                not _fixed(scene.shots[index - 1], "演技")
                or not _fixed(scene.shots[index - 1], "カメラ")
            )
        ]
        event_states: dict[int, str] = {}
        if pending_events:
            result, issues, retries, missing, recovered = request_entities(
                backend,
                task="scene-author-event",
                record_type="EVENT",
                entities=[
                    PlannerEntity(scene.scene_number, (index,), {
                        "scene_number": scene.scene_number,
                        "scene": scene.scene_number,
                        "shot": index,
                        "position": positions[index - 1],
                    })
                    for index in pending_events
                ],
                shared={
                    **shared,
                    "scene_other": list(direction.other_direction),
                    "staging_candidates_optional": list(direction.staging_candidates),
                    "fixed_events": {
                        str(index): value for index, value in fixed_events.items()
                    },
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
            for index in pending_events:
                event_texts[index], event_states[index] = _split_terminal_state(
                    result[(index,)]
                )
                if event_texts[index] not in {"なし", "無し", "none", "NONE"}:
                    events.append((scene.scene_number, index, event_texts[index]))
        shared["accepted_events_by_shot"] = {
            str(index): value for index, value in sorted(event_texts.items())
        }
        shared["event_sources_by_shot"] = {
            str(index): "author" if index in fixed_events else "llm"
            for index in sorted(event_texts)
        }

        scene_mouths = (mouth_performances or {}).get(scene.scene_number, scene.mouth_performances)
        if scene_mouths:
            shared["mouth_performance"] = mouth_scene_payload(scene, scene_mouths)
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
        if composition and composition_timing == "pre_author":
            shared["scheduled_motion_composition"] = {
                "shot": composition[1], "source": composition[2],
                "template": composition[3], "text": composition[4],
            }
        prop_decisions = {}
        if inventory and pending_actions:
            prop_request = {
                **shared,
                "prop_inventory": list(inventory),
                "fixed_performances": {str(i): v for i, v in fixed_actions.items()},
                "previous_prop_state": previous_prop_state if scene.continuation else "",
                "previous_scene_state": (
                    previous_terminal.get("performance", "") if scene.continuation else ""
                ),
                "scene_motion": list(direction.motion_direction),
                "scene_other": list(direction.other_direction),
                "staging_candidates_optional": list(direction.staging_candidates),
            }
            if composition:
                # Post-author supplements are advisory here, not silently
                # moved into Performance. Their later selection also sees
                # the accepted holding plan.
                prop_request["planned_motion_composition"] = {
                    "shot": composition[1], "text": composition[4],
                    "timing": composition_timing,
                }
            decision_result = request_prop_decisions(
                backend, shared=prop_request,
                system_prompt=system_prompts["scene-author-prop-decision"],
                runtime_config=runtime_config, interrupt_callback=interrupt_callback,
            )
            prop_decisions = dict(decision_result.decisions)
            _LOGGER.log(
                logging.INFO if decision_result.status == "transport_valid" else logging.WARNING,
                "[MV Director - Timeline Planner] prop decisions completed; scene=%d; "
                "status=%s; attempts=%d; fallback=%s", scene.scene_number,
                decision_result.status, decision_result.attempts,
                "none" if prop_decisions else "existing_authorship",
            )
            if prop_decisions:
                shared["prop_inventory"] = list(inventory)
                shared["accepted_prop_decisions"] = {
                    str(i): value for i, value in prop_decisions.items()
                }
        performance_prompt = prompts["performance"]
        if prop_decisions:
            performance_prompt += "\n" + system_prompts["prop-performance-addendum"]
        if pending_actions:
            result, issues, retries, missing, recovered = request_entities(
                backend,
                task="scene-author-performance",
                record_type="PERFORMANCE",
                entities=[
                    PlannerEntity(scene.scene_number, (index,), {
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
                system_prompt=performance_prompt,
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
            if composition_timing == "pre_author":
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
        inherited_arc = previous_arc_direction if scene.continuation else None
        camera_shared = {
            **shared,
            "scene_camera": list(direction.camera_direction),
            "arc_roll_policy": CAMERA_ARC_ROLL_POLICIES.get(
                direction.camera_profile_id, "off"
            ),
            "staging_candidates_optional": list(direction.staging_candidates),
            "scene_other": list(direction.other_direction),
            "fixed_cameras": {str(index): value for index, value in fixed_cameras.items()},
            "previous_scene_state": (
                previous_terminal.get("camera", "") if scene.continuation else ""
            ),
            "arc_continuity": {
                "inherited_direction": inherited_arc,
                "scope": "same_direction_through_zoom_static_until_cut",
                "author_camera_has_priority": True,
            },
        }
        camera_states: dict[int, str] = {}
        if pending_cameras:
            result, issues, retries, missing, recovered = request_entities(
                backend,
                task="scene-author-camera",
                record_type="CAMERA",
                entities=[
                    PlannerEntity(scene.scene_number, (index,), {
                        "scene_number": scene.scene_number,
                        "scene": scene.scene_number,
                        "shot": index,
                        "position": positions[index - 1],
                    })
                    for index in pending_cameras
                ],
                shared=camera_shared,
                system_prompt=prompts["camera"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            issue_count += len(issues)
            retried_scenes.update(retries)
            recovered_count += recovered
            if missing:
                return None, tuple(missing)
            for index in pending_cameras:
                camera_texts[index], camera_states[index] = _split_terminal_state(
                    result[(index,)]
                )
            conflicts, _ = inspect_arc_sequence(camera_texts, fixed_cameras, inherited_arc)
            if conflicts:
                _LOGGER.info(
                    "[MV Director - Timeline Planner] Arc direction repair; scene=%d; targets=%s",
                    scene.scene_number, conflicts,
                )
                retried_scenes.add(scene.scene_number)
                repaired, issues, retries, missing, recovered = request_entities(
                    backend, task="scene-author-camera", record_type="CAMERA",
                    entities=[PlannerEntity(scene.scene_number, (index,), {
                        "scene_number": scene.scene_number, "scene": scene.scene_number,
                        "shot": index, "position": positions[index - 1],
                        "required_arc_direction": expected,
                    }) for index, expected in conflicts.items()],
                    shared={
                        **camera_shared, "retry": "arc_direction_only",
                        "arc_direction_targets": {str(i): value for i, value in conflicts.items()},
                        "existing_cameras": {str(i): value for i, value in camera_texts.items()},
                    },
                    system_prompt=prompts["camera"], runtime_config=runtime_config,
                    interrupt_callback=interrupt_callback,
                )
                issue_count += len(issues)
                retried_scenes.update(retries)
                recovered_count += recovered
                for index, expected in conflicts.items():
                    value = repaired.get((index,))
                    if value:
                        prose, state = _split_terminal_state(value)
                        if arc_directions(prose) == {expected}:
                            camera_texts[index], camera_states[index] = prose, state
                            _LOGGER.info(
                                "[MV Director - Timeline Planner] Arc direction repaired; "
                                "scene=%d; shot=%d; direction=%s", scene.scene_number, index, expected,
                            )
                            continue
                    _LOGGER.warning(
                        "[MV Director - Timeline Planner] Arc direction repair unresolved; "
                        "scene=%d; shot=%d; retained original Camera AS IS; expected=%s",
                        scene.scene_number, index, expected,
                    )
            cameras.extend(
                (scene.scene_number, index, camera_texts[index])
                for index in pending_cameras
            )
        _, previous_arc_direction = inspect_arc_sequence(
            camera_texts, fixed_cameras, inherited_arc
        )
        if composition and composition_timing == "post_author":
            if MOTION_COMPOSITION_RESELECTIONS.get(composition_profile) == "guarded_no_drop":
                composition = _reselect_composition(
                    backend, scene=scene, composition=composition,
                    direction=direction, event_texts=event_texts,
                    action_texts=action_texts, camera_texts=camera_texts,
                    system_prompt=system_prompts["scene-author-composition-choice"],
                    runtime_config=runtime_config,
                    interrupt_callback=interrupt_callback,
                    prop_context={key: shared[key] for key in (
                        "prop_inventory", "accepted_prop_decisions",
                    ) if key in shared},
                )
            motion_compositions.append(composition)
        last = len(scene.shots)
        previous_prop_state = prop_decisions.get(last, {}).get("end_state", "")
        previous_terminal = {
            "event": event_states.get(last, ""),
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
        actions=tuple(actions),
        cameras=tuple(cameras),
        issue_count=issue_count,
        retried_scenes=tuple(sorted(retried_scenes)),
        protocol_recovered_count=recovered_count,
        events=tuple(events),
        motion_compositions=tuple(motion_compositions),
        terminal_states=tuple(terminal_states),
        mouth_performances=tuple(
            (scene.scene_number, i.target_concept_id, i.start_ms, i.end_ms, i.state)
            for scene in template.scenes
            for i in (mouth_performances or {}).get(scene.scene_number, scene.mouth_performances)
        ),
    ), ()
