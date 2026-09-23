"""Run a frozen prefix of the full song with fixed effective seed per LLM call.

This is an EMD-only Scene continuity probe; it does not render H3 video.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import DirectionArtifact, canonical_json
from core.inference import LlamaRuntimeConfig
from core.planner import plan_timeline
from nodes.node_timeline_planner.node import _system_prompts
from tools.offline_section_performance_probe import FixedSeedBackend, RecordingLifecycle


class NoPerformanceStateBackend(FixedSeedBackend):
    """Offline control: suppress only cross-Scene body state, not other inputs."""

    def complete_planner(self, *, task, payload, **kwargs):
        if task == "scene-author-performance":
            request = json.loads(payload)
            request["previous_scene_state"] = ""
            payload = canonical_json(request)
        return super().complete_planner(task=task, payload=payload, **kwargs)


class NoPreviousStateBackend(FixedSeedBackend):
    """Offline control: suppress all cross-Scene state, preserving local inputs."""

    def complete_planner(self, *, task, payload, **kwargs):
        if task.startswith("scene-author-"):
            request = json.loads(payload)
            request["previous_scene_state"] = ""
            payload = canonical_json(request)
        return super().complete_planner(task=task, payload=payload, **kwargs)


def p1b_request(task: str, request: dict) -> dict:
    """Offline-only role contract: prior frame is a boundary, lyrics drive change."""
    if not task.startswith("scene-author-"):
        return request
    value = dict(request)
    value.pop("previous_scene_state", None)
    value["start_condition"] = {
        "continuation": bool(value["continuation"]),
        "source": "previous_video_frame" if value["continuation"] else "new_scene",
    }
    value["current_lyric_focus"] = [
        {"shot": shot["shot"], "lines": [line["text"] for line in shot["lyrics"]]}
        for shot in value["original_lyrics"]
    ]
    if task == "scene-author-event":
        # Subject appearance is not evidence for an external Scene event.
        value.pop("subject_emd", None)
    elif task == "scene-author-performance":
        count = len(value["shot_positions"])
        value["shot_progression"] = [
            {"shot": index, "role": (
                "single_phrase" if count == 1 else
                "trigger" if index == 1 else
                "carry_forward" if index == count else "development"
            )}
            for index in range(1, count + 1)
        ]
    return value


class P1bBackend(FixedSeedBackend):
    """Pilot contract in the existing three calls; no new inference stage."""

    def complete_planner(self, *, task, payload, **kwargs):
        request = p1b_request(task, json.loads(payload))
        return super().complete_planner(
            task=task, payload=canonical_json(request), **kwargs,
        )


def scene_prefix(template: str, count: int) -> str:
    starts = [line for line in template.splitlines(keepends=True) if line.startswith("> `シーン` ")]
    if count < 1 or count > len(starts):
        raise ValueError("scene count outside frozen template")
    marker = starts[count] if count < len(starts) else None
    if marker is None:
        return template
    boundary = template.find(marker)
    return template[:boundary].rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenes", type=int, default=4)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--omit-performance-state", action="store_true")
    parser.add_argument("--omit-all-states", action="store_true")
    parser.add_argument("--p1b", action="store_true")
    parser.add_argument("--p1b-event-variant", choices=("v1", "v2"), default="v2")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    args.output.mkdir(parents=True, exist_ok=True)
    template = scene_prefix((args.fixture / "template.md").read_text(encoding="utf-8"), args.scenes)
    concept = (args.fixture / "concept.md").read_text(encoding="utf-8")
    scene = (args.fixture / "scene.md").read_text(encoding="utf-8")
    direction = DirectionArtifact.from_dict(json.loads((args.fixture / "direction.json").read_text(encoding="utf-8")))
    config = LlamaRuntimeConfig(
        n_ctx=16_384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=args.seed,
    )
    lifecycle = RecordingLifecycle()
    if sum((args.omit_performance_state, args.omit_all_states, args.p1b)) > 1:
        raise ValueError("Choose only one experimental contract")
    backend_type = (P1bBackend if args.p1b else
                    NoPreviousStateBackend if args.omit_all_states else
                    NoPerformanceStateBackend if args.omit_performance_state else
                    FixedSeedBackend)
    backend = backend_type(lifecycle)
    prompts = _system_prompts()
    if args.p1b:
        for stage in ("event", "performance", "camera"):
            suffix = "_v1" if stage == "event" and args.p1b_event_variant == "v1" else ""
            prompts[f"scene-author-{stage}"] = (
                ROOT / f"prompts/experiments/scene_author_p1b_{stage}{suffix}.txt"
            ).read_text(encoding="utf-8")
    result = None
    failure = None
    try:
        lifecycle.ensure_loaded(args.model, config)
        result = plan_timeline(
            backend, template_emd=template, concept_emd=concept, scene_emd=scene,
            direction=direction, lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts=prompts, runtime_config=config,
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        lifecycle.clear()
    summary = {
        "scene_count": args.scenes,
        "seed": args.seed,
        "fixed_call_seed": True,
        "omit_performance_state": args.omit_performance_state,
        "omit_all_states": args.omit_all_states,
        "p1b": args.p1b,
        "p1b_event_variant": args.p1b_event_variant if args.p1b else None,
        "model": args.model.name,
        "complete": result.complete if result is not None else False,
        "missing": [list(row) for row in result.missing] if result is not None else [],
        "failure": failure,
        "task_calls": backend._task_calls,
        "trace": backend.trace,
        "content": result.content.to_dict() if result is not None and result.content else None,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "template.md").write_text(template, encoding="utf-8")
    if result is not None and result.complete:
        (args.output / "planned.md").write_text(result.emd.text, encoding="utf-8")
    print(f"scenes={args.scenes} complete={summary['complete']} calls={backend._task_calls} failure={failure}", flush=True)
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
