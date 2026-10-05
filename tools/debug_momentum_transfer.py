"""Research: transfer the accepted staging candidate to a second instrumental Scene.

Only the target Performance is generated. The cache-only dummy Plan is a
structural guard, not a rendered baseline or a quality comparator.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.compiler import compile_ref2va
from core.emd import parse_emd
from core.h3_contract.timing import DEFAULT_H3_TIMING_PROFILE
from nodes.node_timeline_planner.node import _system_prompts
from tools.debug_momentum_pipeline import USER_REQUEST, production_inputs, infer
from tools.debug_shot_duration import verify_pcm
from tools.prepare_beat_motion_h3 import read, save, fresh_plan, FFMPEG, FFPROBE
from tools.prepare_instrumental_h3 import render

SCENE = 12
RUN_NAME = "momentum-transfer-b18-momiji2-s12-20261004"
PLACEHOLDER = "検証対象外。"
PLACEHOLDER_EN = "Outside the scope of verification."


def transfer_input(text):
    """Change target author fields only; preserve every unrelated Scene verbatim."""
    document = parse_emd(text)
    source = next(s for s in document.scenes if s.scene_number == 11).shots[0]
    target = next(s for s in document.scenes if s.scene_number == SCENE)
    if len(target.shots) != 1 or target.shots[0].lyric_annotations:
        raise ValueError("Requires one lyric-free target Shot")
    fields = {d.kind: line for d, line in zip(source.directives, source.body)}
    if set(fields) != {"演出", "カメラ", "演技"}:
        raise ValueError("Accepted source must have three fields")
    parts = re.split(r"(?=> `シーン` \d+)", text)
    matches = [i for i, chunk in enumerate(parts) if chunk.startswith(f"> `シーン` {SCENE}\n")]
    if len(matches) != 1:
        raise ValueError("Target Scene must be unique")
    i = matches[0]
    chunk, count = re.subn(r"^\* `カメラ` .*?$", "* " + fields["カメラ"], parts[i], flags=re.M)
    if count != 1 or chunk.count("* `演技` " + PLACEHOLDER) != 1:
        raise ValueError("Target must contain one dummy Performance and Camera")
    chunk = chunk.replace("* `カメラ`", "* " + fields["演出"] + "\n* `カメラ`", 1)
    # Align the guard field order with the normal renderer: Event, Camera, Performance.
    chunk = chunk.replace("* `演技` " + PLACEHOLDER + "\n", "")
    chunk = chunk.replace("* " + fields["カメラ"] + "\n",
                          "* " + fields["カメラ"] + "\n* `演技` " + PLACEHOLDER + "\n", 1)
    parts[i] = chunk
    result = "".join(parts)
    template, _, _, _ = production_inputs(result, USER_REQUEST, target_scene=SCENE)
    if template.scenes[SCENE - 1].shots[0].lyric_annotations:
        raise ValueError("Unexpected target lyrics")
    return result


def scene_clock(text):
    scene = next(s for s in parse_emd(text).scenes if s.scene_number == SCENE)
    rate, fps = 48000, DEFAULT_H3_TIMING_PROFILE.fps
    start, end = scene.start_ms * rate // 1000, scene.end_ms * rate // 1000
    size = end - start
    if size % (rate // fps):
        raise ValueError("Source interval must lie on frame and sample grids")
    content = size // (rate // fps)
    frames, delivered, context = DEFAULT_H3_TIMING_PROFILE.quantize_delivered_frames(content, first_scene=True)
    if context or frames != delivered:
        raise ValueError("Requires a fresh isolated frame clock")
    return {"source_start_sample": start, "source_end_sample": end,
            "sample_rate": rate, "content_frames": content, "render_frames": frames,
            "tail_silence_samples": frames * (rate // fps) - size, "preroll_frames": 0}


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty research destination")
    source_manifest = read(source / "h3-manifest.json")
    text = transfer_input((source / "dance.md").read_text(encoding="utf-8"))
    clock = scene_clock(text)
    document = parse_emd(text)
    activity = document.audio_activity.scene_payload(start_ms=99375, end_ms=110000, audio_mode="context_loop")
    if not activity["intervals"] or any(row["state"] != "instrumental_candidate" for row in activity["intervals"]):
        raise ValueError("Target audio activity is not purely instrumental")
    cache = {tuple(row["fragments"]): tuple(row["translated"]) for row in read(source / "translation.json")}

    class CacheOnly:
        def translate(self, units):
            if tuple(units) not in cache:
                raise ValueError(f"Guard contains uncached prose: {units}")
            return cache[tuple(units)]

    guard = compile_ref2va(text, CacheOnly()).plan
    for i, shot in enumerate(guard["shots"], 1):
        shot["seed"] = 20261003 + i
    guard = fresh_plan(guard, clock["render_frames"], scene=SCENE)
    guard["shots"][0]["continuation_mode"] = "guide"
    if sum(line.count(PLACEHOLDER_EN) for line in guard["shots"][0]["prompt"]) != 1:
        raise ValueError("Dummy guard is not unique")
    graph = deepcopy(read(source / "h3-dance.json"))
    if graph["48"]["inputs"]["enable"] or graph["37"]["inputs"]["reference_alignment"] != "off":
        raise ValueError("Unexpected PCM clock adapter")
    if graph["40"]["inputs"]["voice"] != ["48", 1] or graph["28"]["inputs"]["enabled"]:
        raise ValueError("Lip-sync or ReviewGate route changed")
    targets = [Path(r"C:\Software\ComfyUI\input") / f"mvd_transfer_b18_momiji2_{stem}_s12_20261004.wav"
               for stem in ("vocal", "fullmix")]
    if any(p.exists() for p in targets):
        raise ValueError("Refusing to overwrite PCM evidence")
    output.mkdir(parents=True)
    audio = []
    for row, target in zip(source_manifest["audio"], targets):
        subprocess.run([FFMPEG, "-v", "error", "-i", row["source"], "-af",
            f"atrim=start_sample={clock['source_start_sample']}:end_sample={clock['source_end_sample']},"
            f"asetpts=PTS-STARTPTS,apad=whole_len={clock['render_frames'] * 2000}",
            "-c:a", "pcm_f32le", str(target)], check=True)
        audio.append({"source": row["source"], "crop": str(target)})
    checks, _ = verify_pcm(clock, audio)
    prompts = _system_prompts()
    conditions = read(source / "conditions.json")
    save(output / "conditions.json", {"model": conditions["model"], "runtime": conditions["runtime"],
        "scene": SCENE, "source": str(source), "sample_rate": clock["sample_rate"],
        "source_pcm_window_samples": [clock["source_start_sample"], clock["source_end_sample"]],
        "camera_authorship": "fixed Camera borrowed from accepted Scene 11",
        "staging_candidate_policy": "optional", "compiler_max_tokens": 4096,
        "translation_cache": str(source / "translation.json"),
        "baseline_performance_english": PLACEHOLDER_EN,
        "scope": "Scene 12 Performance only through normal Planner and Compiler",
        "system_prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()}})
    save(output / "system-prompts.json", prompts)
    (output / "user-request.md").write_text(USER_REQUEST, encoding="utf-8")
    (output / "input-emd.md").write_text(text, encoding="utf-8")
    save(output / "baseline-plan.json", guard)
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(guard, ensure_ascii=False)
    graph["33"]["inputs"]["audio"], graph["32"]["inputs"]["audio"] = targets[0].name, targets[1].name
    save(output / "h3-baseline.json", graph)
    save(output / "pcm-checks.json", checks)
    save(output / "input-contract.json", {"target_scene": SCENE,
        "source_start_ms": 99375, "source_end_ms": 110000, "audio_activity": activity,
        "candidate": USER_REQUEST, "fixed_event_camera_source_scene": 11,
        "target_continuation": False, "source_predecessor_reused": False,
        "guard_baseline_not_for_rendering": True, "same_scene_baseline_video": None,
        "normal_planner_compiler": True, "no_authored_english_insertion": True})
    save(output / "h3-manifest.json", {**clock, "audio": audio, "scene": SCENE,
        "source": str(source), "run_names": {"dance": RUN_NAME}, "megapixels": 0.4, "steps": 20,
        "seed": 20261015, "guard_baseline_not_for_rendering": True,
        "same_scene_baseline_video": None, "new_render_count": 1,
        "planner_rerun": True, "compiler_used": True})
    print(json.dumps({"prepared": True, "clock": clock, "GPU_used": False}), flush=True)


def finalize(args):
    import torch
    from tools.analyze_audio_activity import decode_audio
    output = args.output.resolve(strict=True)
    if (output / "media-checks.json").exists():
        raise ValueError("Evidence already finalized")
    manifest, history = read(output / "h3-manifest.json"), read(output / "render-dance.json")
    if history["history"]["status"]["status_str"] != "success":
        raise ValueError("Incomplete render")
    checks, fullmix = verify_pcm(manifest, manifest["audio"])
    path = Path(r"C:\Software\ComfyUI\output\h3_chains") / RUN_NAME / "final" / (RUN_NAME + ".mp4")
    probe = json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(path)], encoding="utf-8"))
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if (video["width"], video["height"], video["r_frame_rate"], int(video["nb_frames"])) != (864, 480, "24/1", manifest["render_frames"]):
        raise ValueError("Wrong rendered frame clock")
    delivered, rate, _ = decode_audio(path, FFMPEG)
    if fullmix is None or rate != 48000:
        raise ValueError("Fullmix clock unavailable")
    size = min(fullmix.shape[-1], delivered.shape[-1])
    cosine = float(torch.nn.functional.cosine_similarity(fullmix.mean(dim=1)[..., :size].reshape(-1),
                                                       delivered.mean(dim=1)[..., :size].reshape(-1), dim=0))
    if cosine < 0.98:
        raise ValueError("Output fullmix clock mismatch")
    subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", "fps=1,scale=432:240,tile=5x2",
                    "-frames:v", "1", str(output / "contact-sheet.png")], check=True)
    save(output / "media-checks.json", {"videos": {"dance": {"path": str(path), "streams": probe["streams"],
        "render_wait_s": history["elapsed_s"], "render_audio_zero_offset_fullmix_cosine": cosine}},
        "pcm_checks": checks, "same_scene_baseline_video": None, "human_evaluation": "pending"})
    print(str(path), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "infer", "render", "finalize"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "prepare":
        if not args.source:
            parser.error("prepare requires --source")
        prepare(args)
    elif args.task == "infer":
        infer(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
