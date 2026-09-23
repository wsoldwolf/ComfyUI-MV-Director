"""Deterministic completed-EMD renderer for Timeline Planner."""

from __future__ import annotations

import re
import logging
import hashlib
from typing import Mapping

from ..artifacts import DirectionArtifact, EMDTextArtifact
from ..direction.profiles import (
    STYLE_RETENTION_POLICIES,
    STYLE_SCENE_REINFORCEMENTS,
    render_profile_direction,
)
from ..emd import parse_emd
from ..h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
from ..lyrics import format_emd_time
from .errors import TimelinePlannerError
from .template import PlannerTemplate
from .text_normalization import strip_generated_line_continuation


_TARGET_RE = re.compile(r"サブジェクト[1-4]\Z")
_LOGGER = logging.getLogger("mv_director.nodes")


def _concept_subject_count(concept_emd: str) -> int:
    return sum(
        1
        for line in concept_emd.rstrip().split("\n")
        if line.startswith("* ")
    )


def render_completed_emd(
    *,
    concept_emd: str,
    template: PlannerTemplate,
    direction: DirectionArtifact,
    actions: Mapping[tuple[int, int], str],
    cameras: Mapping[tuple[int, int], str],
    events: Mapping[tuple[int, int], str] | None = None,
    typed_output: bool = False,
    motion_compositions: Mapping[tuple[int, int], tuple[str, int, str]] | None = None,
    lip_sync_mode: str,
    lip_sync_target: str,
    lip_sync_audio_slot: int,
    scene_emd: str = "",
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> EMDTextArtifact:
    direction.validate()
    if lip_sync_mode not in {"off", "context_loop", "audio_reference", "lyrics"}:
        raise TimelinePlannerError("unknown lip_sync_mode")
    if not _TARGET_RE.fullmatch(lip_sync_target):
        raise TimelinePlannerError("lip_sync_target must be サブジェクト1..4")
    if not isinstance(lip_sync_audio_slot, int) or isinstance(lip_sync_audio_slot, bool) or not 1 <= lip_sync_audio_slot <= 3:
        raise TimelinePlannerError("lip_sync_audio_slot must be in 1..3")

    lines = concept_emd.rstrip().split("\n")
    if scene_emd.strip():
        lines.extend(("", *scene_emd.rstrip().split("\n")))
    style_profile = direction.style_profile_id
    retention_policy = (
        STYLE_RETENTION_POLICIES.get(style_profile, "")
        if direction.retention_policy == "profile"
        else ""
    )
    scene_reinforcement = STYLE_SCENE_REINFORCEMENTS.get(
        style_profile, ""
    )
    if direction.retention_policy == "passthrough":
        lines.extend(("", "# 保持分析"))
        lines.extend(f"* {value}" for value in direction.retention_lines)
    elif retention_policy:
        lines.extend(("", "# 保持分析"))
        lines.extend(
            f"* `サブジェクト{index}`: {retention_policy}"
            for index in range(1, _concept_subject_count(concept_emd) + 1)
        )
    common = (
        ("スタイル", direction.style_direction),
        ("環境", direction.environment_direction),
        ("時間・照明", direction.time_lighting_direction),
        ("モーション", render_profile_direction("motion", direction.motion_profile_id, direction.motion_direction)),
        ("カメラ", render_profile_direction("camera", direction.camera_profile_id, direction.camera_direction)),
        ("その他", direction.other_direction),
    )
    if any(values for _, values in common):
        lines.extend(("", "# 共通プロンプト"))
        for heading, values in common:
            if values:
                lines.append(f"## {heading}")
                lines.extend(f"* {value}" for value in values)

    cleaned_generated_lines = 0
    event_values = events or {}
    for scene in template.scenes:
        continuation = " 継続" if scene.continuation else ""
        lines.extend(
            (
                "",
                f"> `シーン` {scene.scene_number}",
                f"# シーン {format_emd_time(scene.start_ms)} --> {format_emd_time(scene.end_ms)}{continuation}",
                f"* `H3長` {scene.h3_length}",
            )
        )
        lines.extend(f"* {value}" for value in scene.descriptions)
        scene_has_lyrics = any(shot.lyric_annotations for shot in scene.shots)
        for shot_index, shot in enumerate(scene.shots, 1):
            for lyric in shot.lyric_annotations:
                if lyric.section is not None:
                    lines.append(f"> `セクション` {lyric.section}")
                if lyric.start_ms is not None and lyric.end_ms is not None:
                    lines.extend(
                        (
                            f"> `歌詞開始` {format_emd_time(lyric.start_ms)}",
                            f"> `歌詞終了` {format_emd_time(lyric.end_ms)}",
                        )
                    )
                lines.append(f"> `歌詞` {lyric.text}")
            lines.append(f"## ショット {format_emd_time(shot.start_ms)}")
            author_body = [value for value in shot.body if value != "未計画"]
            body = [*author_body]
            fixed_kinds = {directive.kind for directive in shot.directives}
            event = event_values.get((scene.scene_number, shot_index), "").strip()
            action = actions.get((scene.scene_number, shot_index), "").strip()
            camera = cameras.get((scene.scene_number, shot_index), "").strip()
            if typed_output:
                if event and "演出" not in fixed_kinds:
                    body.append(f"`演出` {event}")
                if action and "演技" not in fixed_kinds:
                    body.append(f"`演技` {action}")
                    composition = (motion_compositions or {}).get((scene.scene_number, shot_index))
                    if composition:
                        source, index, supplement = composition
                        digest = hashlib.sha256(supplement.encode("utf-8")).hexdigest()
                        lines.append(f"> `モーション補完` source={source} template={index} sha256={digest}")
                        body.append(f"`演技` {supplement}")
                if camera and "カメラ" not in fixed_kinds:
                    body.append(f"`カメラ` {camera}")
                action = ""
                camera = ""
            cleaned_action = strip_generated_line_continuation(action)
            cleaned_camera = strip_generated_line_continuation(camera)
            cleaned_generated_lines += int(cleaned_action != action) + int(cleaned_camera != camera)
            action, camera = cleaned_action, cleaned_camera
            if action:
                body.append(action)
            if camera:
                body.append(camera)
            if shot_index == 1 and scene_reinforcement:
                body.append(scene_reinforcement)
            if not body:
                body.append("未計画")
            lines.extend(f"* {value}" for value in body)
            if lip_sync_mode == "lyrics":
                lines.extend(
                    f"* `リップシンク` `歌詞` `{lip_sync_target}` 「{lyric.text}」"
                    for lyric in shot.lyric_annotations
                )
        if lip_sync_mode == "context_loop" or (
            scene_has_lyrics and lip_sync_mode == "audio_reference"
        ):
            lines.append("## 音響")
            if lip_sync_mode == "context_loop":
                lines.append(f"* `リップシンク` `Context Loop` `{lip_sync_target}`")
            else:
                lines.append(
                    f"* `リップシンク` `Audio参照` `{lip_sync_target}` `音声{lip_sync_audio_slot}`"
                )
    if cleaned_generated_lines:
        _LOGGER.info(
            "[MV Director - Timeline Planner] removed standalone trailing backslash at EMD render; lines=%d",
            cleaned_generated_lines,
        )
    text = "\n".join(lines) + "\n"
    try:
        parse_emd(text, timing_profile=timing_profile)
    except Exception as exc:
        raise TimelinePlannerError(f"Planner rendered invalid completed EMD: {exc}") from exc
    return EMDTextArtifact.create("MVD_EMD_V1", text)
