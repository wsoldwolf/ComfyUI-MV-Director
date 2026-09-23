"""Read-only prototype snapshot, current-runtime lyric-action comparison.

Loads selected source modules from a pinned local Git revision in memory.
Never changes the prototype checkout or production Planner. Saves raw outputs.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, replace
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig


class GitModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Only the probe namespace is served; package initializers are not run."""
    prefix = "_mvd_legacy_probe"
    packages = {"", "common", "common.gguf", "node_mv_prompt_planner", "node_japanese_to_json",
                "node_japanese_to_json.compiler"}

    def __init__(self, repo, revision):
        self.repo = repo
        self.revision = subprocess.check_output(
            ["git", "rev-parse", revision], cwd=repo, text=True).strip()
        self.sources = {}

    def read(self, path):
        raw = subprocess.check_output(
            ["git", "show", f"{self.revision}:{path}"], cwd=self.repo)
        self.sources[path] = hashlib.sha256(raw).hexdigest()
        return raw.decode("utf-8-sig")

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.prefix and not fullname.startswith(self.prefix + "."):
            return None
        relative = fullname[len(self.prefix):].lstrip(".")
        return importlib.util.spec_from_loader(
            fullname, self, is_package=relative in self.packages)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        relative = module.__name__[len(self.prefix):].lstrip(".")
        if relative in self.packages:
            return
        path = relative.replace(".", "/") + ".py"
        exec(compile(self.read(path), f"{self.revision}:{path}", "exec"), module.__dict__)

    def module(self, name):
        return importlib.import_module(self.prefix + "." + name)

    def builders(self):
        source = self.read("node_mv_prompt_planner/planning.py")
        wanted = {"_planning_brief_payload", "_lyric_lines", "_lyric_action_request_scene"}
        tree = ast.parse(source)
        tree.body = [n for n in tree.body if
                     isinstance(n, ast.ImportFrom) and n.module == "__future__" or
                     isinstance(n, ast.FunctionDef) and n.name in wanted]
        if sum(isinstance(n, ast.FunctionDef) for n in tree.body) != len(wanted):
            raise ValueError("Pinned prototype builders changed")
        namespace = {}
        exec(compile(tree, "prototype-builders", "exec"), namespace)
        return namespace


class TraceLifecycle(LlamaCppLifecycle):
    def _collect_chat_stream(self, stream, interrupt_callback):
        self.finish_reasons = []
        self.stream_chunks = 0

        def recorded():
            for chunk in stream:
                self.stream_chunks += 1
                for choice in chunk.get("choices", []):
                    if choice.get("finish_reason"):
                        self.finish_reasons.append(choice["finish_reason"])
                yield chunk
        return super()._collect_chat_stream(recorded(), interrupt_callback)


def framing(response, scene_id):
    """Syntax-only observation, NOT the prototype semantic validator."""
    rows = [line.split("\t") for line in response.strip().splitlines()]
    actions = [row for row in rows if row[0] == "ACTION"]
    return {
        "expected_open": bool(rows and rows[0] == ["LYRIC_SCENE", str(scene_id)]),
        "expected_end": bool(rows and rows[-1] == ["END_LYRIC_SCENE"]),
        "action_count": len(actions),
        "action_columns_valid": all(len(row) == 3 for row in actions),
        "action_indices": [row[1] for row in actions if len(row) >= 2],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, default=Path("E:/ComfyUI/projects/ComfyUI-cl-japanese2json"))
    parser.add_argument("--revision", default="992fa8b")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--legacy-emd", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--transport", choices=("current-chat", "current-soft", "legacy-prefill"),
                        default="legacy-prefill")
    parser.add_argument("--duration-cross", action="store_true",
                        help="Cross lyric grouping and duration using the same source pairs")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Evidence directory must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot = GitModules(args.prototype, args.revision)
    sys.meta_path.insert(0, snapshot)
    metadata = json.loads(subprocess.check_output([
        "C:/Software/ffmpeg/bin/ffprobe.exe", "-v", "error", "-show_entries",
        "format_tags=prompt", "-of", "json", str(args.video)]))
    graph = json.loads(metadata["format"]["tags"]["prompt"])
    planner = next(n for n in graph.values() if n.get("class_type") == "CLMVPromptPlannerGGUF")
    brief_id = planner["inputs"]["planning_markdown"][0]
    brief_text = graph[brief_id]["inputs"]["value"]
    brief = snapshot.module("node_mv_prompt_planner.brief_parser").parse_planning_brief(brief_text)
    structures = snapshot.module("node_mv_prompt_planner.structures")
    protector_type = snapshot.module("node_mv_prompt_planner.placeholders").ReferenceProtector
    timeline = snapshot.module("node_mv_prompt_planner.timeline_parser").parse_prompt_timeline(
        args.legacy_emd.read_text(encoding="utf-8-sig"))
    classify = snapshot.module("common.suno").classify_suno_section
    helpers = snapshot.builders()
    system = snapshot.read("node_mv_prompt_planner/prompts/core/lyric_action_system_prompt.txt")
    reference_evidence = {}
    for path, names in (
        ("node_mv_prompt_planner/validation.py",
         {"_motion_phase_additions", "repair_lyric_action_motion", "repair_subject_motion"}),
        ("node_mv_prompt_planner/planning.py", {"_apply_lyric_action_blueprint"}),
    ):
        source = snapshot.read(path)
        reference_evidence[path] = {
            node.name: {"line": node.lineno, "source": ast.get_source_segment(source, node)}
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name in names}
    profile_source = snapshot.read(
        "node_mv_prompt_planner/prompts/profiles/lyric_visuals_light_8b/profile.json")
    cases = []
    for current, old_id in ((5, 6), (9, 9)):
        old_scene = next(s for s in timeline.scenes if s.scene_id == old_id)
        saved = json.loads((ROOT / f"docs/assets/research/scene-author-2026-09-23/scene{current}-v5/summary.json").read_text(encoding="utf-8"))
        payload = json.loads(next(r["payload"] for r in saved["trace"] if r["task"] == "scene-author-performance"))
        labels = {"VERSE": "[Verse]", "PRE-CHORUS": "[Pre-Chorus]", "CHORUS": "[Chorus]"}
        lyrics = tuple(structures.TimelineLyric(
            text=line["text"], section_label=labels[line["section"]],
            section_kind=classify(labels[line["section"]]))
            for shot in payload["original_lyrics"] for line in shot["lyrics"])
        # Keep scene ID equal within each pair; duration/lyrics are the variable.
        local = replace(old_scene, lyrics=lyrics,
                        duration_seconds=(9.208 if current == 5 else 9.916))
        pair = (("legacy", old_scene), ("fragment", local))
        if args.duration_cross:
            pair = (("legacy-short", replace(old_scene, duration_seconds=local.duration_seconds)),
                    ("fragment-long", replace(local, duration_seconds=old_scene.duration_seconds)))
        for label, scene in pair:
            protector = protector_type()
            planning = helpers["_planning_brief_payload"](brief, protector)
            scene_request = helpers["_lyric_action_request_scene"](scene, protector)
            request = {
                "protocol": "clmv-lyric-action-line-v1",
                "planning_constraints": {k: planning[k] for k in ("subject_identity", "retention_constraints")},
                "reference_legend": protector.legend(),
                "requested_scene_ids": [scene.scene_id],
                "requested_scene_count": 1,
                "scenes": [scene_request],
            }
            cases.append({"case": f"scene{current}-{label}", "payload": request})
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=512, temperature=0.1, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=256,
        keep_model_loaded=False, seed=1)
    manifest = {
        "revision": snapshot.revision, "source_hashes": snapshot.sources,
        "video": str(args.video), "legacy_emd": str(args.legacy_emd),
        "legacy_emd_sha256": hashlib.sha256(args.legacy_emd.read_bytes()).hexdigest(),
        "model": str(args.model), "model_bytes": args.model.stat().st_size,
        "historical_planner_inputs": planner["inputs"], "config": asdict(config),
        "system_prompt": system, "brief_source": brief_text, "cases": cases,
        "reference_evidence": reference_evidence,
        "historical_profile": json.loads(profile_source),
        "limitations": [
            "Historical prompt; restored prototype EMD timeline is not proven to be original video input.",
            "Current llama.cpp runtime/template, explicit seeds; not historical runtime or per-call seed replay.",
            "Legacy-vs-fragment changes lyric grouping AND duration; not single-variable causality.",
            "One unconstrained call per case/seed; no audit, retry, H3, or natural-language repair.",
            "Prompt token count is raw system+JSON, excludes chat-template overhead.",
        ],
        "transport": args.transport, "duration_cross": args.duration_cross, "results": [],
    }
    lifecycle = TraceLifecycle()
    try:
        if not args.prepare_only:
            lifecycle.ensure_loaded(args.model, config)
            legacy_backend = None
            if args.transport == "legacy-prefill":
                legacy_backend = snapshot.module("common.gguf.runtime").LlamaBackend()
                legacy_backend.llm = lifecycle._model
                legacy_backend.current_model_path = args.model
            for seed in args.seeds:
                for case in cases:
                    effective = replace(config, seed=seed)
                    user = json.dumps(case["payload"], ensure_ascii=False, separators=(",", ":"))
                    if args.transport == "current-soft":
                        user = "/no_think\n" + user
                    count = lifecycle.count_serialized_prompt(system + "\n" + user)
                    started = time.perf_counter()
                    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
                    usage = None
                    if legacy_backend is None:
                        response = lifecycle.complete_chat(messages, effective)
                    else:
                        raw = legacy_backend.complete_chat(
                            messages=messages, max_tokens=effective.max_tokens,
                            temperature=effective.temperature, top_p=effective.top_p,
                            repeat_penalty=effective.repetition_penalty, seed=seed,
                            progress_callback=lambda count: None)
                        response = raw["choices"][0]["message"]["content"]
                        lifecycle.finish_reasons = [raw["choices"][0]["finish_reason"]]
                        lifecycle.stream_chunks = None
                        usage = raw.get("usage")
                    result = {**case, "seed": seed, "effective_config": asdict(effective),
                              "transport": args.transport, "usage": usage,
                              "response": response, "finish_reasons": lifecycle.finish_reasons,
                              "stream_chunks": lifecycle.stream_chunks,
                              "raw_prompt_tokens": count.count, "tokens_estimated": count.estimated,
                              "elapsed_seconds": time.perf_counter() - started,
                              "framing": framing(response, case["payload"]["requested_scene_ids"][0])}
                    name = f"{case['case']}-seed{seed}.json"
                    (args.output / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    manifest["results"].append({k: result[k] for k in ("case", "seed", "elapsed_seconds", "framing", "finish_reasons")})
                    print(f"{name}: {result['elapsed_seconds']:.2f}s {result['finish_reasons']}", flush=True)
    finally:
        lifecycle.clear()
        sys.meta_path.remove(snapshot)
        (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
