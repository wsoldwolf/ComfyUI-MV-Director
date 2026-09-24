"""Test whether reading two original lyric lines as one phrase changes Event choice.

This is an Event-only offline experiment. The source lyric rows and timestamps
are never moved, and neither Planner output nor H3 video is generated.
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


def completed_phrase_cases(
    summary: dict, *, scene_number: int, shot_number: int,
    source_lines: tuple[str, ...],
) -> list[tuple[str, dict]]:
    """The only condition difference is the completed_lyric_phrase value."""
    calls = []
    for call in summary["trace"]:
        if call["task"] != "scene-author-event":
            continue
        request = json.loads(call["payload"])
        if request["scene_number"] == scene_number:
            if call["payload"] != canonical_json(request):
                raise ValueError("Saved Event request is not canonical")
            calls.append(request)
    if len(calls) != 1:
        raise ValueError("Expected exactly one saved Event request")
    original = calls[0]
    if "completed_lyric_phrase" in original:
        raise ValueError("Saved Event request already contains a phrase")
    shots = [row for row in original["original_lyrics"] if row["shot"] == shot_number]
    if len(shots) != 1:
        raise ValueError("Expected exactly one matching lyric Shot")
    lines = [row["text"] for row in shots[0]["lyrics"]]
    positions = [index for index in range(len(lines) - len(source_lines) + 1)
                 if tuple(lines[index:index + len(source_lines)]) == source_lines]
    if len(positions) != 1:
        raise ValueError("Phrase must occur once as contiguous lines in one Shot")
    phrase = {"shot": shot_number, "source_lines": list(source_lines),
              "text": "".join(source_lines)}
    empty = {**original, "completed_lyric_phrase": []}
    filled = {**original, "completed_lyric_phrase": [phrase]}
    text_only = {**original, "completed_lyric_phrase": [{"text": "".join(source_lines)}]}
    return [("empty", empty), ("joined", filled), ("text_only", text_only)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--system-prompt", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=int, default=4)
    parser.add_argument("--shot", type=int, default=2)
    parser.add_argument("--line", dest="lines", action="append", required=True)
    parser.add_argument("--condition", choices=("empty", "joined", "text_only"),
                        action="append")
    parser.add_argument("--seed", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    if args.system_prompt.resolve() != (
        ROOT / "prompts/experiments/scene_author_completed_phrase_event.txt"
    ).resolve():
        raise ValueError("Use the fixed completed-phrase experimental prompt")
    source_bytes = args.source.read_bytes()
    cases = completed_phrase_cases(
        json.loads(source_bytes), scene_number=args.scene,
        shot_number=args.shot, source_lines=tuple(args.lines),
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
        "purpose": "P1 completed lyric phrase, empty versus joined",
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "system_prompt": str(args.system_prompt),
        "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
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
                "condition": name, "scene": args.scene, "shot": args.shot,
                "payload": request, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "response": response, "elapsed_seconds": time.perf_counter() - started,
            }
            (args.output / f"{name}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
            manifest["cases"].append({
                key: record[key] for key in (
                    "condition", "payload_sha256", "response", "elapsed_seconds"
                )
            })
            print(f"condition={name} elapsed={record['elapsed_seconds']:.2f}s", flush=True)
    finally:
        lifecycle.clear()
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
