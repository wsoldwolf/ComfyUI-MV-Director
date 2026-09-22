"""Offline 8B probe: plan one continuous body phrase per fixed Scene.

The original actions in the fixture are comparison data and never enter a model
request. This script does not modify the Planner, compile EMD, or invoke H3.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig


COMPACT_SYSTEM_PROMPT = """あなたはアニメMVの身体演技を計画する。1 Scene全体を一回の連続した身体フレーズとして考える。
与えられた歌詞、Cue、時刻、既存Shot枠だけを使い、人物一人の始点姿勢、支持と重心から体幹・腕・表情へ伝わる時間順の進行、終端姿勢を決める。
各Shotのactionは、同じフレーズの異なる時間部分とし、前のShotの終端を次のShotの始点としてつなぐ。新しい場所・小道具・接触対象を創作しない。人物を全身回転させず、カメラ動作は書かない。
静止した手の配置や肩の左右反復だけで終わらせず、歌詞の感情の変化を読める動きにする。ただし各Shotへ身体部位の語を機械的に詰め込まない。
JSONオブジェクトを一つだけ返す。キーはstart_pose, progression, end_pose, shot_actions。progressionとshot_actionsは日本語文字列の配列。shot_actionsは入力Shotと同数。説明やMarkdownは付けない。"""

PROTOTYPE_MOTION_SYSTEM_PROMPT = """You plan one continuous physical performance for one anime music-video Scene. Use the supplied lyric, fixed Cue and Shot boundaries, not a generic dance template.
Plan the Scene before distributing it into Shots: state the grounded starting pose, 2–4 chronological deliberate body phases and a visibly different ending pose. A deliberate phase changes balance, support, torso orientation, body level, stance or articulated limb configuration. Passive swaying, facial expression, gaze, mouth, hair, clothing and camera movement alone do not count. A hand rising or returning to the chest or waist alone does not count.
The same performer must remain physically continuous: movement starts from support and weight transfer, travels through pelvis/ribcage and arms, and settles into a stable ending balance. Distribute the phases over the existing Shot slots. The next Shot starts from the previous Shot's end; do not reset the pose or replay an earlier gesture. For one Shot, its action may contain multiple consecutive phases. Do not invent a prop, contact target or new place. Do not rotate the whole person for a camera orbit. Do not write camera directions.
Respond with one JSON object only. The exact keys are start_pose, progression, end_pose, shot_actions. Write all creative values in concise natural Japanese. progression is a list of 2–4 chronological phase strings. shot_actions is a list of strings with exactly the same length and order as the input shot_slots; each string describes the visible portion of the Scene phrase during that Shot. No Markdown or explanation."""

UNIFIED_SHOT_CHAIN_SYSTEM_PROMPT = """You plan one continuous physical performance for one anime music-video Scene. Use only the given lyric, Cue and fixed Shot boundaries.
Write a single temporal chain, not a separate Scene outline followed by another Shot outline. Choose a grounded starting pose. For each Shot in order, write the action that takes the performer from the current pose to that Shot's ending pose. The next Shot begins in the previous Shot's ending pose without a reset. The last Shot's ending pose is the Scene ending pose and is passed to the following Scene.
Deliberate performance has preparation, a readable accent and settling. A body phrase may change support, balance, torso level or orientation and an arm path, but do not mechanically require each body part in each Shot. Mere sway, returning a hand to the waist, a repeated forward lean or camera movement alone is not a complete phrase. A single Shot can contain several ordered movements. Keep grounded support physically possible. Do not add a prop, contact target, place, whole-person spin, or camera direction.
Return one JSON object with exactly two keys: start_pose and shots. start_pose is a Japanese string. shots is an array with exactly the number of input shot_slots; each item has exactly action and end_pose as concise Japanese strings. Do not add a separate progression field or duplicate the Scene ending elsewhere. No Markdown or explanation."""

CAMERA_GUIDED_SHOT_CHAIN_SYSTEM_PROMPT = UNIFIED_SHOT_CHAIN_SYSTEM_PROMPT + """
The camera_coverage entries are a fixed viewing plan, not new lyric, prop, or action authority. Choreograph a visible body change for each Shot that its assigned view can actually show. A face-and-upper-body view should reveal an eye, mouth, shoulder, or hand accent without starting an unseen footstep. A wider moving view can show grounded weight transfer, torso counter-motion, and an arm trajectory before the final pose. The camera travels around the performer; the performer must not spin to imitate that travel. Align the body's accent or settling with the camera's arrival, while preserving the previous Shot's end pose. Do not copy camera directions into the action field or substitute camera movement for acting. Use the viewing plan only to choose observable performance, not to invent an environment or target."""

BRIEF_CAMERA_GUIDED_SYSTEM_PROMPT = CAMERA_GUIDED_SHOT_CHAIN_SYSTEM_PROMPT + """
The performance_brief is a Scene-specific acting intention derived from its supplied lyric, not text to copy. Realize its preparation, main expressive change, and release across the fixed Shot count. Make the body change physically continuous: establish stable support, transfer weight only when visible, let the torso and arms complete a purposeful path, and carry the resulting pose into the next Shot. A close view shows the upper-body or facial consequence of an earlier visible accent, not a newly invented hidden full-body move. Avoid generic walking, forward-lean repetition, hand-to-waist resets, and mirrored left/right substitutions. Do not add any object, target, setting, or camera instruction from the brief."""

SYSTEM_PROMPTS = {"compact": COMPACT_SYSTEM_PROMPT,
                  "prototype_motion": PROTOTYPE_MOTION_SYSTEM_PROMPT,
                  "unified_shot_chain": UNIFIED_SHOT_CHAIN_SYSTEM_PROMPT,
                  "camera_guided_shot_chain": CAMERA_GUIDED_SHOT_CHAIN_SYSTEM_PROMPT,
                  "brief_camera_guided": BRIEF_CAMERA_GUIDED_SYSTEM_PROMPT}


def model_input(
    scene: dict, previous_end_pose: str = "", *,
    variant: str = "compact", camera_coverage: list[str] | None = None,
    performance_brief: str | None = None,
) -> dict:
    """Keep baseline Actions and other Scenes out of the model request."""
    request = {
        "scene_number": scene["scene_number"],
        "start": scene["start"],
        "end": scene["end"],
        "continuation": scene["continuation"],
        "cue": scene["cue"],
        "lyrics": scene["lyrics"],
        "shot_slots": [
            {"slot": index, "start": shot["start"], "end": shot["end"]}
            for index, shot in enumerate(scene["shots"], 1)
        ],
        "previous_scene_end_pose": previous_end_pose,
    }
    if variant in {"camera_guided_shot_chain", "brief_camera_guided"}:
        if camera_coverage is None or len(camera_coverage) != len(scene["shots"]):
            raise ValueError("camera coverage must match the fixed Shot count")
        if any(not isinstance(role, str) or not role.strip() for role in camera_coverage):
            raise ValueError("camera coverage contains an empty role")
        request["camera_coverage"] = camera_coverage
    if variant == "brief_camera_guided":
        if not isinstance(performance_brief, str) or not performance_brief.strip():
            raise ValueError("performance brief is required")
        request["performance_brief"] = performance_brief
    return request


def parse_response(raw: str, shot_count: int, variant: str = "compact") -> dict:
    """Validate structure only; never rewrite LLM language."""
    # The Qwen chat template can emit this empty wrapper despite /no_think.
    # This is the same protocol normalization used by the existing Planner.
    normalized = re.sub(r"\A\s*<think>.*?</think>\s*", "", raw, flags=re.DOTALL)
    value = json.loads(normalized.strip())
    if variant in {
        "unified_shot_chain", "camera_guided_shot_chain",
        "brief_camera_guided",
    }:
        if not isinstance(value, dict) or set(value) != {"start_pose", "shots"}:
            raise ValueError("response keys differ from the unified contract")
        if not isinstance(value["start_pose"], str) or not value["start_pose"].strip():
            raise ValueError("start_pose is empty or non-text")
        shots = value["shots"]
        if not isinstance(shots, list) or len(shots) != shot_count:
            raise ValueError("shots do not match the fixed Shot count")
        if any(not isinstance(shot, dict) or set(shot) != {"action", "end_pose"}
               or any(not isinstance(shot[key], str) or not shot[key].strip()
                      for key in ("action", "end_pose")) for shot in shots):
            raise ValueError("a Shot action or end_pose is empty or malformed")
        return value
    if not isinstance(value, dict) or set(value) != {
        "start_pose", "progression", "end_pose", "shot_actions"
    }:
        raise ValueError("response keys differ from the four-field contract")
    if any(not isinstance(value[key], str) or not value[key].strip()
           for key in ("start_pose", "end_pose")):
        raise ValueError("a body-phrase field is empty or non-text")
    progression = value["progression"]
    if (not isinstance(progression, list) or not 2 <= len(progression) <= 6
            or any(not isinstance(item, str) or not item.strip() for item in progression)):
        raise ValueError("progression must contain two to six nonempty phases")
    actions = value["shot_actions"]
    if (not isinstance(actions, list) or len(actions) != shot_count
            or any(not isinstance(item, str) or not item.strip() for item in actions)):
        raise ValueError("shot_actions do not match the fixed Shot count")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[1] /
                        "docs/assets/research/scene-body-chain-2026-09-22/fixture.json")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--variant", choices=SYSTEM_PROMPTS, default="compact")
    parser.add_argument("--camera-scaffold", type=Path)
    parser.add_argument("--performance-brief", type=Path)
    parser.add_argument("--gpu-layers", type=int, default=-1,
                        help="Use 0 for CPU-only inference while ComfyUI owns the GPU.")
    parser.add_argument("--max-tokens", type=int, default=1200)
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    scaffold = (
        json.loads(args.camera_scaffold.read_text(encoding="utf-8"))
        if args.camera_scaffold else {}
    )
    brief = (
        json.loads(args.performance_brief.read_text(encoding="utf-8"))
        if args.performance_brief else {}
    )
    if args.variant in {"camera_guided_shot_chain", "brief_camera_guided"} and not scaffold:
        parser.error("--camera-scaffold is required for the camera-guided variants")
    if args.variant == "brief_camera_guided" and not brief:
        parser.error("--performance-brief is required for brief_camera_guided")
    args.output.mkdir(parents=True, exist_ok=True)
    config = LlamaRuntimeConfig(n_ctx=8192, max_tokens=args.max_tokens, temperature=0.2,
                                top_p=0.9, repetition_penalty=1.05,
                                gpu_layers=args.gpu_layers, n_batch=512, keep_model_loaded=False)
    lifecycle = LlamaCppLifecycle()
    result = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "model": str(args.model.resolve()),
        "model_size": args.model.stat().st_size,
        "system_prompt": SYSTEM_PROMPTS[args.variant],
        "variant": args.variant,
        "runtime": config.to_dict(),
        "camera_scaffold_sha256": (
            hashlib.sha256(args.camera_scaffold.read_bytes()).hexdigest()
            if args.camera_scaffold else None
        ),
        "performance_brief_sha256": (
            hashlib.sha256(args.performance_brief.read_bytes()).hexdigest()
            if args.performance_brief else None
        ),
        "runs": [],
    }
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            previous_end_pose = ""
            for scene in fixture["scenes"]:
                coverage = scaffold.get(str(scene["scene_number"]))
                payload = model_input(
                    scene, previous_end_pose, variant=args.variant,
                    camera_coverage=coverage,
                    performance_brief=brief.get(str(scene["scene_number"])),
                )
                started = time.perf_counter()
                print(f"seed={seed} scene={scene['scene_number']} started", flush=True)
                raw = lifecycle.complete_chat(
                    [{"role": "system", "content": SYSTEM_PROMPTS[args.variant]},
                     {"role": "user", "content": "/no_think\n" + json.dumps(payload, ensure_ascii=False)}],
                    replace(config, seed=seed),
                )
                record = {"seed": seed, "scene_number": scene["scene_number"],
                          "input": payload, "raw": raw,
                          "elapsed_seconds": round(time.perf_counter() - started, 3)}
                try:
                    record["parsed"] = parse_response(raw, len(scene["shots"]), args.variant)
                    previous_end_pose = (
                        record["parsed"]["shots"][-1]["end_pose"]
                        if args.variant in {
                            "unified_shot_chain", "camera_guided_shot_chain",
                            "brief_camera_guided",
                        }
                        else record["parsed"]["end_pose"]
                    )
                except (ValueError, json.JSONDecodeError) as error:
                    record["parse_error"] = str(error)
                    previous_end_pose = ""
                result["runs"].append(record)
                (args.output / "evidence.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"seed={seed} scene={scene['scene_number']} elapsed={record['elapsed_seconds']}s "
                      f"parsed={'parsed' in record}", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
