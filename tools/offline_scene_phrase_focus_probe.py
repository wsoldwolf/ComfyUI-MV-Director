"""Evaluate each lyric Shot, choose a continuous phrase, then author one Event.

The focus call receives only the current Scene's lyrics and structural Shot
boundaries. No target dictionary, background, or user staging candidate enters
that call. Production Planner, EMD, Compiler, and H3 are unchanged.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import canonical_json
from core.inference import LlamaRuntimeConfig
from tools.offline_scene_event_source_probe import (
    BASE_PROMPT, DEFAULT_SOURCE, MODEL, event_requests, parse_legacy_response,
)
from tools.offline_section_performance_probe import FixedSeedBackend, RecordingLifecycle

FOCUS_PROMPT = (
    "あなたはアニメMVの一つのSceneの原歌詞だけを読む。まず各Shotの連続した歌詞を"
    "一まとまりとして読み、そのShotが外部の物体・現象の可視変化に使えるか短く評価する。"
    "隣接Shotの境界をまたぐ句も入力にあるので、一続きの意味なら使ってよい。"
    "全Shotを評価してから、Sceneの一回の出来事の着想に最も適した句IDを選ぶ。"
    "単に先頭にある句を選ばず、後半の具体物、光、自然現象も見る。"
    "比喩は自由に映像化し、名詞の逐語描写や人物の接触を義務にしない。"
    "外部の出来事が適切でなければNONEを選ぶ。背景、人物資料、演出候補はここでは見ない。"
    "各ShotについてEVAL<TAB>Shot番号<TAB>YES又はNOを一行ずつ書き、"
    "最後にSELECT<TAB>1<TAB>許可された句IDを一行だけ書く。余分な行を出さない。"
)
_EVAL_LINE = re.compile(r"EVAL\t([1-9][0-9]*)\t(YES|NO)\Z")
_SELECT_LINE = re.compile(r"SELECT\t1\t([^\t\n]+)\Z")


def phrase_candidates(request: dict) -> tuple[dict, ...]:
    """Make contiguous within-Shot and adjacent-boundary phrases mechanically."""
    groups = []
    shots = request["original_lyrics"]
    for index, shot in enumerate(shots):
        lines = shot["lyrics"]
        if not lines:
            raise ValueError("Every selected Shot must contain lyrics")
        number = shot["shot"]
        groups.append({
            "id": f"SHOT:{number}", "first_shot": number, "last_shot": number,
            "lines": [
                {"shot": number, "source_line": line["source_line"],
                 "text": line["text"]} for line in lines
            ],
        })
        if index + 1 < len(shots):
            following = shots[index + 1]
            next_number = following["shot"]
            if next_number != number + 1 or not following["lyrics"]:
                raise ValueError("Adjacent lyric Shots must be consecutive and nonempty")
            groups.append({
                "id": f"BRIDGE:{number}-{next_number}",
                "first_shot": number, "last_shot": next_number,
                "lines": [
                    {"shot": number, "source_line": lines[-1]["source_line"],
                     "text": lines[-1]["text"]},
                    {"shot": next_number,
                     "source_line": following["lyrics"][0]["source_line"],
                     "text": following["lyrics"][0]["text"]},
                ],
            })
    if not groups or len({group["id"] for group in groups}) != len(groups):
        raise ValueError("Phrase candidates must be nonempty and unique")
    return tuple(groups)


def focus_payload(request: dict) -> dict:
    return {
        "scene_number": request["scene_number"],
        "shot_lyrics": [
            {"shot": row["shot"], "lines": [line["text"] for line in row["lyrics"]]}
            for row in request["original_lyrics"]
        ],
        "phrase_candidates": list(phrase_candidates(request)),
    }


def focus_grammar(request: dict) -> str:
    quoted = lambda value: json.dumps(value, ensure_ascii=False)
    evaluations = [
        quoted(f"EVAL\t{row['shot']}\t") + ' ("YES" | "NO") "\\n"'
        for row in request["original_lyrics"]
    ]
    choices = [group["id"] for group in phrase_candidates(request)] + ["NONE"]
    return (
        "root ::= " + " ".join(evaluations) +
        ' "SELECT\\t1\\t" choice "\\n"?\n' +
        "choice ::= " + " | ".join(quoted(choice) for choice in choices) + "\n"
    )


def parse_focus_response(response: str, request: dict) -> dict:
    lines = response.rstrip("\n").split("\n")
    shots = [row["shot"] for row in request["original_lyrics"]]
    if len(lines) != len(shots) + 1:
        raise ValueError("Focus response has incorrect line count")
    evaluations = []
    for expected, line in zip(shots, lines[:-1]):
        match = _EVAL_LINE.fullmatch(line)
        if not match or int(match.group(1)) != expected:
            raise ValueError("Focus response has invalid Shot evaluation")
        evaluations.append({"shot": expected, "visual": match.group(2)})
    chosen = _SELECT_LINE.fullmatch(lines[-1])
    if not chosen:
        raise ValueError("Focus response has no SELECT record")
    selected_id = chosen.group(1)
    choices = {group["id"]: group for group in phrase_candidates(request)}
    if selected_id == "NONE":
        selected = {"id": "NONE", "first_shot": None, "last_shot": None,
                    "lines": []}
    elif selected_id in choices:
        selected = choices[selected_id]
    else:
        raise ValueError("Focus response selected an unknown phrase")
    return {"evaluations": evaluations, "selected": selected}


def selected_event_prompt(baseline: str) -> str:
    prefix, marker, ending = baseline.partition("一行のみ、EVENT")
    if not marker:
        raise ValueError("Unexpected frozen Event prompt")
    return prefix + (
        "selected_lyric_phraseは現在Sceneの原歌詞だけから先に選んだ連続句である。"
        "選択句と前後の原歌詞から一回の可視変化を作り、その歌詞に対応するShotに初出させる。"
        "境界をまたぐ句なら後半Shotでの初出も考慮する。"
        "scene_environmentは対象を置くための資料であり、紅葉や設備で選択句を置き換えない。"
        "selected_lyric_phraseがNONEなら、本文を「なし」にできる。"
        "比喩的な表現は許し、対象の逐語的直写や人物の接触を義務にしない。"
        + marker + ending
    )


def selected_event_request(original: dict, selected: dict) -> dict:
    valid = {group["id"] for group in phrase_candidates(original)} | {"NONE"}
    if selected.get("id") not in valid:
        raise ValueError("Selected phrase does not belong to current Scene")
    return {**original, "selected_lyric_phrase": selected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=int, action="append")
    parser.add_argument("--seed", type=int, action="append")
    args = parser.parse_args()
    scenes = tuple(args.scene or (3, 4, 5, 6))
    seeds = tuple(args.seed or (2, 3))
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    source_bytes = args.source.read_bytes()
    requests = event_requests(json.loads(source_bytes), scenes)
    baseline = BASE_PROMPT.read_text(encoding="utf-8")
    event_prompt = selected_event_prompt(baseline)
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=2,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "focus-system-prompt.txt").write_text(FOCUS_PROMPT, encoding="utf-8")
    (args.output / "event-system-prompt.txt").write_text(event_prompt, encoding="utf-8")
    manifest = {
        "purpose": "per-Shot lyric phrase evaluation then one Event",
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "model": str(args.model), "config": asdict(config), "results": [],
        "prompts_sha256": {
            "baseline": hashlib.sha256(baseline.encode()).hexdigest(),
            "focus": hashlib.sha256(FOCUS_PROMPT.encode()).hexdigest(),
            "event": hashlib.sha256(event_prompt.encode()).hexdigest(),
        },
    }
    lifecycle = RecordingLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        backend = FixedSeedBackend(lifecycle)
        for seed in seeds:
            call_config = LlamaRuntimeConfig(**{**asdict(config), "seed": seed})
            for scene in scenes:
                original = requests[scene]
                focus_request = focus_payload(original)
                selected = None
                for stage, system, request in (
                    ("baseline", baseline, original),
                    ("focus", FOCUS_PROMPT, focus_request),
                ):
                    payload = canonical_json(request)
                    count = lifecycle.count_serialized_prompt(system + "\n/no_think\n" + payload)
                    if count.count + 1024 > (lifecycle.effective_n_ctx or config.n_ctx):
                        raise ValueError("Scene request exceeds safe context budget")
                    started = time.perf_counter()
                    if stage == "baseline":
                        response = backend.complete_planner(
                            task="scene-author-event", system_prompt=system,
                            payload=payload, config=call_config,
                        )
                        parsed = parse_legacy_response(response, original)
                    else:
                        response = lifecycle.complete_chat(
                            [{"role": "system", "content": system},
                             {"role": "user", "content": "/no_think\n" + payload}],
                            call_config, grammar=focus_grammar(original),
                        )
                        parsed = parse_focus_response(response, original)
                        selected = parsed["selected"]
                    record = {
                        "scene": scene, "seed": seed, "stage": stage,
                        "payload": request,
                        "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                        "prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
                        "prompt_tokens": count.count,
                        "elapsed_seconds": time.perf_counter() - started,
                        "response": response, "parsed": parsed,
                    }
                    (args.output / f"scene{scene}-seed{seed}-{stage}.json").write_text(
                        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    manifest["results"].append({key: record[key] for key in (
                        "scene", "seed", "stage", "payload_sha256", "prompt_tokens",
                        "elapsed_seconds", "response", "parsed",
                    )})
                    print(f"scene={scene} seed={seed} stage={stage} "
                          f"elapsed={record['elapsed_seconds']:.2f}s", flush=True)
                if selected is None:
                    raise AssertionError("Focus stage was not executed")
                event_request = selected_event_request(original, selected)
                payload = canonical_json(event_request)
                count = lifecycle.count_serialized_prompt(event_prompt + "\n/no_think\n" + payload)
                if count.count + 1024 > (lifecycle.effective_n_ctx or config.n_ctx):
                    raise ValueError("Event request exceeds safe context budget")
                started = time.perf_counter()
                response = backend.complete_planner(
                    task="scene-author-event", system_prompt=event_prompt,
                    payload=payload, config=call_config,
                )
                record = {
                    "scene": scene, "seed": seed, "stage": "selected_event",
                    "payload": event_request,
                    "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                    "prompt_sha256": hashlib.sha256(event_prompt.encode()).hexdigest(),
                    "prompt_tokens": count.count,
                    "elapsed_seconds": time.perf_counter() - started,
                    "response": response,
                    "parsed": parse_legacy_response(response, original),
                }
                (args.output / f"scene{scene}-seed{seed}-selected-event.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                manifest["results"].append({key: record[key] for key in (
                    "scene", "seed", "stage", "payload_sha256", "prompt_tokens",
                    "elapsed_seconds", "response", "parsed",
                )})
                print(f"scene={scene} seed={seed} stage=selected_event "
                      f"elapsed={record['elapsed_seconds']:.2f}s", flush=True)
    finally:
        lifecycle.clear()
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
