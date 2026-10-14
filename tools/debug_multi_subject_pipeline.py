"""Replay multiple Subject ports through the production nodes.

Default mode validates inputs and exports preparation only (no GPU/model).
--infer explicitly runs Enhancer, Planner and Compiler, but never H3/Vision.
Research inputs and evidence must stay outside this repository.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import inspect
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.direction import DirectionEnhancerInput
from core.emd import parse_emd
from core.emd.subject_fragment import SUBJECT_INPUT_NAMES
from core.planner.template import parse_template_emd
from nodes.common.gguf_discovery import resolve_comfy_gguf_model
from nodes.node_direction_enhancer import node as enhancer_module
from nodes.node_timeline_planner import node as planner_module
from nodes.node_emd_compiler import node as compiler_module


NODE_STAGES = (
    ("enhancer", enhancer_module, enhancer_module.MVDirectorDirectionEnhancer),
    ("planner", planner_module, planner_module.MVDirectorTimelinePlanner),
    ("compiler", compiler_module, compiler_module.MVDirectorEMDCompiler),
)


def workflow_settings(workflow, node_class):
    """Read scalar widget order from the real schema, including seed controls."""
    item, = [n for n in workflow["nodes"] if n["type"] == node_class.__name__]
    values = item["widgets_values"]
    result, position = {}, 0
    schema = node_class.INPUT_TYPES()
    for section in ("required", "optional"):
        for name, spec in schema.get(section, {}).items():
            options = spec[1] if len(spec) > 1 else {}
            if options.get("forceInput") or not (
                isinstance(spec[0], list) or spec[0] in {"STRING", "INT", "FLOAT", "BOOLEAN"}
            ):
                continue
            if position >= len(values):
                raise ValueError(f"Missing workflow widget: {item['type']}.{name}")
            result[name] = values[position]
            position += 1 + bool(options.get("control_after_generate"))
    if position != len(values):
        raise ValueError(f"Workflow/schema widget mismatch: {item['type']}")
    result.update(cache_mode="disabled", keep_model_loaded=False)
    return result


def prepare(case, workflow):
    ports = {name: case.get(name, "") for name in SUBJECT_INPUT_NAMES}
    settings = {stage: workflow_settings(workflow, cls) for stage, _, cls in NODE_STAGES}
    enhancer = {**settings["enhancer"], **ports, "scene_emd": case.get("scene_emd", ""),
                "user_request": case["user_request"], "seed": case["seed"]}
    value = DirectionEnhancerInput(**{name: enhancer[name] for name in (
        *SUBJECT_INPUT_NAMES, "scene_emd", "user_request", "style_profile",
        "motion_profile", "camera_profile", "retention_policy")})
    value.validate()
    template = parse_template_emd(case["template_emd"])
    if not value.merged_subjects.bindings:
        raise ValueError("A diagnostic case must provide at least one Subject")
    planner = {**settings["planner"], "concept_emd": value.merged_subjects.text,
               "scene_emd": case.get("scene_emd", ""), "template_emd": case["template_emd"],
               "save_debug_output": True, "seed": case["seed"]}
    # The merged Enhancer output is the Planner's only Subject source in this run.
    for name in SUBJECT_INPUT_NAMES[1:]:
        planner.pop(name, None)
    compiler = {**settings["compiler"], "translation_mode": "ja_to_en", "seed": case["seed"]}
    for stage, arguments in (("enhancer", enhancer), ("planner", planner), ("compiler", compiler)):
        method = getattr(dict((s, c) for s, _, c in NODE_STAGES)[stage],
                         {"enhancer": "enhance", "planner": "plan", "compiler": "compile_emd"}[stage])
        inspect.signature(method).bind_partial(None, **arguments)
    return {"enhancer": enhancer, "planner": planner, "compiler": compiler,
            "subject_map": [b.to_dict() for b in value.merged_subjects.bindings],
            "subject_count": len(value.merged_subjects.bindings),
            "scene_count": len(template.scenes),
            "enhancer_requires_inference": value.requires_inference}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def implementation_manifest():
    """Record source hashes, not a Git snapshot or user assets."""
    paths = [Path(__file__)]
    for directory in ("core", "nodes", "prompts", "profiles"):
        paths.extend(p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and p.suffix in {".py", ".txt", ".md"})
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))}


def inference(prepared, destination, models_dir):
    folder_paths = SimpleNamespace(models_dir=str(models_dir), folder_names_and_paths={})
    calls, results = [], {}
    def resolve(selection):
        return resolve_comfy_gguf_model(selection, folder_paths_module=folder_paths)
    def record(stage, operation):
        def wrapped(*args, **kwargs):
            entry = {"stage": stage, "task": kwargs.get("task", stage),
                     "payload": kwargs.get("payload"), "system_prompt": kwargs.get("system_prompt")}
            if stage == "compiler":
                entry["messages"] = args[0] if args else kwargs.get("messages")
            calls.append(entry)
            started = time.perf_counter()
            try:
                entry["response"] = operation(*args, **kwargs)
                return entry["response"]
            except BaseException as exc:
                entry["error"] = repr(exc)
                raise
            finally:
                entry["elapsed_s"] = time.perf_counter() - started
                save(destination / "calls.json", calls)
        return wrapped
    def debug(key, payload):
        path = destination / "planner-debug.json"
        save(path, {"cache_key": key, **payload})
        return str(path)
    instances = []
    try:
        with ExitStack() as stack:
            for _, module, cls in NODE_STAGES:
                stack.enter_context(patch.object(module, "resolve_comfy_gguf_model", resolve))
                stack.enter_context(patch.object(module, "_cache", return_value=None))
                instances.append(cls())
            stack.enter_context(patch.object(planner_module, "_debug_write", debug))
            enhancer, planner, compiler = instances
            enhancer._backend.complete_direction = record("enhancer", enhancer._backend.complete_direction)
            planner._backend.complete_planner = record("planner", planner._backend.complete_planner)
            compiler._lifecycle.complete_chat = record("compiler", compiler._lifecycle.complete_chat)
            logging.info("GPU inference starts: Enhancer; model=%s", prepared["enhancer"]["model_name"])
            started = time.perf_counter()
            direction, preview, status, merged = enhancer.enhance(**prepared["enhancer"])
            results["enhancer"] = {"status": status, "elapsed_s": time.perf_counter() - started}
            save(destination / "direction.json", direction.to_dict())
            (destination / "direction-preview.md").write_text(preview, encoding="utf-8")
            (destination / "subjects.md").write_text(merged, encoding="utf-8")
            if merged != prepared["planner"]["concept_emd"]:
                raise AssertionError("Enhancer changed the structurally merged Subject fragment")
            logging.info("GPU inference continues: Planner; subjects=%d", prepared["subject_count"])
            started = time.perf_counter()
            emd_text, _, status = planner.plan(**{**prepared["planner"], "concept_emd": merged,
                                                 "direction": direction})
            results["planner"] = {"status": status, "elapsed_s": time.perf_counter() - started}
            (destination / "planner-emd.md").write_text(emd_text, encoding="utf-8")
            save(destination / "results.json", results)
            if "complete=yes" not in status:
                raise RuntimeError("Planner output incomplete; Compiler was not run")
            document = parse_emd(emd_text)
            if len(document.subjects) != prepared["subject_count"]:
                raise AssertionError("Subject count changed in Planner")
            logging.info("GPU inference continues: Compiler")
            started = time.perf_counter()
            plan, references, status = compiler.compile_emd(
                **prepared["compiler"], emd_text=emd_text)
            results["compiler"] = {"status": status, "elapsed_s": time.perf_counter() - started,
                                   "required_references": references.to_dict()}
            (destination / "plan.json").write_text(plan, encoding="utf-8")
            results["h3_generated"] = False
            save(destination / "results.json", results)
            logging.info("Inference completed; H3 was not run")
    except BaseException as exc:
        save(destination / "failure.json", {"error": repr(exc), "completed_stages": results})
        raise
    finally:
        for instance in instances:
            instance._lifecycle.clear()
        logging.info("Owned models unloaded; GPU phase ended")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, default=ROOT / "workflows/01_plan_compiler_context_loop.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, default=Path("C:/Software/ComfyUI/models"))
    parser.add_argument("--infer", action="store_true", help="Requires prior user authorization for GPU use")
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT) or args.case.resolve().is_relative_to(ROOT):
        raise ValueError("Research inputs and evidence must stay outside the repository")
    if destination.exists():
        raise FileExistsError("Use a fresh evidence directory; existing evidence is never replaced")
    case_bytes, workflow_bytes = args.case.read_bytes(), args.workflow.read_bytes()
    prepared = prepare(json.loads(case_bytes), json.loads(workflow_bytes))
    destination.mkdir(parents=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(sys.stdout), logging.FileHandler(destination / "run.log", encoding="utf-8")])
    save(destination / "prepared.json", prepared)
    save(destination / "sources.json", {
        "case": str(args.case.resolve()), "case_sha256": hashlib.sha256(case_bytes).hexdigest(),
        "workflow": str(args.workflow.resolve()), "workflow_sha256": hashlib.sha256(workflow_bytes).hexdigest(),
        "mode": "real_inference" if args.infer else "cpu_preparation", "vision_run": False,
        "h3_run": False, "subject_fragments": "author-written diagnostic inputs, not Vision observations"})
    save(destination / "implementation-sha256.json", implementation_manifest())
    logging.info("Prepared case: subjects=%d; scenes=%d; inference=%s",
                 prepared["subject_count"], prepared["scene_count"], args.infer)
    if args.infer:
        inference(prepared, destination, args.models_dir)


if __name__ == "__main__":
    main()
