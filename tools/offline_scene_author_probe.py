"""Run an isolated saved Scene through the opt-in three-stage Planner path.

The local time rebasing means this is an EMD-stage comparison, not a production
run or an H3 quality claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import DirectionArtifact
from core.direction.profiles import CAMERA_PROFILES, MOTION_PROFILES, STYLE_PROFILES
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner import plan_timeline
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts
from tools.offline_short_scene_planner import template_from_scene


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--scene", type=int, choices=(5, 9), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    scene = next(row for row in fixture["scenes"] if row["scene_number"] == args.scene)
    template = template_from_scene(scene)
    config = LlamaRuntimeConfig(
        n_ctx=16_384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=args.seed,
    )
    direction = DirectionArtifact(
        style_direction=(STYLE_PROFILES["anime_emotional_mv"],),
        motion_direction=(MOTION_PROFILES["anime_scene_author_mv"],),
        camera_direction=(CAMERA_PROFILES["anime_emotional_mv"],),
        style_profile_id="anime_emotional_mv",
        motion_profile_id="anime_scene_author_mv",
        camera_profile_id="anime_emotional_mv",
    )
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "template.md").write_text(template, encoding="utf-8")
    try:
        lifecycle.ensure_loaded(args.model, config)
        result = plan_timeline(
            backend,
            template_emd=template,
            concept_emd="# サブジェクト\n* 狐耳と狐尻尾のある一人の歌唱者。\n",
            direction=direction,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=1,
            system_prompts=_system_prompts(),
            runtime_config=config,
        )
        summary = {
            "source_emd": fixture["source_emd"],
            "source_scene": args.scene,
            "local_time_rebased": True,
            "seed": args.seed,
            "model": args.model.name,
            "complete": result.complete,
            "missing": [list(item) for item in result.missing],
            "task_calls": backend._task_calls,
            "trace": backend.trace,
            "events": list(result.content.events) if result.content else [],
            "performances": list(result.content.actions) if result.content else [],
            "cameras": list(result.content.cameras) if result.content else [],
        }
        (args.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if result.complete:
            (args.output / "planned.md").write_text(
                result.emd.text, encoding="utf-8",
            )
        print(
            f"scene={args.scene} complete={result.complete} "
            f"missing={result.missing} calls={backend._task_calls}",
            flush=True,
        )
        return 0 if result.complete else 1
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    raise SystemExit(main())
