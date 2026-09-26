"""Public Timeline Planner entry points and completed-EMD rendering."""

from __future__ import annotations

from typing import Any, Mapping

from ..artifacts import DirectionArtifact, EMDTextArtifact
from ..inference import LlamaRuntimeConfig
from .errors import TimelinePlannerError
from .candidate_policy import validate_staging_candidate_policy
from .scene_author import generate_scene_author_content
from .renderer import render_completed_emd
from .template import (
    PlannerTemplate, normalize_concept_emd, normalize_scene_emd, parse_template_emd,
)
from .types import PlannerContent, TimelinePlannerBackend, TimelinePlannerResult

PLANNER_ALGORITHM_VERSION = "mvd-scene-author-v1-gemma31b"


def generate_planner_content(
    backend: TimelinePlannerBackend,
    *,
    template: PlannerTemplate,
    concept_emd: str,
    direction: DirectionArtifact,
    lip_sync_mode: str,
    lip_sync_target: str,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    scene_emd: str = "",
    staging_candidate_policy: str = "optional",
    interrupt_callback: Any = None,
) -> tuple[PlannerContent | None, tuple[tuple[str, int, int], ...]]:
    """Generate one coherent Scene at a time; there is no legacy strategy."""
    validate_staging_candidate_policy(staging_candidate_policy)
    if lip_sync_mode not in {"off", "context_loop", "audio_reference", "lyrics"}:
        raise TimelinePlannerError("unknown lip_sync_mode")
    direction.validate()
    runtime_config.validate()
    required = {"scene-author-event", "scene-author-performance", "scene-author-camera"}
    if not required.issubset(system_prompts) or any(
        not system_prompts[key].strip() for key in required
    ):
        raise TimelinePlannerError("Scene Author Event, Performance and Camera prompts are required")
    return generate_scene_author_content(
        backend, template=template, concept_emd=concept_emd,
        scene_emd=scene_emd, direction=direction,
        system_prompts=system_prompts, runtime_config=runtime_config,
        staging_candidate_policy=staging_candidate_policy,
        interrupt_callback=interrupt_callback,
    )


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
    return render_completed_emd(
        concept_emd=concept_emd,
        scene_emd=scene_emd,
        template=template,
        direction=direction,
        actions={(scene, shot): text for scene, shot, text in content.actions},
        cameras={(scene, shot): text for scene, shot, text in content.cameras},
        events={(scene, shot): text for scene, shot, text in content.events},
        typed_output=True,
        motion_compositions={(s, shot): (source, index, text)
                             for s, shot, source, index, text in content.motion_compositions},
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
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    scene_emd: str = "",
    staging_candidate_policy: str = "optional",
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
        system_prompts=system_prompts,
        runtime_config=runtime_config,
        staging_candidate_policy=staging_candidate_policy,
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
