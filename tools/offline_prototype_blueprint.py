"""Compare the restored prototype lyric-action preplan on fixed current lyrics.

Read-only with respect to the prototype project; writes only the requested
evidence directory. This is an offline LLM probe, not a production node.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from nodes.node_timeline_planner.node import _LlamaPlannerBackend

DEFAULT_FIXTURE = ROOT / "docs/assets/research/prototype-blueprint-gpu-2026-09-22/fixture.json"
DEFAULT_PROMPT = (
    ROOT.parent / "ComfyUI-cl-japanese2json/node_mv_prompt_planner/prompts/core/lyric_action_system_prompt.txt"
)
_ACTION = re.compile(r"^ACTION\t(\d+)\t(.+)$", re.MULTILINE)


def scene_payload(scene: dict) -> dict:
    """Reproduce the old preplan input shape without original Action leakage."""
    lyric_lines = [
        {"index": index, "section": "VERSE", "kind": "lyric", "text": value}
        for index, value in enumerate(scene["lyrics"], 1)
    ]
    return {
        "protocol": "clmv-lyric-action-line-v1",
        "planning_constraints": {
            "subject_identity": ["CLMPSUB1X は一人の女性歌手"],
            "retention_constraints": ["人物の同一性と身体構造を保つ"],
        },
        "reference_legend": {"CLMPSUB1X": "<Subject 1>"},
        "requested_scene_ids": [scene["scene_id"]],
        "requested_scene_count": 1,
        "scenes": [{
            "scene_id": scene["scene_id"],
            "duration_ms": scene["duration_ms"],
            "lyric_lines": lyric_lines,
            "allowed_response_modes": [
                "direct_subject_action", "direct_object_action", "spatial_metaphor"
            ],
            "semantic_grounding_order": [
                "choose the earliest complete source predicate",
                "identify its actor, physical head verb, and concrete target",
                "make the target recognizable before contact",
                "execute that exact verb instead of a visually convenient substitute",
                "show the completed result on the same target after release",
            ],
            "style_separation": (
                "This stage has intentionally omitted global medium, background, "
                "motif, and camera directions. Resolve only the source lyric's "
                "literal visible predicate."
            ),
        }],
    }


def summarize(raw: str) -> dict:
    actions = [(int(index), text) for index, text in _ACTION.findall(raw)]
    return {
        "action_count": len(actions),
        "actions": actions,
        "has_required_records": all(
            token in raw for token in (
                "LYRIC_SCENE\t", "LYRIC_RESPONSE\t", "COMPOSITION_REQUIREMENT\t",
                "VISIBLE_RESULT\t", "END_LYRIC_SCENE",
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    prompt = args.prompt.read_text(encoding="utf-8")
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=768, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False,
    )
    evidence = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "prompt": str(args.prompt.resolve()),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "model": str(args.model.resolve()),
        "model_size": args.model.stat().st_size,
        "runtime": config.to_dict(),
        "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene in fixture["scenes"]:
            payload = scene_payload(scene)
            for seed in args.seeds:
                started = time.perf_counter()
                print(f"scene={scene['scene_id']} seed={seed} started", flush=True)
                raw = _LlamaPlannerBackend(lifecycle).complete_planner(
                    task="prototype-blueprint", system_prompt=prompt,
                    payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    config=replace(config, seed=seed),
                )
                evidence["runs"].append({
                    "scene_id": scene["scene_id"], "seed": seed,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "payload": payload, "raw": raw, "summary": summarize(raw),
                })
                (args.output / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"scene={scene['scene_id']} seed={seed} "
                    f"actions={len(evidence['runs'][-1]['summary']['actions'])}",
                    flush=True,
                )
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
