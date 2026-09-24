"""Compare a frozen Scene Event with a lyric-only focus selection first.

The first LLM call sees only the current Scene's original lyric rows. The
second sees the unchanged Event request plus the selected row. This tool does
not edit the production Planner, EMD, or H3 workflow.
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
    source_ids,
)
from tools.offline_section_performance_probe import FixedSeedBackend, RecordingLifecycle

FOCUS_PROMPT = (
    "あなたはアニメMVの一つのSceneの原歌詞だけを読み、Eventで扱う着想の焦点を一つ選ぶ。"
    "入力には現在Sceneの原歌詞行と所属Shotだけがある。全Shotを読み、画面で表現できる"
    "具体物・外部現象・変化があれば、その根拠となる原歌詞行のIDを選ぶ。"
    "先頭の抽象語や場所を機械的に優先せず、後続行の意味も読む。"
    "比喩からの映像表現は許し、名詞の逐語的な直写や人物の接触を義務にしない。"
    "適切な外部Eventが無ければNONEを選ぶ。背景・人物資料・演出候補はここでは見ない。"
    "出力は一行だけ、SOURCE<TAB>1<TAB>許可されたID。説明を加えない。"
)
_FOCUS_LINE = re.compile(r"SOURCE\t1\t([^\t\n]+)\n?\Z")


def lyric_only_payload(request: dict) -> dict:
    return {
        "scene_number": request["scene_number"],
        "original_lyrics": [
            {"shot": row["shot"], "lyrics": [
                {"id": f"LYRIC:shot{row['shot']}:line{line['source_line']}",
                 "text": line["text"]}
                for line in row["lyrics"]
            ]}
            for row in request["original_lyrics"]
        ],
    }


def focus_ids(request: dict) -> tuple[str, ...]:
    return tuple(value for value in source_ids(request) if value.startswith("LYRIC:")) + ("NONE",)


def focus_grammar(request: dict, *, reverse_choices: bool = False) -> str:
    ids = focus_ids(request)
    if reverse_choices:
        ids = tuple(reversed(ids))
    choices = " | ".join(
        json.dumps(value, ensure_ascii=False) for value in ids
    )
    return 'root ::= "SOURCE\\t1\\t" choice "\\n"?\n' + f"choice ::= {choices}\n"


def parse_focus_response(response: str, request: dict) -> dict:
    matched = _FOCUS_LINE.fullmatch(response)
    if not matched or matched.group(1) not in focus_ids(request):
        raise ValueError("Focus response did not select an existing lyric row or NONE")
    selected = matched.group(1)
    if selected == "NONE":
        return {"id": "NONE", "shot": None, "source_line": None, "text": ""}
    matches = [
        {"id": line["id"], "shot": row["shot"],
         "source_line": int(line["id"].split("line")[-1]), "text": line["text"]}
        for row in lyric_only_payload(request)["original_lyrics"]
        for line in row["lyrics"] if line["id"] == selected
    ]
    if len(matches) != 1:
        raise ValueError("Selected lyric source is ambiguous")
    return matches[0]


def selected_event_prompt(baseline: str) -> str:
    start, marker, ending = baseline.partition("一行のみ、EVENT")
    if not marker:
        raise ValueError("Unexpected frozen Event prompt")
    return start + (
        "selected_lyric_sourceは現在Sceneの原歌詞だけを読んで先に選んだ焦点である。"
        "その原文と前後の歌詞を踏まえて今回の可視変化を作る。scene_environmentは"
        "その対象の位置と照明を支える資料であり、紅葉や設備に主題を置き換えない。"
        "selected_lyric_sourceがNONEなら、無理に外部Eventを作らず本文を「なし」にできる。"
        "比喩的な表現、予告、余韻は許すが、選択した歌詞と無関係な出来事にはしない。"
        + marker + ending
    )


def selected_event_request(original: dict, selected: dict) -> dict:
    if selected.get("id") not in focus_ids(original):
        raise ValueError("Selected Event focus is not from current Scene lyrics")
    return {**original, "selected_lyric_source": selected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=int, action="append")
    parser.add_argument("--seed", type=int, action="append")
    parser.add_argument("--reverse-focus-choices", action="store_true")
    args = parser.parse_args()
    scenes = tuple(args.scene or (3, 4, 5, 6))
    seeds = tuple(args.seed or (2, 3))
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    source_bytes = args.source.read_bytes()
    requests = event_requests(json.loads(source_bytes), scenes)
    baseline_prompt = BASE_PROMPT.read_text(encoding="utf-8")
    chosen_prompt = selected_event_prompt(baseline_prompt)
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=2,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "focus-system-prompt.txt").write_text(FOCUS_PROMPT, encoding="utf-8")
    (args.output / "event-system-prompt.txt").write_text(chosen_prompt, encoding="utf-8")
    manifest = {
        "purpose": "lyric-only focus then frozen Scene Event comparison",
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "model": str(args.model), "config": asdict(config), "results": [],
        "reverse_focus_choices": args.reverse_focus_choices,
        "prompts_sha256": {
            "baseline": hashlib.sha256(baseline_prompt.encode()).hexdigest(),
            "focus": hashlib.sha256(FOCUS_PROMPT.encode()).hexdigest(),
            "selected_event": hashlib.sha256(chosen_prompt.encode()).hexdigest(),
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
                focus_request = lyric_only_payload(original)
                focus_json = canonical_json(focus_request)
                stages = (
                    ("baseline", baseline_prompt, canonical_json(original)),
                    ("focus", FOCUS_PROMPT, focus_json),
                )
                selected = None
                for stage, prompt, payload in stages:
                    tokens = lifecycle.count_serialized_prompt(prompt + "\n/no_think\n" + payload)
                    if tokens.count + 1024 > (lifecycle.effective_n_ctx or config.n_ctx):
                        raise ValueError("Request exceeds safe context budget")
                    started = time.perf_counter()
                    if stage == "baseline":
                        response = backend.complete_planner(
                            task="scene-author-event", system_prompt=prompt,
                            payload=payload, config=call_config,
                        )
                        parsed = parse_legacy_response(response, original)
                    else:
                        response = lifecycle.complete_chat(
                            [{"role": "system", "content": prompt},
                             {"role": "user", "content": "/no_think\n" + payload}],
                            call_config, grammar=focus_grammar(
                                original, reverse_choices=args.reverse_focus_choices,
                            ),
                        )
                        parsed = parse_focus_response(response, original)
                        selected = parsed
                    record = {
                        "scene": scene, "seed": seed, "stage": stage,
                        "payload": json.loads(payload),
                        "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "prompt_tokens": tokens.count,
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
                chosen_request = selected_event_request(original, selected)
                payload = canonical_json(chosen_request)
                tokens = lifecycle.count_serialized_prompt(
                    chosen_prompt + "\n/no_think\n" + payload
                )
                if tokens.count + 1024 > (lifecycle.effective_n_ctx or config.n_ctx):
                    raise ValueError("Selected Event request exceeds safe context budget")
                started = time.perf_counter()
                response = backend.complete_planner(
                    task="scene-author-event", system_prompt=chosen_prompt,
                    payload=payload, config=call_config,
                )
                record = {
                    "scene": scene, "seed": seed, "stage": "selected_event",
                    "payload": chosen_request,
                    "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                    "prompt_sha256": hashlib.sha256(chosen_prompt.encode()).hexdigest(),
                    "prompt_tokens": tokens.count,
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
