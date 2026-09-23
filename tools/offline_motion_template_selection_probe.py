"""Try one LLM-authored Scene motion brief before existing Spine/Action calls."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from nodes.node_timeline_planner.node import _LlamaPlannerBackend
from tools.offline_motion_template_input_probe import (
    ACTION_PROMPT, SCENES, SOURCE, SPINE_PROMPT, TEMPLATES,
    _original_spine_requests, _parse_records, _single_shot_action,
    parse_motion_templates,
)

SELECT = (
    "現在Sceneの歌詞、Cue、前Scene終端、画角を読み、motion_templatesから合う身体経路を選び"
    "適応するか、合わなければ独自に作る。候補は場所・小道具・接触対象を追加する根拠ではない。"
    "body_driverの文をそのまま繰り返さず、支持、重心、体幹、腕、顔がつながる短い経路にする。"
    "出力はMOTIONレコードの本文に身体経路を一行で書く。説明とMarkdownは不要。"
)
SELECT_GRAMMAR = 'root ::= "MOTION\\t" body "\\n"?\nbody ::= [^\\x00-\\x1f]+\n'
SPINE_RULE = (
    "\nscene_motion_briefは現在Scene用の任意の身体経路。Cueの出来事を守り、"
    "前Sceneの終端姿勢から準備、アクセント、終端をShotへ分配する。"
    "合わない箇所は独自に変えてよい。\n"
)
ACTION_RULE = (
    "\nscene_motion_briefは任意の身体経路。歌詞とCueを優先し、"
    "支持、体幹、腕、顔を一続きの可視動作として具体化してよい。\n"
)


def parse_brief(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].startswith("MOTION\t"):
        raise ValueError("selection response is not one MOTION record")
    brief = lines[0].split("\t", 1)[1].strip()
    if not brief:
        raise ValueError("empty motion brief")
    return brief


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43])
    parser.add_argument("--gpu-layers", type=int, default=-1)
    parser.add_argument("--scenes", type=int, nargs="+", default=[*SCENES, 16])
    args = parser.parse_args()
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    templates = parse_motion_templates(TEMPLATES.read_text(encoding="utf-8"))
    scenes = _original_spine_requests(source["trace"])
    _, single = _single_shot_action(source["trace"])
    config = replace(LlamaRuntimeConfig(**source["runtime"]), gpu_layers=args.gpu_layers)
    evidence = {"source": str(SOURCE), "model": str(args.model), "runtime": config.to_dict(), "runs": []}
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            for scene in args.scenes:
                payload = json.loads(scenes[scene]["payload"]) if scene != 16 else json.loads(json.dumps(single))
                payload.pop("choreography_palette", None)
                cue = payload["visual_beat_grounding"] if scene != 16 else payload["slots"][0]["visual_beat_grounding"]
                selection = {
                    "scene": scene,
                    "lyrics": payload["lyric_lines"] if scene != 16 else [x["text"] for x in payload["slots"][0]["lyrics"]],
                    "cue": cue,
                    "entry_body_state": payload.get("entry_body_state", "") if scene != 16 else payload["slots"][0].get("entry_body_state", ""),
                    "coverage": [x.get("editorial_role", x.get("performance_role", "")) for x in payload["slots"]],
                    "motion_templates": list(templates),
                }
                start = perf_counter()
                choice = lifecycle.complete_chat(
                    [{"role": "system", "content": SELECT},
                     {"role": "user", "content": "/no_think\n" + json.dumps(selection, ensure_ascii=False)}],
                    replace(config, seed=seed, max_tokens=192),
                    grammar=SELECT_GRAMMAR,
                )
                row = {"seed": seed, "scene": scene, "selection_input": selection, "selection_raw": choice}
                try:
                    row["brief"] = parse_brief(choice)
                    payload["scene_motion_brief"] = row["brief"]
                    task = "actions" if scene == 16 else "scene-spine"
                    prompt = (ACTION_PROMPT if scene == 16 else SPINE_PROMPT).read_text(encoding="utf-8")
                    prompt += ACTION_RULE if scene == 16 else SPINE_RULE
                    response = backend.complete_planner(
                        task=task, system_prompt=prompt,
                        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        config=replace(config, seed=seed, max_tokens=512),
                    )
                    slots = [int(x["slot"]) for x in payload["slots"]]
                    row["generation_input"] = payload
                    row["generation_raw"] = response
                    row["parsed"] = _parse_records(
                        response, "ACTION" if scene == 16 else "SPINE", slots,
                        contact=scene != 16 and cue["contact"] == "許可",
                    )
                except ValueError as exc:
                    row["error"] = str(exc)
                row["elapsed_seconds"] = round(perf_counter() - start, 3)
                evidence["runs"].append(row)
                args.output.joinpath("evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print(f"seed={seed} scene={scene} brief={'brief' in row} "
                      f"valid={row.get('parsed', {}).get('valid', False)} "
                      f"elapsed={row['elapsed_seconds']}s", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
