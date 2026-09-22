"""Probe LLM phrase selection and Shot expansion without changing production Planner."""

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

from core.direction.profile_loader import load_direction_profile
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from tools.offline_scene_body_chain import (
    BRIEF_CAMERA_GUIDED_SYSTEM_PROMPT,
    model_input,
    parse_response,
)


SELECT_SYSTEM_PROMPT = """あなたはアニメMVのScene演技を決める。候補は身体の運動経路であり、歌詞の対象、場所、小道具を決める権限ではない。
現在Sceneの歌詞、Cue、Shotごとの画角、前Sceneの終端を読み、撮影可能で感情に合う候補を一つ選ぶ。顔だけの画角に見えない新しい踏み替えを割り当てず、接触対象は歌詞とCueにあるものに限る。直前と同じ候補は、他の候補も適合するなら避ける。
応答は候補IDを一つだけ、説明・引用符・Markdownなしで出力する。"""

CHAIN_SYSTEM_PROMPT = BRIEF_CAMERA_GUIDED_SYSTEM_PROMPT + """
If continuation is true and previous_scene_end_pose is nonempty, it is the actual starting body state. The selected performance_brief is a movement vocabulary, not a command to restart its written starting pose. Adapt only the unused movement path from the current pose and finish in a new stable pose. Never repeat the previous Scene's support transfer or arm accent. Preserve the lyric meaning and fixed camera coverage."""


def choose_phrase_input(scene: dict, coverage: list[str], phrases: tuple[tuple[str, str], ...],
                        previous_end: str, previous_phrase_id: str) -> dict:
    if len(coverage) != len(scene["shots"]):
        raise ValueError("camera coverage must match shots")
    eligible = tuple(
        (phrase_id, phrase) for phrase_id, phrase in phrases
        if phrase_id != previous_phrase_id
    ) if previous_phrase_id and len(phrases) > 1 else phrases
    return {
        "scene_number": scene["scene_number"],
        "lyrics": scene["lyrics"],
        "cue": scene["cue"],
        "continuation": scene["continuation"],
        "previous_scene_end_pose": previous_end,
        "previous_phrase_id": previous_phrase_id,
        "camera_coverage": coverage,
        "candidates": [{"id": phrase_id, "body_path": phrase} for phrase_id, phrase in eligible],
    }


def parse_phrase_id(raw: str, phrases: tuple[tuple[str, str], ...]) -> str:
    value = re.sub(r"\A\s*<think>.*?</think>\s*", "", raw, flags=re.DOTALL).strip()
    if value not in dict(phrases):
        raise ValueError("selector did not return exactly one candidate ID")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--fixture", type=Path, default=root / "docs/assets/research/scene-body-chain-2026-09-22/fixture.json")
    parser.add_argument("--camera-scaffold", type=Path, default=root / "docs/assets/research/scene-body-chain-2026-09-22/camera-scaffold.json")
    parser.add_argument("--profile", type=Path, default=root / "profiles/motion/anime_choreography_mv.md")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--gpu-layers", type=int, default=-1)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    scaffold = json.loads(args.camera_scaffold.read_text(encoding="utf-8"))
    profile = load_direction_profile(args.profile, "motion")
    if not profile.choreography_phrases:
        raise ValueError("profile has no choreography phrases")
    args.output.mkdir(parents=True, exist_ok=True)
    config = LlamaRuntimeConfig(n_ctx=8192, max_tokens=1200, temperature=0.2,
                                top_p=0.9, repetition_penalty=1.05,
                                gpu_layers=args.gpu_layers, n_batch=512,
                                keep_model_loaded=False)
    lifecycle = LlamaCppLifecycle()
    result = {
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "camera_scaffold_sha256": hashlib.sha256(args.camera_scaffold.read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(args.profile.read_bytes()).hexdigest(),
        "model": str(args.model.resolve()),
        "runtime": config.to_dict(),
        "selector_system_prompt": SELECT_SYSTEM_PROMPT,
        "chain_system_prompt": CHAIN_SYSTEM_PROMPT,
        "runs": [],
    }
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            previous_end = ""
            previous_id = ""
            for scene in fixture["scenes"]:
                coverage = scaffold[str(scene["scene_number"])]
                selector_input = choose_phrase_input(
                    scene, coverage, profile.choreography_phrases,
                    previous_end, previous_id,
                )
                record = {"seed": seed, "scene_number": scene["scene_number"],
                          "selection_input": selector_input}
                started = time.perf_counter()
                print(f"seed={seed} scene={scene['scene_number']} selection started", flush=True)
                raw = lifecycle.complete_chat(
                    [{"role": "system", "content": SELECT_SYSTEM_PROMPT},
                     {"role": "user", "content": "/no_think\n" + json.dumps(selector_input, ensure_ascii=False)}],
                    replace(config, seed=seed, max_tokens=96),
                )
                record["selection_raw"] = raw
                try:
                    eligible = tuple(
                        (candidate["id"], candidate["body_path"])
                        for candidate in selector_input["candidates"]
                    )
                    phrase_id = parse_phrase_id(raw, eligible)
                    record["selected_phrase_id"] = phrase_id
                    brief = dict(profile.choreography_phrases)[phrase_id]
                    payload = model_input(
                        scene, previous_end, variant="brief_camera_guided",
                        camera_coverage=coverage, performance_brief=brief,
                    )
                    record["chain_input"] = payload
                    chain_raw = lifecycle.complete_chat(
                        [{"role": "system", "content": CHAIN_SYSTEM_PROMPT},
                         {"role": "user", "content": "/no_think\n" + json.dumps(payload, ensure_ascii=False)}],
                        replace(config, seed=seed),
                    )
                    record["chain_raw"] = chain_raw
                    record["parsed"] = parse_response(chain_raw, len(scene["shots"]),
                                                       "brief_camera_guided")
                    previous_end = record["parsed"]["shots"][-1]["end_pose"]
                    previous_id = phrase_id
                except (ValueError, json.JSONDecodeError) as error:
                    record["error"] = str(error)
                    previous_end = ""
                    previous_id = ""
                record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                result["runs"].append(record)
                (args.output / "evidence.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print(f"seed={seed} scene={scene['scene_number']} "
                      f"selected={record.get('selected_phrase_id', 'none')} "
                      f"parsed={'parsed' in record} elapsed={record['elapsed_seconds']}s", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
