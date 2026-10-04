"""Research: user staging candidate through production Planner and Compiler.

Fixed Event/Camera and saved unrelated translations isolate Performance.
No authored English body is inserted and no semantic prose repair is used.
"""
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

from core.artifacts import DirectionArtifact
from core.direction.enhancer import split_staging_directives
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.planner.api import generate_planner_content, render_planner_content
from core.planner.template import PlannerTemplate
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy
from nodes.node_emd_compiler.node import _system_prompt
from tools.debug_simple_dance import MOMENTUM_JAPANESE, MOMENTUM_ENGLISH, replace_body
from tools.prepare_beat_motion_h3 import read, save, fresh_plan, finalize
from tools.prepare_instrumental_h3 import render

USER_REQUEST = "# 演出候補\n* 歌詞のない伴奏が続くSceneで、" + MOMENTUM_JAPANESE + "\n"
RUN_NAME = "momentum-pipeline-b13-momiji2-s11-20261004"
SPEED_REQUEST = USER_REQUEST.rstrip("\n") + "半回転は通常速度の短い一連の踏み替えで進め、その勢いを次の足運びと腕の弧へつなぐ。\n"
SPEED_RUN_NAME = "momentum-speed-b14-momiji2-s11-20261004"


def production_inputs(text, user_request, target_scene=11, *, target_scenes=None, preserve_continuation=False,
                      target_kind="演技"):
    if target_kind not in {"演技", "カメラ"}:
        raise ValueError("Unsupported research target kind")
    common_request, candidates = split_staging_directives(user_request)
    if common_request or len(candidates) != 1:
        raise ValueError("Probe requires one staging candidate and no new common conditions")
    document = parse_emd(text)
    targets = frozenset(target_scenes) if target_scenes is not None else frozenset((target_scene,))
    if not targets:
        raise ValueError("At least one target Scene is required")
    scenes = []
    found = 0
    for scene in document.scenes:
        if scene.scene_number in targets:
            if target_scenes is None and len(scene.shots) != 1:
                raise ValueError(f"Requires single-Shot Scene {target_scene}")
            shots = []
            for shot in scene.shots:
                if {d.kind for d in shot.directives} != {"演出", "演技", "カメラ"}:
                    raise ValueError("Expected three authored target fields")
                shots.append(replace(shot,
                    body=tuple(line for line in shot.body if not line.startswith(f"`{target_kind}` ")),
                    directives=tuple(d for d in shot.directives if d.kind != target_kind)))
            # Match the successful isolated H3 baseline, not the source song's
            # predecessor state. This is an explicit experiment boundary.
            scene = replace(scene, shots=tuple(shots),
                            continuation=scene.continuation if preserve_continuation else False)
            found += 1
        elif any(not {"演技", "カメラ"}.issubset({d.kind for d in q.directives}) for q in scene.shots):
            raise ValueError("Non-target Shots must already have fixed Performance and Camera")
        scenes.append(replace(scene, audio_directives=()))
    if found != len(targets):
        raise ValueError("Requested target Scenes are missing or not unique")
    common = document.common_prompt_dict()
    direction = DirectionArtifact(
        style_direction=common.get("スタイル", ()),
        environment_direction=common.get("環境", ()),
        time_lighting_direction=common.get("時間・照明", ()),
        motion_direction=common.get("モーション", ()),
        camera_direction=common.get("カメラ", ()),
        other_direction=common.get("その他", ()),
        motion_profile_id="anime_scene_author_mv", motion_templates=(),
        staging_candidates=candidates)
    concept = text.split("\n# シーン設定", 1)[0].strip() + "\n"
    scene_emd = "# シーン設定" + text.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
    return PlannerTemplate(tuple(scenes), document.audio_activity), direction, concept, scene_emd


def verify_single_body_plan(baseline, candidate, english, camera="", *, baseline_english=None):
    if not english.strip():
        raise ValueError("Compiler produced empty Performance")
    if baseline_english is not None:
        if not baseline_english.strip():
            raise ValueError("Baseline Performance must not be empty")
        expected = deepcopy(baseline)
        lines = expected["shots"][0]["prompt"]
        if sum(line.count(baseline_english) for line in lines) != 1:
            raise ValueError("Baseline Performance is not unique")
        expected["shots"][0]["prompt"] = [line.replace(baseline_english, english) for line in lines]
    elif camera:
        expected = deepcopy(baseline)
        old = MOMENTUM_ENGLISH + " " + camera
        new = camera + " " + english
        lines = expected["shots"][0]["prompt"]
        if sum(line.count(old) for line in lines) != 1:
            raise ValueError("Baseline Performance-Camera order is not unique")
        expected["shots"][0]["prompt"] = [line.replace(old, new) for line in lines]
    else:
        expected = baseline if english == MOMENTUM_ENGLISH else replace_body(baseline, MOMENTUM_ENGLISH, english)
    if candidate != expected:
        raise ValueError("Compiled Plan changed outside Performance and recorded field order; do not render")


def deliver(output):
    """Validate saved Compiler output; never rewrite its natural language."""
    if (output / "submission-dance.json").exists():
        raise ValueError("Do not replace evidence for a submitted render")
    content = read(output / "inference.json")["content"]
    japanese = content["actions"][0][2]
    translations = read(output / "translation.json")
    rows = [row for row in translations if row["source"] == japanese]
    if len(rows) != 1 or rows[0]["reused_saved_translation"]:
        raise ValueError("Expected a unique freshly translated Planner Performance")
    english = rows[0]["restored"]
    manifest = read(output / "h3-manifest.json")
    conditions = read(output / "conditions.json")
    target_scene = conditions.get("scene", 11)
    camera = next(row["restored"] for row in translations
                  if row["field_id"] == f"scene.{target_scene - 1}.shot.0.body.1")
    baseline_english = conditions.get("baseline_performance_english")
    order_changed = baseline_english is None
    candidate = fresh_plan(read(output / "compiled-full-plan.json"), manifest["render_frames"], scene=target_scene)
    baseline = read(output / "baseline-plan.json")
    # Match the existing isolated render boundary. Compiler output remains
    # saved unchanged in compiled-full-plan.json for provenance.
    candidate["shots"][0]["continuation_mode"] = baseline["shots"][0]["continuation_mode"]
    verify_single_body_plan(baseline, candidate, english, camera, baseline_english=baseline_english)
    save(output / "dance-plan.json", candidate)
    (output / "dance-excerpt.md").write_text(
        f"# Scene {target_scene}の通常パイプライン出力\n\n## ユーザー候補\n\n{(output / 'user-request.md').read_text(encoding='utf-8')}\n"
        f"## Plannerの実出力\n\n{japanese}\n\n## Compilerの実英訳\n\n{english}\n", encoding="utf-8")
    save(output / "output-contract.json", {
        "plan_performance_and_order_only_verified": True,
        "performance_japanese": japanese, "performance_english": english,
        "camera_text_unchanged": True,
        "baseline_order": ["Event", "Performance", "Camera"] if order_changed else ["Event", "Camera", "Performance"],
        "production_order": ["Event", "Camera", "Performance"],
        "order_cause": "renderer keeps fixed author body before generated Performance" if order_changed else "same production field order as baseline",
        "plan_performance_only_verified": not order_changed,
        "isolated_render_adapter": {
            "length": manifest["render_frames"], "context_length": 0,
            "audio_context_length": 0,
            "continuation_mode": baseline["shots"][0]["continuation_mode"],
            "reason": "same isolated boundary as baseline; unchanged Compiler output saved separately"},
        "no_semantic_prose_repair": True, "no_authored_english_insertion": True})
    save(output / "h3-manifest.json", {**manifest,
        "body_only_plan_verified": not order_changed,
        "performance_and_order_only_verified": True,
        "production_field_order_changed": order_changed})
    graph = read(output / "h3-baseline.json")
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(candidate, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = manifest["run_names"]["dance"]
    graph["21"]["inputs"]["filename"] = manifest["run_names"]["dance"]
    save(output / "h3-dance.json", graph)
    scope = "Performance and normal renderer order" if order_changed else "Performance only; field order unchanged"
    print(f"Production output verified; {scope}; inspect before rendering", flush=True)


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty destination")
    manifest = read(source / "h3-manifest.json")
    if not Path(read(source / "media-checks.json")["videos"]["dance"]["path"]).is_file():
        raise ValueError("Successful baseline video is missing")
    text = (source / "dance.md").read_text(encoding="utf-8")
    speed = getattr(args, "speed", False)
    user_request = SPEED_REQUEST if speed else USER_REQUEST
    run_name = SPEED_RUN_NAME if speed else RUN_NAME
    baseline_performance = None
    if speed:
        contract = read(source / "output-contract.json")
        if contract["production_order"] != ["Event", "Camera", "Performance"]:
            raise ValueError("Speed comparison requires a production-order baseline")
        baseline_performance = contract["performance_english"]
    template, direction, _, _ = production_inputs(text, user_request)
    conditions = read(Path(manifest["source_b1"]) / "conditions.json")
    translations = Path(manifest["source_b3_baseline"]).parent / "beat-driven-p2-momiji2-costume-a2-2026-10-03" / "baseline-translation.json"
    if not translations.is_file():
        raise ValueError("Clothing-corrected translation evidence missing")
    prompts = _system_prompts()
    output.mkdir(parents=True)
    (output / "user-request.md").write_text(user_request, encoding="utf-8")
    (output / "input-emd.md").write_text(text, encoding="utf-8")
    save(output / "system-prompts.json", prompts)
    save(output / "conditions.json", {**conditions,
        "source": str(source), "translation_cache": str(translations),
        "staging_candidate_policy": "optional", "compiler_max_tokens": 4096,
        "baseline_performance_english": baseline_performance,
        "candidate_speed_sentence_added": speed,
        "scope": "Scene 11 Performance through production API; fixed Event/Camera; all other Shots already authored",
        "system_prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()}})
    save(output / "input-contract.json", {
        "user_request": user_request, "direction": direction.to_dict(),
        "target_scene": 11, "target_shots": 1,
        "full_template_scene_count": len(template.scenes),
        "parser": "split_staging_directives", "planner": "generate_planner_content",
        "compiler": "compile_ref2va", "semantic_prose_repair": False,
        "authored_english_insertion": False, "motion_composition_disabled": True,
        "target_continuation": False, "source_predecessor_reused": False,
        "fixed_fields": ["Subject", "Scene environment", "Event", "Camera", "all other Shots", "seed", "PCM", "H3 settings"]})
    for old, new in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                     ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json")):
        shutil.copy2(source / old, output / new)
    save(output / "h3-manifest.json", {**manifest,
        "source_pipeline_baseline": str(source),
        "run_names": {"baseline": manifest["run_names"]["dance"], "dance": run_name},
        "comparison_labels": ["baseline", "dance"],
        "comparison_titles": ["Pipeline Baseline", "Pipeline Normal Speed"] if speed else ["Authored Momentum", "Planner Compiler"],
        "comparison": "one normal-speed sentence added to staging candidate; same production field order" if speed else "same movement supplied as Japanese staging candidate; production Performance and Compiler",
        "research_authored_prose": False, "research_authored_candidate": True,
        "planner_rerun": True, "compiler_used": True,
        "new_render_count": 1, "baseline_render_reused": True})
    print("Production inputs prepared on CPU; no inference or rendering yet", flush=True)


def infer(args, *, backend_factory=None):
    output = args.output.resolve(strict=True)
    if (output / "inference.json").exists():
        raise ValueError("Inference already attempted; do not silently overwrite")
    with urlopen(args.url + "/queue", timeout=30) as response:
        queue = json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; existing jobs unchanged")
    conditions = read(output / "conditions.json")
    target_scene = conditions.get("scene", 11)
    template, direction, concept, scene_emd = production_inputs(
        (output / "input-emd.md").read_text(encoding="utf-8"),
        (output / "user-request.md").read_text(encoding="utf-8"), target_scene=target_scene,
        target_scenes=conditions.get("target_scenes"),
        preserve_continuation=conditions.get("preserve_continuation", False),
        target_kind=conditions.get("target_kind", "演技"))
    prompts = read(output / "system-prompts.json")
    if {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()} != conditions["system_prompt_sha256"]:
        raise ValueError("Prepared prompts changed")
    config = LlamaRuntimeConfig(**conditions["runtime"])
    lifecycle = LlamaCppLifecycle()
    try:
        started = time.perf_counter()
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        print(f"Model loaded in {time.perf_counter()-started:.1f}s", flush=True)
        backend = (backend_factory or _LlamaPlannerBackend)(lifecycle)
        backend.transport_policy = _planner_transport_policy(conditions["model"])
        started = time.perf_counter()
        content, missing = generate_planner_content(backend, template=template,
            concept_emd=concept, scene_emd=scene_emd, direction=direction,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            system_prompts=prompts, runtime_config=config,
            staging_candidate_policy=conditions["staging_candidate_policy"])
        save(output / "inference.json", {"content": content.to_dict() if content else None,
            "missing": missing, "trace": backend.trace, "elapsed_s": time.perf_counter()-started})
        if content is None or missing:
            raise RuntimeError(f"Incomplete production Planner: {missing}")
        expected = {tuple(slot) for slot in conditions.get("generated_slots", [(target_scene, 1)])}
        generated_kind = conditions.get("generated_kind", "actions")
        if generated_kind not in {"actions", "cameras"}:
            raise ValueError("Unsupported generated research kind")
        rows = getattr(content, generated_kind)
        unexpected = any(getattr(content, kind) for kind in ("actions", "events", "cameras") if kind != generated_kind)
        if len(rows) != len(expected) or {row[:2] for row in rows} != expected or unexpected or content.motion_compositions:
            raise ValueError("Unexpected generated fields; do not render")
        emd = render_planner_content(content=content, concept_emd=concept,
            scene_emd=scene_emd, template=template, direction=direction,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1)
        (output / "dance.md").write_text(emd.text, encoding="utf-8")
        cache = {}
        for row in read(Path(conditions["translation_cache"])):
            key, value = tuple(row["fragments"]), tuple(row["translated"])
            if key in cache and cache[key] != value:
                raise ValueError("Conflicting saved translation evidence")
            cache[key] = value
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
            runtime_config=replace(config, temperature=0.0, max_tokens=conditions["compiler_max_tokens"]))

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
        compiled = compile_ref2va(emd.text, cached)
        save(output / "translation.json", cached.translation_trace)
        save(output / "compiler-inference.json", {"trace": translator.translation_trace,
            "elapsed_s": time.perf_counter()-started,
            "uncached_fields": [r["field_id"] for r in cached.translation_trace if not r["reused_saved_translation"]]})
        for index, shot in enumerate(compiled.plan["shots"], 1):
            shot["seed"] = 20261003 + index
        save(output / "compiled-full-plan.json", compiled.plan)
        if not conditions.get("defer_delivery", False):
            deliver(output)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "infer", "deliver", "render", "finalize"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    parser.add_argument("--speed", action="store_true", help="prepare a candidate-only speed comparison against production output")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "prepare":
        if not args.source:
            parser.error("prepare requires --source")
        prepare(args)
    elif args.task == "infer":
        infer(args)
    elif args.task == "deliver":
        deliver(args.output.resolve(strict=True))
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
