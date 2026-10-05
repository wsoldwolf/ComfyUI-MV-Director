"""Research: optional instrumental candidate through normal Camera Planner/Compiler.

Only Scene 11/12 Cameras are reopened. Body/Event and singing return stay fixed.
The production renderer appends generated Cameras after the fixed body; retain
and explicitly validate this order change rather than patching compiled prose.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.debug_momentum_pipeline import production_inputs, infer
from tools.debug_instrumental_chain import connected_plan
from tools.debug_instrumental_middle import finalize_middle
from tools.debug_shot_duration import verify_pcm
from tools.prepare_beat_motion_h3 import read, save
from tools.prepare_instrumental_h3 import render
from nodes.node_timeline_planner.node import _system_prompts

RUN_NAME = "instrumental-camera-candidate-b26-momiji2-s11-13-20261004"
USER_REQUEST = """# 演出候補
* 長い伴奏区間では、人物の身体演技に合わせてCameraが早い段階から回り込み、人物が姿勢を保つ間も移動を続ける。継続Sceneでは旋回方向を引き継ぎ、背景の視差を見せる。歌唱復帰へ向かう終盤では上半身へ接近し、表情と歌唱口が読める構図につなぐ。
"""


def verify_candidate_plan(baseline, candidate, old_cameras, bodies, new_cameras):
    if len(baseline["shots"]) != 3 or any(len(rows) != 2 for rows in (old_cameras, bodies, new_cameras)):
        raise ValueError("Require two Cameras and three connected Scenes")
    expected = deepcopy(baseline)
    for index, (old, body, new) in enumerate(zip(old_cameras, bodies, new_cameras)):
        if not all(value.strip() for value in (old, body, new)):
            raise ValueError("Empty Camera or protected body")
        before, after = old + " " + body, body + " " + new
        lines = expected["shots"][index]["prompt"]
        if sum(line.count(before) for line in lines) != 1:
            raise ValueError("Require unique baseline Camera/Performance order")
        expected["shots"][index]["prompt"] = [line.replace(before, after, 1) for line in lines]
    if candidate != expected:
        raise ValueError("Plan changed beyond target Cameras and recorded renderer order")


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty research destination")
    if (Path(r"C:\Software\ComfyUI\output\h3_chains") / RUN_NAME).exists():
        raise ValueError("Do not reuse an existing run")
    media, manifest = read(source / "media-checks.json"), read(source / "h3-manifest.json")
    if not Path(media["videos"]["dance"]["path"]).is_file():
        raise ValueError("Completed baseline video missing")
    reference = read(source / "reference-contract.json")
    if hashlib.sha256(Path(reference["input_snapshot"]).read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("Reference snapshot changed")
    verify_pcm(manifest, manifest["audio"])
    text = (source / "dance.md").read_text(encoding="utf-8")
    template, direction, _, _ = production_inputs(text, USER_REQUEST, target_scenes=(11, 12),
                                               preserve_continuation=True, target_kind="カメラ")
    output.mkdir(parents=True)
    for before, after in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                          ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json"),
                          ("reference-contract.json", "reference-contract.json")):
        shutil.copy2(source / before, output / after)
    (output / "input-emd.md").write_text(text, encoding="utf-8")
    (output / "user-request.md").write_text(USER_REQUEST, encoding="utf-8")
    prompts, conditions = _system_prompts(), read(source / "conditions.json")
    save(output / "system-prompts.json", prompts)
    save(output / "conditions.json", {**conditions, "source": str(source),
        "translation_cache": str(source / "translation.json"), "target_scenes": [11, 12],
        "generated_slots": [[11, 1], [12, 1]], "target_kind": "カメラ", "generated_kind": "cameras",
        "preserve_continuation": True, "defer_delivery": True, "staging_candidate_policy": "optional",
        "planned_new_fields": ["scene.10.shot.0.body.2", "scene.11.shot.0.body.2"],
        "system_prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()},
        "planner_rerun": True})
    save(output / "input-contract.json", {"user_request": USER_REQUEST, "direction": direction.to_dict(),
        "target_scenes": [11, 12], "normal_parser": "split_staging_directives",
        "normal_planner": "generate_planner_content", "normal_compiler": "compile_ref2va",
        "audio_activity_present": template.audio_activity is not None,
        "candidate_policy": "optional", "no_forced_candidate_selection": True,
        "fixed": ["Performance", "Event", "Subject", "Scene 13 Camera", "PCM", "seed", "timing", "H3 settings", "reference"],
        "production_renderer_order_before": ["Event", "Camera", "Performance"],
        "production_renderer_order_after": ["Event", "Performance", "Camera"],
        "authored_camera_output_insertion": False, "semantic_prose_repair": False})
    save(output / "h3-manifest.json", {**manifest, "source": str(source),
        "run_names": {"baseline": manifest["run_names"]["dance"], "dance": RUN_NAME},
        "comparison_titles": ["Accepted Authored Camera", "Planner Camera Candidate"],
        "comparison_labels": ["baseline", "dance"], "baseline_render_reused": True, "new_render_count": 1,
        "comparison": "optional candidate through normal Camera Planner; renderer field order also changes",
        "planner_rerun": True, "camera_only_plan_verified": False, "compiler_used": True})
    print("Prepared optional candidate; only Scene 11/12 Cameras reopened", flush=True)


def deliver(args):
    output = args.output.resolve(strict=True)
    if (output / "submission-dance.json").exists():
        raise ValueError("Do not replace a submitted comparison")
    source = Path(read(output / "conditions.json")["source"])
    old_rows, rows = read(source / "translation.json"), read(output / "translation.json")
    generated = read(output / "inference.json")["content"]["cameras"]
    old_cameras, bodies, new_cameras = [], [], []
    excerpts = ["# 伴奏用演出候補からのCamera生成", "", USER_REQUEST]
    for number in (11, 12):
        old_camera = next(r for r in old_rows if r["field_id"] == f"scene.{number-1}.shot.0.body.1")
        body = next(r for r in old_rows if r["field_id"] == f"scene.{number-1}.shot.0.body.2")
        japanese = next(r[2] for r in generated if r[:2] == [number, 1])
        translated = [r for r in rows if r["source"] == japanese]
        if len(translated) != 1:
            raise ValueError("Generated Camera translation is not unique")
        old_cameras.append(old_camera["restored"])
        bodies.append(body["restored"])
        new_cameras.append(translated[0]["restored"])
        excerpts.extend((f"## Scene {number}", "", "### Plannerの日本語", "", japanese,
                         "", "### Compilerの英訳", "", translated[0]["restored"], ""))
    uncached = read(output / "compiler-inference.json")["uncached_fields"]
    allowed = {"scene.10.shot.0.body.2", "scene.11.shot.0.body.2"}
    if len(set(uncached)) != len(uncached) or not set(uncached).issubset(allowed):
        raise ValueError("Unexpected newly translated fields")
    candidate = connected_plan(read(output / "compiled-full-plan.json"))
    verify_candidate_plan(read(output / "baseline-plan.json"), candidate, old_cameras, bodies, new_cameras)
    save(output / "dance-plan.json", candidate)
    graph = read(output / "h3-baseline.json")
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(candidate, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = graph["21"]["inputs"]["filename"] = RUN_NAME
    save(output / "h3-dance.json", graph)
    save(output / "output-contract.json", {**read(output / "input-contract.json"),
        "plan_camera_and_order_only_verified": True, "performance_japanese_and_english_unchanged": True,
        "camera_japanese": [r[2] for r in generated], "camera_english": new_cameras,
        "candidate_adoption_verdict": "requires semantic review; normal protocol does not report candidate ID"})
    (output / "dance-excerpt.md").write_text("\n".join(excerpts), encoding="utf-8")
    print("Verified Camera changes and normal renderer order; inspect output before H3", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "infer", "deliver", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--url", default="http://127.0.0.1:8188")
    args = p.parse_args()
    if args.task == "prepare":
        if not args.source:
            p.error("prepare requires --source")
        prepare(args)
    elif args.task == "infer":
        infer(args)
        deliver(args)
    elif args.task == "deliver":
        deliver(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize_middle(args)
