"""Probe an LLM-written Scene brief before the existing Camera-guided chain."""

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
from tools.offline_scene_body_chain import (
    SYSTEM_PROMPTS, model_input, parse_response,
)

BRIEF_PROMPT = (
    "あなたはアニメMVのScene単位の人物振付を短く設計する。歌詞とSceneのCueだけから、"
    "一人の人物の身体演技の始点、感情が変わる瞬間の身体動作、終端姿勢を一つの連続した"
    "フレーズにする。既存Shotの時間順を守り、前Sceneの終端があればそこから始める。"
    "撮影、照明、衣装、場所、歌詞にない小道具を追加しない。人物の自転、ただ歩くこと、"
    "前傾と手を腰へ置く定型、左右反転の反復をフレーズの主軸にしない。"
    "重心・体幹・腕・目のうち感情に必要な部分が、原因と結果を持って変わる。"
    "抽象的な感情語だけで終えず、動作を撮影可能な日本語で書く。"
    "実TAB区切りで BRIEF、1、開始=...｜変化=...｜終端=... の一行だけ出力する。"
    "Markdown、JSON、説明、他の行は付けない。"
)
_BRIEF_PATTERN = re.compile(
    r"^BRIEF\t1\t開始=([^\n｜]+)｜変化=([^\n｜]+)｜終端=([^\n｜]+)$"
)


def parse_brief(raw: str) -> str:
    normalized = re.sub(r"\A\s*<think>.*?</think>\s*", "", raw, flags=re.DOTALL)
    match = _BRIEF_PATTERN.fullmatch(normalized.strip())
    if match is None:
        raise ValueError("brief line protocol is invalid")
    return normalized.strip().split("\t", 2)[2]


def brief_input(scene: dict, previous_end_pose: str) -> dict:
    return {
        "scene_number": scene["scene_number"],
        "lyrics": scene["lyrics"], "cue": scene["cue"],
        "shot_count": len(scene["shots"]),
        "continuation": scene["continuation"],
        "previous_scene_end_pose": previous_end_pose,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", type=Path,
        default=ROOT / "docs/assets/research/scene-body-chain-2026-09-22/fixture.json",
    )
    parser.add_argument(
        "--camera-scaffold", type=Path,
        default=ROOT / "docs/assets/research/scene-body-chain-2026-09-22/camera-scaffold.json",
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    scaffold_bytes = args.camera_scaffold.read_bytes()
    scaffold = json.loads(scaffold_bytes)
    config = LlamaRuntimeConfig(
        n_ctx=8192, max_tokens=1200, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False,
    )
    evidence = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "camera_scaffold_sha256": hashlib.sha256(scaffold_bytes).hexdigest(),
        "brief_prompt_sha256": hashlib.sha256(BRIEF_PROMPT.encode("utf-8")).hexdigest(),
        "chain_prompt_sha256": hashlib.sha256(
            SYSTEM_PROMPTS["brief_camera_guided"].encode("utf-8")
        ).hexdigest(),
        "model": str(args.model.resolve()), "runtime": config.to_dict(),
        "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            previous_end_pose = ""
            for scene in fixture["scenes"]:
                request = brief_input(scene, previous_end_pose)
                started = time.perf_counter()
                print(f"seed={seed} scene={scene['scene_number']} brief started", flush=True)
                raw_brief = lifecycle.complete_chat(
                    [{"role": "system", "content": BRIEF_PROMPT},
                     {"role": "user", "content": "/no_think\n" + json.dumps(request, ensure_ascii=False)}],
                    replace(config, seed=seed, max_tokens=256),
                )
                record = {
                    "seed": seed, "scene_number": scene["scene_number"],
                    "brief_input": request, "brief_raw": raw_brief,
                    "brief_elapsed_seconds": round(time.perf_counter() - started, 3),
                }
                try:
                    brief = parse_brief(raw_brief)
                    record["brief"] = brief
                    chain_input = model_input(
                        scene, previous_end_pose, variant="brief_camera_guided",
                        camera_coverage=scaffold[str(scene["scene_number"])],
                        performance_brief=brief,
                    )
                    record["chain_input"] = chain_input
                    started = time.perf_counter()
                    raw_chain = lifecycle.complete_chat(
                        [{"role": "system", "content": SYSTEM_PROMPTS["brief_camera_guided"]},
                         {"role": "user", "content": "/no_think\n" + json.dumps(chain_input, ensure_ascii=False)}],
                        replace(config, seed=seed),
                    )
                    record["chain_raw"] = raw_chain
                    record["chain_elapsed_seconds"] = round(time.perf_counter() - started, 3)
                    record["chain"] = parse_response(
                        raw_chain, len(scene["shots"]), "brief_camera_guided"
                    )
                    previous_end_pose = record["chain"]["shots"][-1]["end_pose"]
                except (ValueError, json.JSONDecodeError) as error:
                    record["error"] = str(error)
                    previous_end_pose = ""
                evidence["runs"].append(record)
                (args.output / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"seed={seed} scene={scene['scene_number']} "
                    f"chain={'chain' in record}", flush=True,
                )
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
