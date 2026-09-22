"""Compare old/current Visual Beat prompts on fixed real-lyric Scenes, without ComfyUI."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.direction.profile_loader import load_direction_profile
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.cue_constraints import build_grounded_cue_grammar
from core.protocols.llm_records import parse_llm_records
from nodes.node_timeline_planner.node import _LlamaPlannerBackend


PROMPT_PATH = Path("prompts/timeline_planner_visual_beats_system_prompt.txt")
COMPACT_MOTION = (
    "歌詞の感情を人物の姿勢変化にし、Sceneごとに異なる身体の到達状態を作る。"
    "Cameraの回り込みを人物自身の回転で代用しない。"
)


def prompts() -> dict[str, str]:
    baseline = subprocess.run(
        ["git", "show", f"HEAD:{PROMPT_PATH.as_posix()}"],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.rstrip() + "\n"
    current = (ROOT / PROMPT_PATH).read_text(encoding="utf-8").rstrip() + "\n"
    return {"baseline": baseline, "choreography": current}


def model_request(fixture: dict, *, motion_mode: str = "full") -> dict:
    """Hold source lyrics and model inputs fixed; do not expose cached outputs."""
    profile = load_direction_profile(
        ROOT / "profiles/motion/anime_emotional_mv.md", "motion"
    )
    if motion_mode not in {"full", "compact"}:
        raise ValueError("motion_mode must be full or compact")
    return {
        "protocol": fixture["protocol"],
        "task": fixture["task"],
        "planner_policy_contract": fixture["planner_policy_contract"],
        "direction": {
            "style": "手描きセルアニメ",
            "time_lighting": "夜の神社参道。月光。",
            "motion": profile.text if motion_mode == "full" else COMPACT_MOTION,
            "other": "",
        },
        "subject_roster": ["サブジェクト1"],
        "scene_context_usage": "spatial_support_only_never_activates_an_action_target",
        "recent_visual_beat_history": [],
        "slots": fixture["slots"],
    }


def parse_response(raw: str, slots: list[dict]) -> dict:
    ids = frozenset(slot["slot"] for slot in slots)
    parsed = parse_llm_records(
        raw, allowed_slots={"BEAT": ids},
        required=frozenset(("BEAT", slot) for slot in ids),
    )
    return parsed.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT /
                        "docs/assets/research/visual-beat-choreography-2026-09-22/fixture.json")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--variants", nargs="+", choices=("baseline", "choreography"),
                        default=["baseline", "choreography"])
    parser.add_argument("--gpu-layers", type=int, default=-1)
    parser.add_argument("--motion-mode", choices=("full", "compact"), default="full")
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    request = model_request(fixture, motion_mode=args.motion_mode)
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    variants = prompts()
    grammar = build_grounded_cue_grammar(request["slots"])
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=1024, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=args.gpu_layers,
        n_batch=512, keep_model_loaded=False,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "model": str(args.model.resolve()),
        "model_size": args.model.stat().st_size,
        "runtime": config.to_dict(),
        "motion_mode": args.motion_mode,
        "prompt_sha256": {
            name: hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            for name, prompt in variants.items()
        },
        "payload": request,
        "grammar_sha256": hashlib.sha256(grammar.encode("utf-8")).hexdigest(),
        "runs": [],
    }
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            for variant in args.variants:
                backend = _LlamaPlannerBackend(lifecycle)
                started = time.perf_counter()
                print(f"seed={seed} variant={variant} started", flush=True)
                raw = backend.complete_planner(
                    task="visual-beats", system_prompt=variants[variant],
                    payload=payload, config=replace(config, seed=seed),
                )
                run = {
                    "seed": seed, "variant": variant, "raw": raw,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "parsed": parse_response(raw, request["slots"]),
                }
                evidence["runs"].append(run)
                (args.output / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"seed={seed} variant={variant} elapsed={run['elapsed_seconds']}s "
                    f"missing={run['parsed']['missing']} issues={len(run['parsed']['issues'])}",
                    flush=True,
                )
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
