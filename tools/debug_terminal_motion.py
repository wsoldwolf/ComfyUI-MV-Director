"""Research: retain an accepted turn and replace only its terminal settling clause."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import shutil
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.emd import parse_emd
from core.compiler import LlamaPromptTranslator
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from nodes.node_emd_compiler.node import _system_prompt
from tools.prepare_beat_motion_h3 import read, save, finalize
from tools.prepare_instrumental_h3 import render
from tools.debug_simple_dance import replace_body

RUN_NAME = "terminal-motion-b17-momiji2-s11-20261004"
OLD_JAPANESE = "静かに呼吸を整えて次なる展開へ備える。"
NEW_JAPANESE = "人物は回転の勢いを次の踏み替えへ送り、体幹と左腕の流れをつなげて踊り続ける。"
OLD_ENGLISH = "the breath is quietly steadied in preparation for the next development."


def replace_terminal_emd(text):
    document = parse_emd(text)
    scenes = [s for s in document.scenes if s.scene_number == 11]
    if len(scenes) != 1 or len(scenes[0].shots) != 1:
        raise ValueError("Requires unique single-Shot Scene 11")
    performances = [d for d in scenes[0].shots[0].directives if d.kind == "演技"]
    if len(performances) != 1:
        raise ValueError("Expected one Performance")
    performance = performances[0]
    old = performance.text
    if not old.endswith(OLD_JAPANESE) or old.count(OLD_JAPANESE) != 1:
        raise ValueError("Expected accepted settling ending")
    new = old[:-len(OLD_JAPANESE)] + NEW_JAPANESE
    lines = text.splitlines(keepends=True)
    index = performance.line_number - 1
    if lines[index].count(old) != 1:
        raise ValueError("Source line does not match AST")
    lines[index] = lines[index].replace(old, new, 1)
    result = "".join(lines)
    shot = replace(scenes[0].shots[0],
        body=tuple("`演技` " + new if line == "`演技` " + old else line for line in scenes[0].shots[0].body),
        directives=tuple(replace(d, text=new) if d == performance else d for d in scenes[0].shots[0].directives))
    expected = replace(document, scenes=tuple(replace(s, shots=(shot,)) if s.scene_number == 11 else s
                                              for s in document.scenes))
    if parse_emd(result) != expected:
        raise ValueError("EMD changed outside terminal Performance")
    return result, old, new


def replace_terminal_plan(baseline, old_performance, ending):
    if not old_performance.endswith(OLD_ENGLISH) or old_performance.count(OLD_ENGLISH) != 1:
        raise ValueError("Expected accepted English terminal clause")
    if not isinstance(ending, str) or not ending.strip() or OLD_ENGLISH in ending:
        raise ValueError("Expected a new nonempty translated ending")
    # Reuse the original English prefix byte-for-byte; use the translated unit AS IS.
    new_performance = old_performance[:-len(OLD_ENGLISH)] + ending
    candidate = replace_body(baseline, old_performance, new_performance)
    return candidate, new_performance


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    manifest = read(source / "h3-manifest.json")
    if not Path(read(source / "media-checks.json")["videos"]["dance"]["path"]).is_file():
        raise ValueError("Completed accepted baseline is missing")
    text, old, new = replace_terminal_emd((source / "dance.md").read_text(encoding="utf-8"))
    contract = read(source / "output-contract.json")
    if contract["performance_japanese"] != old or not contract["performance_english"].endswith(OLD_ENGLISH):
        raise ValueError("Baseline translation evidence mismatch")
    output.mkdir(parents=True, exist_ok=True)
    for old_name, new_name in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                               ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json")):
        shutil.copy2(source / old_name, output / new_name)
    (output / "dance.md").write_text(text, encoding="utf-8")
    prompt = _system_prompt()
    (output / "compiler-system-prompt.txt").write_text(prompt, encoding="utf-8")
    source_conditions = read(source / "conditions.json")
    save(output / "conditions.json", {"source": str(source), "model": source_conditions["model"],
        "runtime": source_conditions["runtime"], "compiler_max_tokens": 4096,
        "compiler_system_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "planner_rerun": False})
    save(output / "input-contract.json", {"performance_japanese_before": old, "performance_japanese_after": new,
        "performance_english_before": contract["performance_english"], "ending_japanese_before": OLD_JAPANESE,
        "ending_japanese_after": NEW_JAPANESE, "ending_english_before": OLD_ENGLISH,
        "emd_terminal_only_verified": True, "translation_scope": "new ending unit only",
        "fixed": ["Performance prefix", "Subject", "Event", "Camera", "field order", "seed", "PCM", "length", "H3 settings"],
        "research_authored_terminal_clause": True})
    save(output / "h3-manifest.json", {**manifest,
        "run_names": {"baseline": manifest["run_names"]["dance"], "dance": RUN_NAME},
        "comparison_titles": ["Accepted Performance", "Continuing Ending"], "comparison_labels": ["baseline", "dance"],
        "comparison": "Terminal clause only; accepted preparation and turn frozen",
        "planner_rerun": False, "compiler_used": True, "compiler_scope": "one ending unit",
        "source_terminal_baseline": str(source), "production_field_order_changed": False,
        "performance_and_order_only_verified": False, "terminal_only_plan_verified": False,
        "new_render_count": 1, "baseline_render_reused": True})
    print("Ending-only comparison prepared on CPU", flush=True)


def compile_ending(args):
    output = args.output.resolve(strict=True)
    if (output / "compiler-inference.json").exists() or (output / "submission-dance.json").exists():
        raise ValueError("Do not overwrite an attempted comparison")
    with urlopen(args.url + "/queue", timeout=30) as response:
        queue = json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; leave existing jobs intact")
    conditions = read(output / "conditions.json")
    prompt = (output / "compiler-system-prompt.txt").read_text(encoding="utf-8")
    if hashlib.sha256(prompt.encode()).hexdigest() != conditions["compiler_system_sha256"]:
        raise ValueError("Prepared Compiler system prompt changed")
    contract = read(output / "input-contract.json")
    config = replace(LlamaRuntimeConfig(**conditions["runtime"]), temperature=0.0,
                     max_tokens=conditions["compiler_max_tokens"])
    lifecycle = LlamaCppLifecycle()
    try:
        start = time.perf_counter()
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        load_s = time.perf_counter() - start
        print(f"31B loaded in {load_s:.1f}s", flush=True)
        translator = LlamaPromptTranslator(lifecycle, system_prompt=prompt, runtime_config=config)
        start = time.perf_counter()
        translated = tuple(translator.translate((contract["ending_japanese_after"],)))
        save(output / "compiler-inference.json", {"model_load_s": load_s, "elapsed_s": time.perf_counter()-start,
            "source_units": [contract["ending_japanese_after"]], "translated_units": list(translated),
            "research_segmentation": True, "whole_performance_retranslated": False})
        if len(translated) != 1:
            raise ValueError("Expected one translated ending")
        baseline = read(output / "baseline-plan.json")
        candidate, performance = replace_terminal_plan(baseline, contract["performance_english_before"], translated[0])
        save(output / "dance-plan.json", candidate)
        save(output / "output-contract.json", {**contract, "ending_english_after": translated[0],
            "performance_english_after": performance, "plan_terminal_only_verified": True,
            "no_english_semantic_repair": True, "translated_ending_inserted_as_is": True,
            "research_authored_segmentation_and_join": True})
        graph = read(output / "h3-baseline.json")
        for key in ("24", "37", "48"):
            graph[key]["inputs"]["plan_json"] = json.dumps(candidate, ensure_ascii=False)
        graph["24"]["inputs"]["run_name"] = RUN_NAME
        graph["21"]["inputs"]["filename"] = RUN_NAME
        save(output / "h3-dance.json", graph)
        manifest = read(output / "h3-manifest.json")
        save(output / "h3-manifest.json", {**manifest, "terminal_only_plan_verified": True})
        print("Translated ending: " + translated[0], flush=True)
        print("Plan verified: only terminal English clause changed", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "compile", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--url", default="http://127.0.0.1:8191")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "prepare":
        if not args.source:
            p.error("prepare requires --source")
        prepare(args)
    elif args.task == "compile":
        compile_ending(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
