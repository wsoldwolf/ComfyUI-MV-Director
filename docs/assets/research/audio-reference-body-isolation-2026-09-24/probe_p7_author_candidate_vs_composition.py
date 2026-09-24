"""Research-only 2x2 replay of user candidate and Python motion composition."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from core.artifacts.base import canonical_json
from core.direction.enhancer import split_staging_directives
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.scene_author import build_scene_author_grammar
from core.protocols import parse_llm_records


def saved_payload(scene: int, composition: bool) -> dict[str, object]:
    path = (
        ROOT / "docs/assets/research/motion-composition-2026-09-23/fixed-seed"
        / f"scene{scene}-{'on' if composition else 'off'}/summary.json"
    )
    summary = json.loads(path.read_text(encoding="utf-8"))
    entry = next(
        item for item in summary["trace"]
        if item["task"] == "scene-author-performance"
    )
    return json.loads(entry["payload"])


def candidate_for(scene: int, style: str) -> tuple[str, str]:
    path = (
        ROOT / "docs/assets/research/audio-reference-body-isolation-2026-09-24"
        / f"p7-scene{scene}-user-request{'' if style == 'original' else '-compact'}.md"
    )
    source = path.read_text(encoding="utf-8")
    common, candidates = split_staging_directives(source)
    if common or len(candidates) != 1:
        raise ValueError("candidate fixture must contain exactly one plan-only line")
    return candidates[0], hashlib.sha256(source.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--candidate-style", choices=("original", "compact"), default="original")
    parser.add_argument("--candidate-only", action="store_true")
    args = parser.parse_args()

    prompt_path = ROOT / "prompts/timeline_planner_scene_author_performance_system_prompt.txt"
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    config = LlamaRuntimeConfig(
        n_ctx=8192, max_tokens=1536, n_batch=512, gpu_layers=-1,
        temperature=0.1, top_p=0.9, keep_model_loaded=False,
    )
    result = {
        "scope": "research_only_saved_performance_input_candidate_by_composition",
        "model": str(args.model),
        "model_size": args.model.stat().st_size,
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "runtime": config.to_dict(),
        "candidate_style": args.candidate_style,
        "runs": [],
    }
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene in (5, 9):
            candidate, candidate_sha = candidate_for(scene, args.candidate_style)
            for seed in args.seeds:
                for composition in (False, True):
                    for injected in ((True,) if args.candidate_only else (False, True)):
                        request = saved_payload(scene, composition)
                        request["staging_candidates_optional"] = (
                            [candidate] if injected else []
                        )
                        payload = canonical_json(request)
                        grammar = build_scene_author_grammar(
                            "scene-author-performance", request["slots"]
                        )
                        active = LlamaRuntimeConfig(
                            **{**config.to_dict(), "seed": seed}
                        )
                        started = time.perf_counter()
                        print(
                            f"scene={scene} seed={seed} composition={composition} "
                            f"candidate={injected} started", flush=True,
                        )
                        response = lifecycle.complete_chat(
                            [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": "/no_think\n" + payload},
                            ],
                            active,
                            grammar=grammar,
                        )
                        allowed = frozenset(
                            int(slot["slot"]) for slot in request["slots"]
                        )
                        parsed = parse_llm_records(
                            response,
                            allowed_slots={"PERFORMANCE": allowed},
                            required=frozenset(
                                ("PERFORMANCE", slot) for slot in allowed
                            ),
                        )
                        result["runs"].append({
                            "scene": scene,
                            "seed": seed,
                            "composition": composition,
                            "candidate": injected,
                            "candidate_sha256": candidate_sha,
                            "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                            "response": response,
                            "parsed": parsed.to_dict(),
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                        })
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(
                            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        print(
                            f"scene={scene} seed={seed} composition={composition} "
                            f"candidate={injected} issues={len(parsed.issues)} "
                            f"missing={len(parsed.missing)}", flush=True,
                        )
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    main()
