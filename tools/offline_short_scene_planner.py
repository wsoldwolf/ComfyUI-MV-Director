"""Run the production Planner on one isolated, saved-EMD-derived Scene.

This is a bounded EMD-stage experiment, not an audio/H3 render. Local Scene
time is rebased to zero; the saved Scene's original context is not fully
reconstructed, so the result is a structural/acting probe only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import DirectionArtifact
from core.direction.profiles import (
    CAMERA_PROFILES, MOTION_PROFILES, STYLE_PROFILES,
)
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner import plan_timeline
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts


def stamp(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    minutes, rest = divmod(milliseconds, 60_000)
    seconds, fraction = divmod(rest, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{fraction:03d}"


def template_from_scene(scene: dict) -> str:
    start = scene["start_ms"]
    length = scene["end_ms"] - start
    h3_lengths = {5: 243, 9: 260}
    rows = [
        "> " + chr(96) + "シーン" + chr(96) + " 1",
        f"# シーン 00:00.000 --> {stamp(length)}",
        f"* " + chr(96) + "H3長" + chr(96) + f" {h3_lengths[scene['scene_number']]}",
    ]
    for shot in scene["shots"]:
        for lyric in shot["lyrics"]:
            rows += [
                "> " + chr(96) + "セクション" + chr(96) + f" {lyric['section']}",
                "> " + chr(96) + "歌詞開始" + chr(96)
                + f" {stamp(lyric['start_ms'] - start)}",
                "> " + chr(96) + "歌詞終了" + chr(96)
                + f" {stamp(min(length, lyric['end_ms'] - start))}",
                "> " + chr(96) + "歌詞" + chr(96) + f" {lyric['text']}",
            ]
        rows += [
            f"## ショット {stamp(shot['start_ms'] - start)}",
            "* 未計画",
        ]
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--scene", type=int, choices=(5, 9), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    scene = next(
        item for item in fixture["scenes"]
        if item["scene_number"] == args.scene
    )
    template = template_from_scene(scene)
    config = LlamaRuntimeConfig(
        n_ctx=16_384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=args.seed,
    )
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    direction = DirectionArtifact(
        style_direction=(STYLE_PROFILES["anime_emotional_mv"],),
        motion_direction=(MOTION_PROFILES["anime_scene_phrase_mv"],),
        camera_direction=(CAMERA_PROFILES["anime_emotional_mv"],),
        style_profile_id="anime_emotional_mv",
        motion_profile_id="anime_scene_phrase_mv",
        camera_profile_id="anime_emotional_mv",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "template.md").write_text(template, encoding="utf-8")
    try:
        lifecycle.ensure_loaded(args.model, config)
        result = plan_timeline(
            backend, template_emd=template,
            concept_emd="# サブジェクト\n* 狐耳と狐尻尾のある一人の歌唱者。\n",
            direction=direction,
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts=_system_prompts(), runtime_config=config,
        )
        summary = {
            "source_emd": fixture["source_emd"],
            "source_scene": args.scene,
            "local_time_rebased": True,
            "seed": args.seed,
            "complete": result.complete,
            "missing": [list(item) for item in result.missing],
            "task_calls": backend._task_calls,
            "actions": list(result.content.actions) if result.content else [],
            "cameras": list(result.content.cameras) if result.content else [],
            "scene_spine_steps": (
                list(result.content.scene_spine_steps) if result.content else []
            ),
        }
        (args.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if result.complete:
            (args.output / "planned.md").write_text(result.emd.text, encoding="utf-8")
        print(
            f"scene={args.scene} complete={result.complete} "
            f"missing={result.missing} calls={backend._task_calls}",
            flush=True,
        )
    finally:
        lifecycle.clear()
    return 0 if result.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
