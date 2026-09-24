"""Compare frozen Scene Event calls with only optional staging candidates removed.

The saved candidate-on response is the control. This tool never runs H3 or
modifies production Planner output; it records the exact counterfactual input.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import canonical_json
from core.inference import LlamaRuntimeConfig
from tools.offline_section_performance_probe import FixedSeedBackend, RecordingLifecycle


def candidate_off_cases(summary: dict, scenes: tuple[int, ...]) -> list[dict]:
    """Change only the optional candidate list in frozen Event requests."""
    selected: dict[int, dict] = {}
    for call in summary["trace"]:
        if call["task"] != "scene-author-event":
            continue
        original = json.loads(call["payload"])
        scene = original["scene_number"]
        if scene not in scenes:
            continue
        if scene in selected:
            raise ValueError(f"Duplicate saved Event request for Scene {scene}")
        candidates = original.get("staging_candidates_optional")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"No optional candidates in saved Scene {scene}")
        changed = dict(original)
        changed["staging_candidates_optional"] = []
        baseline_payload = canonical_json(original)
        changed_payload = canonical_json(changed)
        if call["payload"] != baseline_payload:
            raise ValueError(f"Saved Event request is not canonical for Scene {scene}")
        selected[scene] = {
            "scene": scene,
            "baseline_response": call["response"],
            "baseline_payload": original,
            "candidate_off_payload": changed,
            "baseline_payload_sha256": hashlib.sha256(baseline_payload.encode()).hexdigest(),
            "candidate_off_payload_sha256": hashlib.sha256(changed_payload.encode()).hexdigest(),
            "candidate_count": len(candidates),
        }
    missing = set(scenes) - set(selected)
    if missing:
        raise ValueError(f"Saved Event requests missing for Scenes {sorted(missing)}")
    return [selected[scene] for scene in scenes]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--system-prompt", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenes", type=int, nargs="+", default=(3, 9))
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    source_bytes = args.source.read_bytes()
    summary = json.loads(source_bytes)
    cases = candidate_off_cases(summary, tuple(args.scenes))
    prompt = args.system_prompt.read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    if args.source.parent.name == "p1b-six-scenes-seed2-v2":
        expected_path = ROOT / "prompts/experiments/scene_author_p1b_event.txt"
        expected = hashlib.sha256(expected_path.read_bytes()).hexdigest()
    else:
        expected_path = ROOT / "prompts/timeline_planner_scene_author_event_system_prompt.txt"
        manifest_path = (
            ROOT / "docs/assets/research/scene-composition-full-sequence-2026-09-23/manifest.json"
        )
        expected = json.loads(manifest_path.read_text(encoding="utf-8"))[
            "p1_prompt_sha256"
        ]["event"]
    if args.system_prompt.resolve() != expected_path.resolve():
        raise ValueError("System Prompt path does not match the saved experiment")
    if prompt_hash != expected:
        raise ValueError("System Prompt differs from frozen P1 Event prompt")
    if not args.prepare_only and args.model is None:
        parser.error("--model is required unless --prepare-only is set")
    args.output.mkdir(parents=True, exist_ok=True)
    config = LlamaRuntimeConfig(
        n_ctx=16_384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=args.seed,
    )
    manifest = {
        "purpose": "P1 candidate-on saved control versus candidate-off Event call",
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "system_prompt": str(args.system_prompt),
        "system_prompt_sha256": prompt_hash,
        "model": str(args.model) if args.model is not None else None,
        "config": asdict(config),
        "prepare_only": args.prepare_only,
        "cases": [],
    }
    lifecycle = RecordingLifecycle()
    backend = FixedSeedBackend(lifecycle)
    try:
        if not args.prepare_only:
            lifecycle.ensure_loaded(args.model, config)
        for case in cases:
            payload = canonical_json(case["candidate_off_payload"])
            record = dict(case)
            record["response"] = None
            record["elapsed_seconds"] = None
            if not args.prepare_only:
                started = time.perf_counter()
                record["response"] = backend.complete_planner(
                    task="scene-author-event", system_prompt=prompt,
                    payload=payload, config=config,
                )
                record["elapsed_seconds"] = time.perf_counter() - started
            (args.output / f"scene{case['scene']}-candidate-off.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest["cases"].append({
                "scene": case["scene"], "candidate_count": case["candidate_count"],
                "baseline_payload_sha256": case["baseline_payload_sha256"],
                "candidate_off_payload_sha256": case["candidate_off_payload_sha256"],
                "response": record["response"],
                "elapsed_seconds": record["elapsed_seconds"],
            })
            print(f"scene={case['scene']} candidates={case['candidate_count']} "
                  f"elapsed={record['elapsed_seconds']}", flush=True)
    finally:
        lifecycle.clear()
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
