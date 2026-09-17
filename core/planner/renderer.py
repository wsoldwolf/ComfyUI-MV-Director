"""Deterministic completed-EMD renderer for Timeline Planner."""

from __future__ import annotations

import re
from typing import Mapping

from ..artifacts import DirectionArtifact, EMDTextArtifact
from ..direction.profiles import (
    STYLE_RETENTION_POLICIES,
    STYLE_SCENE_REINFORCEMENTS,
)
from ..emd import parse_emd
from ..h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
from ..lyrics import format_emd_time
from .errors import TimelinePlannerError
from .template import PlannerTemplate


_TARGET_RE = re.compile(r"サブジェクト[1-4]\Z")


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
    lip_sync_mode: str,
    lip_sync_target: str,
    lip_sync_audio_slot: int,
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
        ("モーション", direction.motion_direction),
        ("カメラ", direction.camera_direction),
        ("その他", direction.other_direction),
    )
    if any(values for _, values in common):
        lines.extend(("", "# 共通プロンプト"))
        for heading, values in common:
            if values:
                lines.append(f"## {heading}")
                lines.extend(f"* {value}" for value in values)

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
            action = actions.get((scene.scene_number, shot_index), "").strip()
            camera = cameras.get((scene.scene_number, shot_index), "").strip()
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
    text = "\n".join(lines) + "\n"
    try:
        parse_emd(text, timing_profile=timing_profile)
    except Exception as exc:
        raise TimelinePlannerError(f"Planner rendered invalid completed EMD: {exc}") from exc
    return EMDTextArtifact.create("MVD_EMD_V1", text)
