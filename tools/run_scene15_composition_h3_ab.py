"""Prepare a controlled Scene 15 H3 comparison of cyclic, retry, and none.

This is research-only. All song inputs and authored prose stay identical.
Only the Scene 15 profile composition marker and text vary.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from tools import run_gemma4_31b_full as base


RESEARCH = Path(r"E:\ComfyUI\projects\ComfyUI-MV-Director-research\docs\assets\research")
SOURCE = RESEARCH / "gemma4-31b-post-author-full-2026-09-25" / "planned.md"
SUMMARY = RESEARCH / "gemma4-31b-post-author-full-2026-09-25" / "planner-summary.json"
GRAPH = RESEARCH / "refsheet-scene3-ab-2026-09-25" / "original-api-prompt.json"
RETRY = RESEARCH / "gemma4-31b-composition-audit-probe-2026-09-25" / "scene15-choice-retry.json"
DEST = RESEARCH / "gemma4-31b-composition-audit-h3-s15-2026-09-25"
MODEL = Path(r"E:\ComfyUI\models\LLM\GGUF\Qwen3-8B-Abliterated\qwen3-8b-abliterated-Q4_K_M.gguf")
PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "prompt_translation_ja_en_system_prompt.txt"
VARIANTS = ("current", "retry_choice", "without_composition")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare() -> None:
    original = SOURCE.read_text(encoding="utf-8")
    content = json.loads(SUMMARY.read_text(encoding="utf-8"))["content"]
    rows = [row for row in content["motion_compositions"] if row[0] == 15]
    if len(rows) != 1 or rows[0][1] != 1:
        raise ValueError("Expected exactly one Scene 15 composition on Shot 1")
    _scene, _shot, source, index, motion = rows[0]
    marker = f"> `モーション補完` source={source} template={index} "
    lines = original.splitlines()
    start = lines.index("> `シーン` 15")
    end = lines.index("> `シーン` 16")
    block = lines[start:end]
    markers = [line for line in block if line.startswith(marker)]
    action = f"* `演技` {motion}"
    if len(markers) != 1 or block.count(action) != 1:
        raise ValueError("Scene 15 composition marker/text are not uniquely identified")
    reduced_block = [line for line in block if line != markers[0] and line != action]
    reduced = "\n".join(lines[:start] + reduced_block + lines[end:]) + "\n"
    retry = json.loads(RETRY.read_text(encoding="utf-8"))
    if retry["old_choice"] != index or retry["source_scene"] != 15:
        raise ValueError("Composition retry does not match frozen Scene 15")
    retry_motion = retry["retry_composition"]
    if not isinstance(retry_motion, str) or not retry_motion:
        raise ValueError("Composition retry did not select a template")
    retry_digest = hashlib.sha256(retry_motion.encode("utf-8")).hexdigest()
    retry_marker = (
        f"> `モーション補完` source={source} "
        f"template={retry['retry_choice']} sha256={retry_digest}"
    )
    retry_block = [
        retry_marker
        if line == markers[0] else
        f"* `演技` {retry_motion}" if line == action else line
        for line in block
    ]
    retried = "\n".join(lines[:start] + retry_block + lines[end:]) + "\n"
    for variant, text in zip(VARIANTS, (original, retried, reduced)):
        parse_emd(text)
        path = DEST / variant / "planned.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _write(DEST / "source-manifest.json", {
        "source_emd": str(SOURCE), "source_emd_sha256": _sha(SOURCE),
        "planner_summary": str(SUMMARY), "planner_summary_sha256": _sha(SUMMARY),
        "removed_scene": 15, "removed_shot": 1,
        "removed_motion_source": source, "removed_template_id": index,
        "retry_decision": str(RETRY), "retry_decision_sha256": _sha(RETRY),
        "retry_template_id": retry["retry_choice"],
        "compiler_model": str(MODEL),
        "h3_graph": str(GRAPH), "h3_graph_sha256": _sha(GRAPH),
        "h3_seed": 42, "h3_megapixels": 0.4,
        "variants": list(VARIANTS),
    })
    print("Prepared three EMD variants differing only in Scene 15 composition", flush=True)


def compile_variants() -> None:
    config = LlamaRuntimeConfig(
        max_tokens=4096, temperature=0.0, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=256,
        n_ctx=16384, flash_attn=True, kv_cache_type="q8_0",
        op_offload=True, keep_model_loaded=False, seed=1,
    )
    lifecycle = LlamaCppLifecycle()
    lifecycle.ensure_loaded(MODEL, config)
    try:
        compiled = {}
        for variant in VARIANTS:
            target = DEST / variant
            translator = LlamaPromptTranslator(
                lifecycle, system_prompt=PROMPT.read_text(encoding="utf-8"),
                runtime_config=config,
            )
            result = compile_ref2va(
                (target / "planned.md").read_text(encoding="utf-8"),
                translator, steps=8,
            )
            compiled[variant] = json.loads(result.plan_json())
            (target / "plan.json").write_text(result.plan_json(), encoding="utf-8")
            _write(target / "compile-summary.json", {
                "translation_batches": translator.batch_count,
                "protocol_recovered": translator.protocol_recovered_count,
                "segmented_recovered": translator.segmented_recovered_count,
                "cleanup_recovered": translator.cleanup_recovered_count,
                "translation_trace": translator.translation_trace,
                "plan_sha256": _sha(target / "plan.json"),
            })
            print(f"Compiled {variant}: batches={translator.batch_count}", flush=True)
    finally:
        lifecycle.clear()
    isolate_compiled(compiled)


def isolate_compiled(compiled: dict[str, dict] | None = None) -> None:
    if compiled is None:
        compiled = {
            variant: json.loads((DEST / variant / "plan.json").read_text(encoding="utf-8"))
            for variant in VARIANTS
        }
    current = compiled["current"]
    if any(len(plan["shots"]) != 16 for plan in compiled.values()):
        raise ValueError("Expected 16 Scene entries in every Plan")
    changed_by_variant = {
        variant: [index + 1 for index, (left, right) in enumerate(zip(
            current["shots"], plan["shots"]
        )) if left != right]
        for variant, plan in compiled.items() if variant != "current"
    }
    _write(DEST / "plan-comparison.json", {"changed_scenes": changed_by_variant})
    if any(15 not in changed for changed in changed_by_variant.values()):
        raise ValueError("Scene 15 Plan did not change in every comparison")
    # Isolate one variable even if independent 8B translation changed other
    # fields (including Subject definitions) within Scene 15. Only the first
    # Shot's detailed-description line may differ in the H3 input.
    for variant in VARIANTS[1:]:
        isolated = copy.deepcopy(current)
        base_prompt = isolated["shots"][14]["prompt"]
        other_prompt = compiled[variant]["shots"][14]["prompt"]
        base_positions = [index for index, line in enumerate(base_prompt)
                          if line.startswith("[Shot 1]")]
        other_lines = [line for line in other_prompt if line.startswith("[Shot 1]")]
        if len(base_positions) != 1 or len(other_lines) != 1:
            raise ValueError("Scene 15 Shot 1 prompt line was not unique")
        base_prompt[base_positions[0]] = other_lines[0]
        path = DEST / variant / "isolated-plan.json"
        path.write_text(json.dumps(isolated, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        remaining = [number + 1 for number, (left, right) in enumerate(zip(
            current["shots"], isolated["shots"]
        )) if left != right]
        if remaining != [15]:
            raise ValueError(f"Isolation changed unexpected Scenes: {remaining}")
    print(f"Compiled three variants; translation-affected Scenes={changed_by_variant}; "
          "H3 isolates Scene 15", flush=True)


def prepare_video() -> None:
    frozen = json.loads(GRAPH.read_text(encoding="utf-8"))
    if frozen["47"]["inputs"]["megapixels"] != 0.4:
        raise ValueError("Frozen graph is not 0.4MP")
    if frozen["49"]["inputs"]["seed"] != 42:
        raise ValueError("Frozen graph seed changed")
    for variant in VARIANTS:
        plan_path = (DEST / variant / (
            "plan.json" if variant == "current" else "isolated-plan.json"
        ))
        text = plan_path.read_text(encoding="utf-8")
        graph = copy.deepcopy(frozen)
        graph["26"]["inputs"]["image"] = "image001_mikofox_ref.jpg"
        for node in ("24", "37", "48"):
            graph[node]["inputs"]["plan_json"] = text
        graph["48"]["inputs"].update({
            "enable": True, "scene_start": 15, "scene_length": 1,
        })
        run_name = f"composition-audit-s15-{variant}-20260925"
        graph["24"]["inputs"]["run_name"] = run_name
        graph["21"]["inputs"]["filename"] = run_name
        target = DEST / variant
        _write(target / "h3-api-prompt.json", graph)
        _write(target / "h3-manifest.json", {
            "variant": variant, "run_name": run_name,
            "plan_sha256": _sha(plan_path),
            "api_prompt_sha256": _sha(target / "h3-api-prompt.json"),
            "scene": 15, "seed": 42, "megapixels": 0.4,
        })
        print(f"Prepared {variant}: {run_name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "compile", "isolate", "prepare_video"))
    args = parser.parse_args()
    {"prepare": prepare, "compile": compile_variants,
     "isolate": isolate_compiled,
     "prepare_video": prepare_video}[args.phase]()
