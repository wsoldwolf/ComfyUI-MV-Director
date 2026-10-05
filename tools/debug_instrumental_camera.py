"""Research: Camera-only Arc in continuing Scene 12; saved body prose stays fixed."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.emd import parse_emd
from nodes.node_emd_compiler.node import _system_prompt
from tools.debug_camera_speed import compile_camera
from tools.debug_instrumental_chain import connected_plan
from tools.debug_instrumental_middle import finalize_middle
from tools.debug_shot_duration import verify_pcm
from tools.prepare_beat_motion_h3 import read, save
from tools.prepare_instrumental_h3 import render

RUN_NAME = "instrumental-camera-b21-momiji2-s11-13-20261004"
CAMERA_FIELD = "scene.11.shot.0.body.1"
CAMERA = ("前Shotの高さと距離から、人物の頭から足までを画面に収めたまま、"
          "正面から人物の右斜め前へ一方向のArcで回り込む。体幹と左腕の動き、"
          "袖と滝の水しぶきを角度の変化とともに捉え、Shotの終わりまで滑らかに進む。")


def replace_middle_camera(text, expected_old, new_camera=CAMERA, *, scene_number=12):
    if not new_camera.strip() or "\n" in new_camera or "\r" in new_camera or new_camera == expected_old:
        raise ValueError("Requires one new nonempty Camera line")
    document = parse_emd(text)
    scenes = [s for s in document.scenes if s.scene_number == scene_number]
    if len(scenes) != 1 or len(scenes[0].shots) != 1:
        raise ValueError(f"Requires unique single-Shot Scene {scene_number}")
    shot = scenes[0].shots[0]
    cameras = [d for d in shot.directives if d.kind == "カメラ"]
    if len(cameras) != 1 or cameras[0].text != expected_old:
        raise ValueError("Baseline Camera evidence mismatch")
    camera = cameras[0]
    lines = text.splitlines(keepends=True)
    index = camera.line_number - 1
    if lines[index].count(expected_old) != 1:
        raise ValueError("Camera source line mismatch")
    lines[index] = lines[index].replace(expected_old, new_camera, 1)
    updated = "".join(lines)
    expected_shot = replace(shot,
        body=tuple(line.replace(expected_old, new_camera) if line == "`カメラ` " + expected_old
                   else line for line in shot.body),
        directives=tuple(replace(d, text=new_camera) if d == camera else d for d in shot.directives))
    expected = replace(document, scenes=tuple(
        replace(s, shots=(expected_shot,)) if s.scene_number == scene_number else s for s in document.scenes))
    if parse_emd(updated) != expected:
        raise ValueError(f"EMD changed outside Scene {scene_number} Camera")
    return updated


def verify_middle_camera(baseline, candidate, old, new):
    if not old.strip() or not new.strip() or old == new or len(baseline["shots"]) != 3:
        raise ValueError("Requires one changed Camera in a three-Scene Plan")
    expected = deepcopy(baseline)
    lines = expected["shots"][1]["prompt"]
    if sum(line.count(old) for line in lines) != 1:
        raise ValueError("Target Camera must be unique")
    expected["shots"][1]["prompt"] = [line.replace(old, new, 1) for line in lines]
    if candidate != expected:
        raise ValueError("Plan changed outside Scene 12 Camera")


def verify_opening_and_middle_cameras(baseline, candidate, old, new):
    if len(baseline["shots"]) != 3 or len(old) != 2 or len(new) != 2:
        raise ValueError("Require two changed Cameras in a three-Scene Plan")
    expected = deepcopy(baseline)
    for index, (before, after) in enumerate(zip(old, new)):
        if not before.strip() or not after.strip() or before == after:
            raise ValueError("Require a nonempty changed Camera")
        lines = expected["shots"][index]["prompt"]
        if sum(line.count(before) for line in lines) != 1:
            raise ValueError("Target Camera must be unique in its Scene")
        expected["shots"][index]["prompt"] = [line.replace(before, after, 1) for line in lines]
    if candidate != expected:
        raise ValueError("Plan changed outside Scene 11 and 12 Cameras")


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty research destination")
    run_name = getattr(args, "run_name", RUN_NAME)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", run_name):
        raise ValueError("Unsafe run name")
    if (Path(r"C:\Software\ComfyUI\output\h3_chains") / run_name).exists():
        raise ValueError("Do not reuse an existing run")
    camera_file = getattr(args, "camera_file", None)
    camera_text = camera_file.read_text(encoding="utf-8").strip() if camera_file else CAMERA
    media, manifest = read(source / "media-checks.json"), read(source / "h3-manifest.json")
    if not Path(media["videos"]["dance"]["path"]).is_file():
        raise ValueError("Completed reference baseline missing")
    reference = read(source / "reference-contract.json")
    if hashlib.sha256(Path(reference["input_snapshot"]).read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("Reference snapshot changed")
    verify_pcm(manifest, manifest["audio"])
    opening_file = getattr(args, "opening_camera_file", None)
    targets = [(12, CAMERA_FIELD, camera_text)]
    if opening_file:
        targets.insert(0, (11, "scene.10.shot.0.body.1", opening_file.read_text(encoding="utf-8").strip()))
    rows = read(source / "translation.json")
    updated = (source / "dance.md").read_text(encoding="utf-8")
    cameras = []
    for number, field, text in targets:
        matches = [r for r in rows if r["field_id"] == field]
        if len(matches) != 1:
            raise ValueError("Unique Camera translation required")
        cameras.append(matches[0])
        updated = replace_middle_camera(updated, matches[0]["source"], text, scene_number=number)
    output.mkdir(parents=True)
    for before, after in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                          ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json"),
                          ("reference-contract.json", "reference-contract.json")):
        shutil.copy2(source / before, output / after)
    # Generated research evidence, not manual editing of the saved baseline.
    (output / "dance.md").write_text(updated, encoding="utf-8")
    prompt = _system_prompt()
    (output / "compiler-system-prompt.txt").write_text(prompt, encoding="utf-8")
    conditions = read(source / "conditions.json")
    save(output / "conditions.json", {
        "source": str(source), "model": conditions["model"], "runtime": conditions["runtime"],
        "compiler_max_tokens": 4096, "translation_cache": str(source / "translation.json"),
        "compiler_system_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "planned_new_fields": [field for _, field, _ in targets], "planner_rerun": False})
    multiple = len(targets) > 1
    save(output / "input-contract.json", {
        "camera_japanese_before": [r["source"] for r in cameras] if multiple else cameras[0]["source"],
        "camera_japanese_after": [text for _, _, text in targets] if multiple else camera_text,
        "camera_english_before": [r["restored"] for r in cameras] if multiple else cameras[0]["restored"],
        "target_scenes": [number for number, _, _ in targets], "emd_camera_only_verified": True,
        "fixed": ["Performance", "Event", "Subject", "reference", "PCM", "seed", "timing", "H3 settings"],
        "authored_camera_change": True, "authored_english_insertion": False,
        "fresh_render": True, "old_checkpoint_reused": False})
    save(output / "h3-manifest.json", {**manifest,
        "run_names": {"baseline": manifest["run_names"]["dance"], "dance": run_name},
        "comparison_labels": ["baseline", "dance"],
        "comparison_titles": [getattr(args, "baseline_title", "Fixed Camera"),
                              getattr(args, "candidate_title", "One-direction Arc")],
        "baseline_render_reused": True, "new_render_count": 1,
        "source": str(source), "comparison": f"Scenes {[number for number, _, _ in targets]} Camera only; same reference and body prose"})
    print(f"CPU preparation verified: only Scenes {[number for number, _, _ in targets]} Cameras change", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "compile", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--url", default="http://127.0.0.1:8188")
    p.add_argument("--camera-file", type=Path)
    p.add_argument("--opening-camera-file", type=Path)
    p.add_argument("--run-name", default=RUN_NAME)
    p.add_argument("--baseline-title", default="Fixed Camera")
    p.add_argument("--candidate-title", default="One-direction Arc")
    args = p.parse_args()
    if args.task == "prepare":
        if not args.source:
            p.error("prepare requires --source")
        prepare(args)
    elif args.task == "compile":
        fields = read(args.output / "conditions.json")["planned_new_fields"]
        compile_camera(args, camera_field=fields[0] if len(fields) == 1 else tuple(fields), plan_builder=connected_plan,
                       plan_validator=verify_middle_camera if len(fields) == 1 else verify_opening_and_middle_cameras,
                       run_name=read(args.output / "h3-manifest.json")["run_names"]["dance"])
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize_middle(args)
