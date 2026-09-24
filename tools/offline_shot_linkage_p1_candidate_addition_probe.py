"""Replay a frozen Event with and without one added user-style staging cue."""

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


def candidate_addition_cases(
    summary: dict, *, scene_number: int, candidate: str,
) -> list[tuple[str, dict]]:
    if not candidate.strip() or "\n" in candidate.strip():
        raise ValueError("Candidate must be one nonempty line")
    calls = []
    for call in summary["trace"]:
        if call["task"] != "scene-author-event":
            continue
        payload = json.loads(call["payload"])
        if payload["scene_number"] == scene_number:
            if call["payload"] != canonical_json(payload):
                raise ValueError("Saved Event request is not canonical")
            calls.append(payload)
    if len(calls) != 1:
        raise ValueError("Expected exactly one saved Scene Event request")
    baseline = calls[0]
    choices = baseline.get("staging_candidates_optional")
    if not isinstance(choices, list) or candidate in choices:
        raise ValueError("Candidate list missing or already contains addition")
    if len(choices) >= 12:
        raise ValueError("Addition would exceed the 12-candidate limit")
    added = {**baseline, "staging_candidates_optional": [*choices, candidate]}
    only_flower = {**baseline, "staging_candidates_optional": [candidate]}
    return [("baseline", baseline), ("added", added), ("only_flower", only_flower)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--system-prompt", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=int, default=4)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--condition", choices=("baseline", "added", "only_flower"),
                        action="append")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    expected_prompt = ROOT / "prompts/experiments/scene_author_p1b_event.txt"
    if args.system_prompt.resolve() != expected_prompt.resolve():
        raise ValueError("Use the frozen P1b v2 Event prompt")
    source_bytes = args.source.read_bytes()
    candidate = args.candidate.read_text(encoding="utf-8").strip()
    cases = candidate_addition_cases(
        json.loads(source_bytes), scene_number=args.scene, candidate=candidate,
    )
    if args.condition:
        cases = [case for case in cases if case[0] in args.condition]
    prompt = args.system_prompt.read_text(encoding="utf-8")
    config = LlamaRuntimeConfig(
        n_ctx=16_384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=args.seed,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = RecordingLifecycle()
    backend = FixedSeedBackend(lifecycle)
    manifest = {
        "purpose": "P1 one added user-style flower staging candidate",
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "system_prompt": str(args.system_prompt),
        "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "candidate": candidate,
        "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "model": str(args.model), "config": asdict(config), "cases": [],
    }
    try:
        lifecycle.ensure_loaded(args.model, config)
        for name, request in cases:
            payload = canonical_json(request)
            started = time.perf_counter()
            response = backend.complete_planner(
                task="scene-author-event", system_prompt=prompt,
                payload=payload, config=config,
            )
            record = {
                "condition": name, "scene": args.scene,
                "candidate_count": len(request["staging_candidates_optional"]),
                "payload": request,
                "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "response": response, "elapsed_seconds": time.perf_counter() - started,
            }
            (args.output / f"{name}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
            manifest["cases"].append({
                key: record[key] for key in (
                    "condition", "candidate_count", "payload_sha256",
                    "response", "elapsed_seconds",
                )
            })
            print(f"condition={name} candidates={record['candidate_count']} "
                  f"elapsed={record['elapsed_seconds']:.2f}s", flush=True)
    finally:
        lifecycle.clear()
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
