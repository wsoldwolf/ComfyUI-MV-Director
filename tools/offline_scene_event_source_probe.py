"""Compare a frozen Scene Event with a lyric/candidate-source declaration.

This is an Event-only experiment. It never changes production Planner output,
lyrics, Shot timing, EMD, or H3 inputs. Raw requests and responses are saved.
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
from tools.offline_section_performance_probe import FixedSeedBackend, RecordingLifecycle

DEFAULT_SOURCE = (
    ROOT / "docs/assets/research/scene-composition-full-sequence-2026-09-23"
    / "p1b-six-scenes-seed2-v2/summary.json"
)
BASE_PROMPT = ROOT / "prompts/experiments/scene_author_p1b_event.txt"
MODEL = Path(
    "E:/ComfyUI/models/LLM/GGUF/Qwen3-8B-Abliterated/"
    "qwen3-8b-abliterated-Q4_K_M.gguf"
)
_SOURCE_LINE = re.compile(
    r"EVENT\t1\tSOURCE=([^｜\t\n]+)｜FOCUS=([^｜\t\n]+)"
    r"｜SHOT=([1-9][0-9]*)｜([^\t\n]+)\n?\Z"
)
_LEGACY_LINE = re.compile(r"EVENT\t1\tSHOT=([1-9][0-9]*)｜([^\t\n]+)\n?\Z")


def event_requests(summary: dict, scenes: tuple[int, ...]) -> dict[int, dict]:
    """Read only canonical, unique saved Event requests for selected Scenes."""
    result = {}
    for call in summary["trace"]:
        if call["task"] != "scene-author-event":
            continue
        raw = call["payload"]
        request = json.loads(raw)
        scene = request["scene_number"]
        if scene not in scenes:
            continue
        if raw != canonical_json(request) or scene in result:
            raise ValueError("Event fixture is noncanonical or repeated")
        result[scene] = request
    if set(result) != set(scenes):
        raise ValueError("Missing selected Scene Event request")
    return result


def source_ids(request: dict) -> tuple[str, ...]:
    lyrics = [
        f"LYRIC:shot{shot['shot']}:line{lyric['source_line']}"
        for shot in request["original_lyrics"] for lyric in shot["lyrics"]
    ]
    candidates = [
        f"CANDIDATE:{index}"
        for index, _ in enumerate(request["staging_candidates_optional"], 1)
    ]
    result = tuple([*lyrics, *candidates, "NONE"])
    if len(set(result)) != len(result) or not lyrics:
        raise ValueError("Source IDs must be unique and contain current lyrics")
    return result


def source_prompt(baseline: str) -> str:
    prefix, separator, _ = baseline.partition("一行のみ、EVENT")
    if not separator:
        raise ValueError("Unexpected baseline Event prompt")
    return prefix + (
        "まず今回の出来事の根拠をSOURCEで選ぶ。原歌詞の具体物・現象が"
        "現在Sceneにある場合はその原歌詞行を優先し、候補を採用した場合は"
        "CANDIDATE番号を選ぶ。背景は対象の配置資料でありSOURCEではない。"
        "歌詞の比喩は自由に映像化してよく、具体物を毎回必ず接触・直写する義務はない。"
        "出来事が適さない場合はSOURCE=NONE、FOCUS=なし、本文=なしを選べる。"
        "FOCUSには自分が選んだ対象又は表現の焦点を短く記し、本文との関係を保つ。"
        "一行のみ、EVENT<TAB>1<TAB>SOURCE=許可されたID｜FOCUS=短い焦点｜"
        "SHOT=番号｜短い日本語本文。見出し、Markdown、余分な行を出さない。"
    )


def source_grammar(request: dict) -> str:
    quoted = lambda value: json.dumps(value, ensure_ascii=False)
    sources = " | ".join(quoted(value) for value in source_ids(request))
    shots = " | ".join(quoted(str(row["shot"])) for row in request["shot_positions"])
    return (
        'root ::= "EVENT\\t1\\tSOURCE=" source "｜FOCUS=" focus '
        '"｜SHOT=" shot "｜" body "\\n"?\n'
        f"source ::= {sources}\n"
        f"shot ::= {shots}\n"
        'focus ::= [^｜\\x00-\\x1f]+\n'
        'body ::= [^\\x00-\\x1f]+\n'
    )


def parse_source_response(response: str, request: dict) -> dict:
    match = _SOURCE_LINE.fullmatch(response)
    if not match:
        raise ValueError("Source Event response has invalid fields")
    source, focus, shot, body = match.groups()
    if source not in source_ids(request):
        raise ValueError("Source Event references an unknown source")
    if int(shot) not in {row["shot"] for row in request["shot_positions"]}:
        raise ValueError("Source Event references an unknown Shot")
    if source == "NONE" and (focus != "なし" or body != "なし"):
        raise ValueError("NONE source must describe no Event")
    return {"source": source, "focus": focus, "shot": int(shot), "body": body}


def parse_legacy_response(response: str, request: dict) -> dict:
    match = _LEGACY_LINE.fullmatch(response)
    if not match or int(match.group(1)) not in {
        row["shot"] for row in request["shot_positions"]
    }:
        raise ValueError("Legacy Event response is invalid")
    return {"shot": int(match.group(1)), "body": match.group(2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=int, action="append")
    parser.add_argument("--seed", type=int, action="append")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    scenes = tuple(args.scene or (3, 4, 5, 6))
    seeds = tuple(args.seed or (2, 3))
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    source_bytes = args.source.read_bytes()
    requests = event_requests(json.loads(source_bytes), scenes)
    baseline = BASE_PROMPT.read_text(encoding="utf-8")
    changed = source_prompt(baseline)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "P0/P1 source-aware Event contract comparison",
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "model": str(args.model), "seeds": list(seeds),
        "baseline_prompt_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "source_prompt_sha256": hashlib.sha256(changed.encode()).hexdigest(),
        "cases": [], "results": [],
    }
    (args.output / "source-prompt.txt").write_text(changed, encoding="utf-8")
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=3072, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=2,
    )
    manifest["config"] = asdict(config)
    for scene in scenes:
        request = requests[scene]
        payload = canonical_json(request)
        manifest["cases"].append({
            "scene": scene,
            "lyrics": [
                {"shot": shot["shot"], "source_line": line["source_line"],
                 "text": line["text"]}
                for shot in request["original_lyrics"] for line in shot["lyrics"]
            ],
            "candidate_count": len(request["staging_candidates_optional"]),
            "source_ids": list(source_ids(request)),
            "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        })
    lifecycle = RecordingLifecycle()
    try:
        if not args.cpu_only:
            lifecycle.ensure_loaded(args.model, config)
            backend = FixedSeedBackend(lifecycle)
            for seed in seeds:
                call_config = LlamaRuntimeConfig(**{**asdict(config), "seed": seed})
                for scene in scenes:
                    request = requests[scene]
                    payload = canonical_json(request)
                    for condition in ("legacy", "source"):
                        system = baseline if condition == "legacy" else changed
                        token_count = lifecycle.count_serialized_prompt(
                            system + "\n/no_think\n" + payload
                        )
                        if token_count.count + 1024 > (lifecycle.effective_n_ctx or config.n_ctx):
                            raise ValueError("Event request exceeds safe context budget")
                        started = time.perf_counter()
                        if condition == "legacy":
                            response = backend.complete_planner(
                                task="scene-author-event", system_prompt=system,
                                payload=payload, config=call_config,
                            )
                        else:
                            response = lifecycle.complete_chat(
                                [{"role": "system", "content": system},
                                 {"role": "user", "content": "/no_think\n" + payload}],
                                call_config, grammar=source_grammar(request),
                            )
                        try:
                            parsed = (
                                parse_legacy_response(response, request)
                                if condition == "legacy"
                                else parse_source_response(response, request)
                            )
                            parse_error = ""
                        except ValueError as exc:
                            parsed, parse_error = {}, str(exc)
                        record = {
                            "scene": scene, "seed": seed, "condition": condition,
                            "payload": request, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                            "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
                            "prompt_tokens": token_count.count,
                            "elapsed_seconds": time.perf_counter() - started,
                            "response": response, "parsed": parsed,
                            "parse_error": parse_error,
                        }
                        path = args.output / f"scene{scene}-seed{seed}-{condition}.json"
                        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
                        manifest["results"].append({
                            key: record[key] for key in (
                                "scene", "seed", "condition", "prompt_tokens",
                                "elapsed_seconds", "response", "parsed", "parse_error",
                            )
                        })
                        print(f"scene={scene} seed={seed} condition={condition} "
                              f"elapsed={record['elapsed_seconds']:.2f}s", flush=True)
    finally:
        lifecycle.clear()
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
