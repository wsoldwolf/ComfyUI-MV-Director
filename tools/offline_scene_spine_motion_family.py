"""Probe scene-specific motion families in the existing Scene Spine stage."""

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
    parse_scene_spine_step, validate_contact_coverage, validate_scene_spine,
)
from core.protocols.llm_records import parse_llm_records
from nodes.node_timeline_planner.node import _LlamaPlannerBackend

PROMPT = ROOT / "prompts/timeline_planner_scene_spine_system_prompt.txt"
SCENES = (
    {
        "scene_number": 11,
        "lyric_lines": ["自由なのか", "それでも新しい足音が", "またこの社へ続くなら"],
        "cue": {
            "valid": True, "emotion": "決意", "evidence": "またこの社へ続くなら",
            "target": "社", "contact": "禁止", "phenomenon": "なし",
            "spatial_anchor": "参道の先の社", "visible_development": "社が視界に入る",
            "body_driver": "左肩を前に出し、右腕を上げ、左足を踏み出す",
            "final_state": "左足を前に置き、右手を顔の前に止める",
        },
        "shot_durations_ms": [4708, 5208],
        "editorial_roles": ["continuity_bridge", "upper_body_performance_coverage"],
        "motion_family": "体幹の方向を変え、腕の大きな軌道に遅れと着地を作る",
    },
    {
        "scene_number": 12,
        "lyric_lines": ["千年鳥居を", "くぐるそなたよ", "今この刹那を", "わらわに預けよ", "異なる時を"],
        "cue": {
            "valid": True, "emotion": "託す", "evidence": "千年鳥居を",
            "target": "千年鳥居", "contact": "禁止", "phenomenon": "なし",
            "spatial_anchor": "参道の鳥居", "visible_development": "鳥居の下へ進む",
            "body_driver": "右肩を前に出し、左腕を上げ、右足を踏み出す",
            "final_state": "右足を前に置き、左手を顔の前に止める",
        },
        "shot_durations_ms": [4167, 5250],
        "editorial_roles": ["face_performance_cut", "upper_body_performance_coverage"],
        "motion_family": "重心の移動を体幹から腕へ伝え、最後は異なる上半身姿勢で止まる",
    },
)
FAMILY_RULE = (
    "\n入力のsuggested_motion_familyは前Sceneと同じ手足の上下を避けるための候補。"
    "歌詞と撮影尺に合う場合だけ、準備・アクセント・到達姿勢へ具体化する。"
    "Cue Cardの身体主導を左右反転して繰り返す指示として扱わない。"
    "不適合なら採用せず、歌詞から別の身体経路を選ぶ。\n"
)
NO_COPY_RULE = (
    "\nCue Cardの身体主導は現在Sceneで達成すべき演技の方向、終端は最後に残す状態であり、"
    "いずれもShotのADVANCEにそのまま再掲しない。最初のShotでそこに至る予備動作、"
    "次のShotでそれとは異なる身体のアクセント又は感情反応を、具体的な身体変化として書く。"
    "FROMとTOを同じ語句で埋めるだけのShot、歩くだけのShot、左右反転の反復を避ける。\n"
)


def request_for_scene(
    scene: dict, *, guided: bool = False, unlock_body: bool = False,
) -> dict:
    slots = [
        {
            "slot": index,
            "scene_number": scene["scene_number"],
            "shot_index": index,
            "shot_count": len(scene["shot_durations_ms"]),
            "shot_duration_ms": duration,
            "editorial_role": scene["editorial_roles"][index - 1],
        }
        for index, duration in enumerate(scene["shot_durations_ms"], 1)
    ]
    cue = dict(scene["cue"])
    if unlock_body:
        cue["body_driver"] = ""
        cue["final_state"] = ""
    payload = {
        "protocol": "MVD_LLM_RECORDS_V1", "task": "scene-spine",
        "scene_number": scene["scene_number"],
        "lyric_lines": scene["lyric_lines"], "author_body": [],
        "visual_beat_grounding": cue,
        "spine_event_kind": "non_contact_change",
        "scene_continuation": scene["scene_number"] == 11,
        "entry_body_state": "", "slots": slots,
    }
    if guided:
        payload["suggested_motion_family"] = scene["motion_family"]
    return payload


def parse_response(raw: str, count: int) -> dict:
    slots = frozenset(range(1, count + 1))
    parsed = parse_llm_records(
        raw, allowed_slots={"SPINE": slots},
        required=frozenset(("SPINE", slot) for slot in slots),
    )
    values = {record.slot: record.text for record in parsed.records}
    result = {"protocol": parsed.to_dict(), "steps": []}
    if len(values) != count:
        return result
    try:
        steps = tuple(parse_scene_spine_step(values[slot]) for slot in sorted(slots))
        validate_scene_spine(steps)
        validate_contact_coverage(steps, contact_allowed=False)
        result["steps"] = [step.to_dict() for step in steps]
    except ValueError as error:
        result["semantic_error"] = str(error)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument(
        "--variants", nargs="+",
        choices=(
            "baseline", "family", "cue_without_body", "body_unlocked_family",
            "cue_reinterpret",
        ),
        default=["baseline", "family"],
    )
    args = parser.parse_args()
    prompt = PROMPT.read_text(encoding="utf-8")
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=640, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False,
    )
    evidence = {
        "source": "C:/Software/ComfyUI/output/mv_director/context_loop_emd_00001.md",
        "fixture": SCENES,
        "model": str(args.model.resolve()), "runtime": config.to_dict(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "guided_prompt_sha256": hashlib.sha256((prompt + FAMILY_RULE).encode("utf-8")).hexdigest(),
        "no_copy_prompt_sha256": hashlib.sha256((prompt + NO_COPY_RULE).encode("utf-8")).hexdigest(),
        "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene in SCENES:
            for seed in args.seeds:
                for variant in args.variants:
                    guided = variant in {"family", "body_unlocked_family"}
                    payload = request_for_scene(
                        scene, guided=guided,
                        unlock_body=variant in {"cue_without_body", "body_unlocked_family"},
                    )
                    started = time.perf_counter()
                    print(
                        f"scene={scene['scene_number']} seed={seed} variant={variant} started",
                        flush=True,
                    )
                    system_prompt = (
                        prompt + FAMILY_RULE if guided else
                        prompt + NO_COPY_RULE if variant == "cue_reinterpret" else prompt
                    )
                    raw = _LlamaPlannerBackend(lifecycle).complete_planner(
                        task="scene-spine",
                        system_prompt=system_prompt,
                        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        config=replace(config, seed=seed),
                    )
                    parsed = parse_response(raw, len(scene["shot_durations_ms"]))
                    evidence["runs"].append({
                        "scene_number": scene["scene_number"], "seed": seed,
                        "variant": variant, "payload": payload, "raw": raw,
                        "parsed": parsed,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                    })
                    (args.output / "evidence.json").write_text(
                        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    print(
                        f"scene={scene['scene_number']} seed={seed} "
                        f"variant={variant} steps={len(parsed['steps'])}", flush=True,
                    )
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
