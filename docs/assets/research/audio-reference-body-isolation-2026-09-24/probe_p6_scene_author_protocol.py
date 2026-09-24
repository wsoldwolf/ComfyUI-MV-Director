"""Research-only replay of saved Scene Author requests with production grammar.

This script does not alter generated EMD, plans, or ComfyUI caches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.scene_author import build_scene_author_grammar
from core.protocols import parse_llm_records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top-p", type=float, default=0.9)
    args = parser.parse_args()

    prompt_path = ROOT / "prompts/timeline_planner_scene_author_performance_system_prompt.txt"
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    requests = []
    for path in args.summary:
        summary = json.loads(path.read_text(encoding="utf-8"))
        entry = next(
            row for row in summary["trace"]
            if row["task"] == "scene-author-performance"
        )
        payload = entry["payload"]
        requests.append({
            "source": str(path),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "payload": payload,
            "request": json.loads(payload),
        })

    config = LlamaRuntimeConfig(
        n_ctx=8192, max_tokens=1536, n_batch=512, gpu_layers=-1,
        temperature=args.temperature, top_p=args.top_p,
        keep_model_loaded=False,
    )
    result = {
        "scope": "research_only_saved_scene_author_performance_replay",
        "model": str(args.model),
        "model_size": args.model.stat().st_size,
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "runtime": config.to_dict(),
        "runs": [],
    }
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for source in requests:
            request = source["request"]
            slots = request["slots"]
            allowed = frozenset(int(slot["slot"]) for slot in slots)
            grammar = build_scene_author_grammar("scene-author-performance", slots)
            for seed in args.seeds:
                active = LlamaRuntimeConfig(**{**config.to_dict(), "seed": seed})
                started = time.perf_counter()
                print(
                    f"scene={request['scene_number']} seed={seed} started",
                    flush=True,
                )
                response = lifecycle.complete_chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "/no_think\n" + source["payload"]},
                    ],
                    active,
                    grammar=grammar,
                )
                parsed = parse_llm_records(
                    response,
                    allowed_slots={"PERFORMANCE": allowed},
                    required=frozenset(("PERFORMANCE", slot) for slot in allowed),
                )
                result["runs"].append({
                    "scene": request["scene_number"],
                    "seed": seed,
                    "source": source["source"],
                    "source_sha256": source["source_sha256"],
                    "payload_sha256": hashlib.sha256(source["payload"].encode()).hexdigest(),
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
                    f"scene={request['scene_number']} seed={seed} "
                    f"issues={len(parsed.issues)} missing={len(parsed.missing)}",
                    flush=True,
                )
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    main()
