"""Research-only: ask the actual 8B to condense saved Scene prose.

This does not change the Planner/Compiler and does not patch an H3 Plan.
The saved EMD actions are input evidence, so this tests compression and
temporal expression, not de-novo story selection.
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

from core.emd.parser import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig


SYSTEM = """You write a short Japanese visual specification for one music-video Scene.
Use only the supplied lyrics, location, and existing actions as evidence. Do not invent
a new object, action, location, or effect. Preserve the visible relationship between
the lyric subject, its change, and the performer's reaction. Do not describe camera
movement. Return exactly these records, one per line and no commentary:
SCENE|one short sentence about the location, visible event, and performer
ACTION|1|one short sentence for Shot 1
If Shot 2 is present, add ACTION|2|one short sentence for Shot 2.
Do not copy a line verbatim from the input. Do not include a pipe in the prose.
"""


def payload_for_scene(scene) -> dict[str, object]:
    lyrics = []
    for shot in scene.shots:
        for lyric in shot.lyric_annotations:
            if lyric.text not in lyrics:
                lyrics.append(lyric.text)
    return {
        "scene_number": scene.scene_number,
        "section": next((lyric.section for shot in scene.shots
                         for lyric in shot.lyric_annotations if lyric.section), None),
        "lyrics": lyrics,
        "existing_actions": [shot.body[0] if shot.body else "" for shot in scene.shots],
        "shot_count": len(scene.shots),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emd", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    args = parser.parse_args()
    emd_bytes = args.emd.read_bytes()
    document = parse_emd(emd_bytes.decode("utf-8"))
    scenes = {scene.scene_number: scene for scene in document.scenes}
    config = LlamaRuntimeConfig(n_ctx=8192, max_tokens=384,
                                temperature=0.2, top_p=0.9, n_batch=512,
                                gpu_layers=-1, keep_model_loaded=False)
    evidence: dict[str, object] = {
        "scope": "research_only_real_8b_condensation_from_existing_emd_actions",
        "response_stage": "after_llama_cpp_lifecycle_normalization",
        "emd_sha256": hashlib.sha256(emd_bytes).hexdigest(),
        "model_path": str(args.model),
        "model_size": args.model.stat().st_size,
        "system_prompt": SYSTEM,
        "runtime": config.to_dict(),
        "runs": [],
    }
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene_number in (6, 9):
            payload = payload_for_scene(scenes[scene_number])
            user_text = "/no_think\n" + json.dumps(payload, ensure_ascii=False)
            for seed in args.seeds:
                active_config = LlamaRuntimeConfig(**{**config.to_dict(), "seed": seed})
                started = time.perf_counter()
                print(f"scene={scene_number} seed={seed} started", flush=True)
                raw = lifecycle.complete_chat(
                    [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user_text}], active_config,
                )
                lines = [line.strip() for line in raw.splitlines() if line.strip()]
                content_lines = [line for line in lines
                                 if line.startswith(("SCENE|", "ACTION|"))]
                extra_lines = [line for line in lines if line not in content_lines]
                records = [line.split("|", 2) for line in content_lines]
                content_records_ok = (
                    len(records) == 1 + len(scenes[scene_number].shots)
                    and len(records[0]) == 2 and records[0][0] == "SCENE"
                    and all(len(record) == 3 and record[0] == "ACTION"
                            and record[1] == str(index)
                            for index, record in enumerate(records[1:], 1))
                )
                run = {
                    "scene": scene_number,
                    "seed": seed,
                    "payload": payload,
                    "raw": raw,
                    "records": records,
                    "extra_lines": extra_lines,
                    "content_records_ok": content_records_ok,
                    "protocol_ok": content_records_ok and not extra_lines,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
                evidence["runs"].append(run)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"scene={scene_number} seed={seed} "
                      f"protocol_ok={run['protocol_ok']} "
                      f"elapsed={run['elapsed_seconds']}s", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    main()
