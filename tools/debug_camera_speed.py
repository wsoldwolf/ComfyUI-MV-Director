"""Research: change only Scene 11 Camera speed, retaining accepted Performance."""
from __future__ import annotations

import argparse
from copy import deepcopy
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
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from nodes.node_emd_compiler.node import _system_prompt
from tools.prepare_beat_motion_h3 import read, save, fresh_plan, finalize
from tools.prepare_instrumental_h3 import render

RUN_NAME = "camera-speed-b15-momiji2-s11-20261004"
CAMERA_FIELD = "scene.10.shot.0.body.1"


def replace_camera_speed(text):
    document = parse_emd(text)
    scenes = [scene for scene in document.scenes if scene.scene_number == 11]
    if len(scenes) != 1 or len(scenes[0].shots) != 1:
        raise ValueError("Requires unique single-Shot Scene 11")
    cameras = [d for d in scenes[0].shots[0].directives if d.kind == "カメラ"]
    if len(cameras) != 1 or cameras[0].text.count("ゆっくり後方へ引き") != 1:
        raise ValueError("Expected accepted slow-pullback Camera")
    camera = cameras[0]
    old = camera.text
    new = old.replace("ゆっくり後方へ引き", "通常速度で後方へ引き")
    lines = text.splitlines(keepends=True)
    index = camera.line_number - 1
    if lines[index].count(old) != 1:
        raise ValueError("Camera source line does not match AST")
    lines[index] = lines[index].replace(old, new, 1)
    result = "".join(lines)
    expected_shot = replace(scenes[0].shots[0],
        body=tuple(line.replace(old, new) if line == "`カメラ` " + old else line
                   for line in scenes[0].shots[0].body),
        directives=tuple(replace(d, text=new) if d == camera else d
                         for d in scenes[0].shots[0].directives))
    expected = replace(document, scenes=tuple(
        replace(scene, shots=(expected_shot,)) if scene.scene_number == 11 else scene
        for scene in document.scenes))
    if parse_emd(result) != expected:
        raise ValueError("EMD changed outside target Camera")
    return result, old, new


def verify_camera_only(baseline, candidate, old, new):
    if not old.strip() or not new.strip() or old == new or len(baseline["shots"]) != 1:
        raise ValueError("Expected one changed Camera in isolated Plan")
    expected = deepcopy(baseline)
    lines = expected["shots"][0]["prompt"]
    if sum(line.count(old) for line in lines) != 1:
        raise ValueError("Baseline Camera must be unique")
    expected["shots"][0]["prompt"] = [line.replace(old, new) for line in lines]
    if candidate != expected:
        raise ValueError("Plan changed outside Camera; do not render")


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    manifest = read(source / "h3-manifest.json")
    if not Path(read(source / "media-checks.json")["videos"]["dance"]["path"]).is_file():
        raise ValueError("Completed baseline video is missing")
    text, old, new = replace_camera_speed((source / "dance.md").read_text(encoding="utf-8"))
    translations = read(source / "translation.json")
    camera = [row for row in translations if row["field_id"] == CAMERA_FIELD]
    if len(camera) != 1 or camera[0]["source"] != old:
        raise ValueError("Baseline Camera translation evidence does not match EMD")
    output.mkdir(parents=True, exist_ok=True)
    for old_name, new_name in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                               ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json")):
        shutil.copy2(source / old_name, output / new_name)
    (output / "dance.md").write_text(text, encoding="utf-8")
    prompt = _system_prompt()
    (output / "compiler-system-prompt.txt").write_text(prompt, encoding="utf-8")
    source_conditions = read(source / "conditions.json")
    save(output / "conditions.json", {
        "source": str(source), "model": source_conditions["model"],
        "runtime": source_conditions["runtime"], "compiler_max_tokens": 4096,
        "translation_cache": str(source / "translation.json"), "planned_new_fields": [CAMERA_FIELD],
        "compiler_system_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "planner_rerun": False})
    save(output / "input-contract.json", {
        "camera_japanese_before": old, "camera_japanese_after": new,
        "camera_english_before": camera[0]["restored"], "emd_camera_only_verified": True,
        "performance_source": str(source / "output-contract.json"),
        "fixed": ["Japanese and English Performance", "Event", "Subject", "field order", "seed", "PCM", "H3 settings"],
        "authored_camera_change": True, "authored_english_insertion": False})
    save(output / "h3-manifest.json", {**manifest,
        "run_names": {"baseline": manifest["run_names"]["dance"], "dance": RUN_NAME},
        "comparison_titles": ["Accepted Performance", "Normal Speed Camera"],
        "comparison_labels": ["baseline", "dance"],
        "comparison": "Camera-only speed wording; accepted Performance reused without inference",
        "source_camera_baseline": str(source), "planner_rerun": False, "compiler_used": True,
        "body_only_plan_verified": False, "performance_and_order_only_verified": False,
        "production_field_order_changed": False, "camera_only_plan_verified": False,
        "new_render_count": 1, "baseline_render_reused": True})
    print("Camera-only EMD prepared on CPU; no inference or rendering", flush=True)


def compile_camera(args, *, camera_field=CAMERA_FIELD, plan_builder=None,
                   plan_validator=verify_camera_only, run_name=RUN_NAME):
    camera_fields = (camera_field,) if isinstance(camera_field, str) else tuple(camera_field)
    if not camera_fields or len(set(camera_fields)) != len(camera_fields):
        raise ValueError("Require unique target Camera fields")
    output = args.output.resolve(strict=True)
    if (output / "compiler-inference.json").exists() or (output / "submission-dance.json").exists():
        raise ValueError("Do not overwrite an attempted comparison")
    with urlopen(args.url + "/queue", timeout=30) as response:
        queue = json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; existing jobs unchanged")
    conditions = read(output / "conditions.json")
    prompt = (output / "compiler-system-prompt.txt").read_text(encoding="utf-8")
    if hashlib.sha256(prompt.encode()).hexdigest() != conditions["compiler_system_sha256"]:
        raise ValueError("Prepared Compiler prompt changed")
    cache = {}
    for row in read(Path(conditions["translation_cache"])):
        key, value = tuple(row["fragments"]), tuple(row["translated"])
        if key in cache and cache[key] != value:
            raise ValueError("Conflicting baseline translation evidence")
        cache[key] = value
    config = replace(LlamaRuntimeConfig(**conditions["runtime"]),
                     temperature=0.0, max_tokens=conditions["compiler_max_tokens"])
    lifecycle = LlamaCppLifecycle()
    try:
        started = time.perf_counter()
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        load_s = time.perf_counter() - started
        print(f"31B loaded in {load_s:.1f}s", flush=True)
        translator = LlamaPromptTranslator(lifecycle, system_prompt=prompt, runtime_config=config)

        class CachedTranslator:
            def __init__(self):
                self.translation_trace = []
                self.reused = False
            def translate(self, units):
                key = tuple(units)
                self.reused = key in cache
                return cache[key] if self.reused else translator.translate(units)
            def record_field_translation(self, **kwargs):
                self.translation_trace.append({**kwargs, "reused_saved_translation": self.reused})

        cached = CachedTranslator()
        started = time.perf_counter()
        compiled = compile_ref2va((output / "dance.md").read_text(encoding="utf-8"), cached)
        uncached = [r["field_id"] for r in cached.translation_trace if not r["reused_saved_translation"]]
        save(output / "translation.json", cached.translation_trace)
        save(output / "compiler-inference.json", {"elapsed_s": time.perf_counter()-started,
            "model_load_s": load_s, "uncached_fields": uncached})
        if uncached != list(camera_fields):
            raise ValueError("Unexpected new translation fields; do not render")
        for index, shot in enumerate(compiled.plan["shots"], 1):
            shot["seed"] = 20261003 + index
        save(output / "compiled-full-plan.json", compiled.plan)
        manifest = read(output / "h3-manifest.json")
        candidate = (plan_builder(compiled.plan) if plan_builder is not None
                     else fresh_plan(compiled.plan, manifest["render_frames"]))
        baseline = read(output / "baseline-plan.json")
        if plan_builder is None:
            candidate["shots"][0]["continuation_mode"] = baseline["shots"][0]["continuation_mode"]
        contract = read(output / "input-contract.json")
        cameras = [next(r for r in cached.translation_trace if r["field_id"] == field)
                   for field in camera_fields]
        after = cameras[0]["restored"] if isinstance(camera_field, str) else [r["restored"] for r in cameras]
        plan_validator(baseline, candidate, contract["camera_english_before"], after)
        save(output / "dance-plan.json", candidate)
        save(output / "output-contract.json", {**contract, "camera_english_after": after,
            "plan_camera_only_verified": True, "performance_japanese_and_english_unchanged": True,
            "field_order_unchanged": True, "no_semantic_prose_repair": True})
        graph = read(output / "h3-baseline.json")
        for key in ("24", "37", "48"):
            graph[key]["inputs"]["plan_json"] = json.dumps(candidate, ensure_ascii=False)
        graph["24"]["inputs"]["run_name"] = run_name
        graph["21"]["inputs"]["filename"] = run_name
        save(output / "h3-dance.json", graph)
        save(output / "h3-manifest.json", {**manifest, "camera_only_plan_verified": True})
        print("Camera-only Plan verified; inspect translation before render", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "compile", "render", "finalize"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "prepare":
        if not args.source:
            parser.error("prepare requires --source")
        prepare(args)
    elif args.task == "compile":
        compile_camera(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
