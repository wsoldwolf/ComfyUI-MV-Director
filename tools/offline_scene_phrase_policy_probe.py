"""Probe the production Scene Spine prompt on two fixed saved-EMD Scenes.

This is an offline inference experiment. It never rewrites the saved EMD or
invokes H3. The fixture contains reconstructed Cue Cards because the original
intermediate Cue Card responses were not saved.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.scene_spine import (
    build_scene_spine_grammar, parse_scene_spine_step,
    validate_contact_coverage, validate_scene_spine,
)
from core.protocols.llm_records import parse_llm_records


def probe_scene(lifecycle, config, prompt: str, scene: dict, seed: int) -> dict:
    slots = [
        {
            "slot": index,
            "scene_number": scene["scene_number"],
            "shot_index": index,
            "shot_count": len(scene["shots"]),
            "shot_start_ms": shot["start_ms"],
            "shot_end_ms": shot["end_ms"],
            "shot_duration_ms": shot["end_ms"] - shot["start_ms"],
            "lyrics": shot["lyrics"],
            "editorial_role": shot["editorial_role"],
        }
        for index, shot in enumerate(scene["shots"], 1)
    ]
    cue = scene["visual_beat_grounding"]
    payload = {
        "protocol": "MVD_LLM_RECORDS_V1",
        "task": "scene-spine",
        "scene_number": scene["scene_number"],
        "scene_start_ms": scene["start_ms"],
        "scene_end_ms": scene["end_ms"],
        "lyric_lines": list(dict.fromkeys(
            lyric["text"] for shot in scene["shots"] for lyric in shot["lyrics"]
        )),
        "author_body": [],
        "visual_beat_grounding": cue,
        "body_phrase_policy": "scene_phrase",
        "track_external_effect": scene["track_external_effect"],
        "spine_event_kind": "non_contact_change",
        "scene_continuation": True,
        "entry_body_state": scene["entry_body_state"],
        "entry_effect_state": "",
        "slots": slots,
    }
    grammar = build_scene_spine_grammar(
        slots,
        allow_target_hands=cue["contact"] == "許可",
        track_external_effect=scene["track_external_effect"],
        body_phrase_only=cue["target"] == "なし",
    )
    started = time.perf_counter()
    raw = lifecycle.complete_chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "/no_think\n" + json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )},
        ],
        replace(config, seed=seed), grammar=grammar,
    )
    parsed = parse_llm_records(
        raw,
        allowed_slots={"SPINE": frozenset(range(1, len(slots) + 1))},
        required=frozenset(("SPINE", index) for index in range(1, len(slots) + 1)),
    )
    record = {
        "scene_number": scene["scene_number"],
        "seed": seed,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "payload": payload,
        "raw": raw,
        "protocol_issues": [issue.reason for issue in parsed.issues],
        "missing": [list(item) for item in parsed.missing],
    }
    try:
        if record["protocol_issues"] or record["missing"]:
            raise ValueError("line protocol invalid")
        texts = {item.slot: item.text for item in parsed.records}
        steps = tuple(
            parse_scene_spine_step(texts[index])
            for index in range(1, len(slots) + 1)
        )
        validate_scene_spine(steps)
        validate_contact_coverage(steps, contact_allowed=False)
        if scene["track_external_effect"] and any(not step.effect_to for step in steps):
            raise ValueError("external effect endpoint missing")
        record["steps"] = [step.to_dict() for step in steps]
        record["valid"] = True
    except ValueError as error:
        record["valid"] = False
        record["validation_error"] = str(error)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--gpu-layers", type=int, default=-1)
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    prompt = (ROOT / "prompts/timeline_planner_scene_spine_system_prompt.txt").read_text(
        encoding="utf-8"
    )
    body_prompt = (
        ROOT / "prompts/timeline_planner_scene_spine_body_system_prompt.txt"
    ).read_text(encoding="utf-8")
    config = LlamaRuntimeConfig(
        n_ctx=8192, max_tokens=768, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=args.gpu_layers,
        n_batch=512, keep_model_loaded=False,
    )
    evidence = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "source_emd": fixture["source_emd"],
        "cue_provenance": fixture["cue_provenance"],
        "model": str(args.model.resolve()),
        "model_size": args.model.stat().st_size,
        "scene_spine_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "scene_spine_body_prompt_sha256": hashlib.sha256(
            body_prompt.encode("utf-8")
        ).hexdigest(),
        "runtime": config.to_dict(),
        "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            for scene in fixture["scenes"]:
                print(f"seed={seed} scene={scene['scene_number']} started", flush=True)
                selected_prompt = (
                    body_prompt
                    if scene["visual_beat_grounding"]["target"] == "なし"
                    else prompt
                )
                result = probe_scene(lifecycle, config, selected_prompt, scene, seed)
                evidence["runs"].append(result)
                args.output.write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"seed={seed} scene={scene['scene_number']} "
                    f"elapsed={result['elapsed_seconds']}s valid={result['valid']}",
                    flush=True,
                )
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
