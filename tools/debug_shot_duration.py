"""Research: shorten an accepted isolated Shot without changing its prose or seed."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.emd import parse_emd
from core.h3_contract.timing import DEFAULT_H3_TIMING_PROFILE
from core.lyrics import format_emd_time
from tools.prepare_beat_motion_h3 import read, save, FFMPEG, FFPROBE
from tools.prepare_instrumental_h3 import render

RUN_NAME = "shot-duration-b16-momiji2-s11-20261004"
INPUT = Path(r"C:\Software\ComfyUI\input")


def short_clock(manifest, duration_ms=5000):
    rate = manifest["sample_rate"]
    fps = DEFAULT_H3_TIMING_PROFILE.fps
    if rate % fps or duration_ms * rate % 1000 or duration_ms * fps % 1000:
        raise ValueError("Content must lie on both sample and frame grids")
    size = duration_ms * rate // 1000
    if duration_ms < 1 or size >= manifest["source_end_sample"] - manifest["source_start_sample"]:
        raise ValueError("Use a positive duration shorter than the baseline content")
    frames, delivered, context = DEFAULT_H3_TIMING_PROFILE.quantize_duration_ms(duration_ms, first_scene=True)
    if context or frames != delivered:
        raise ValueError("Requires a fresh isolated Shot")
    return {"source_start_sample": manifest["source_start_sample"],
            "source_end_sample": manifest["source_start_sample"] + size,
            "sample_rate": rate, "content_frames": duration_ms * fps // 1000,
            "render_frames": frames, "tail_silence_samples": frames * (rate // fps) - size,
            "content_duration_ms": duration_ms, "preroll_frames": 0}


def verify_duration_only(baseline, candidate, frames):
    DEFAULT_H3_TIMING_PROFILE.validate_raw_length(frames)
    if len(baseline["shots"]) != 1 or frames >= baseline["shots"][0]["length"]:
        raise ValueError("Requires one isolated Shot and a shorter valid length")
    shot = baseline["shots"][0]
    if shot.get("context_length", 0) or shot.get("audio_context_length", 0):
        raise ValueError("Baseline must have no predecessor context")
    expected = deepcopy(baseline)
    expected["shots"][0]["length"] = frames
    if candidate != expected:
        raise ValueError("Plan changed outside length; do not render")


def isolated_emd(text, duration_ms, frames):
    document = parse_emd(text)
    scenes = [s for s in document.scenes if s.scene_number == 11]
    if len(scenes) != 1 or len(scenes[0].shots) != 1:
        raise ValueError("Expected unique single-Shot Scene 11")
    scene = scenes[0]
    if any(d.mode != "context_loop" for d in scene.audio_directives) or scene.shots[0].lyric_annotations:
        raise ValueError("This instrumental probe does not rewrite vocal timing")
    # Documentary local EMD; the already compiled English Plan is reused verbatim.
    prefix = text.split("# 音声活動", 1)[0]
    prefix = prefix.split("> `シーン`", 1)[0].rstrip()
    body = "\n".join("* " + line for line in scene.shots[0].body)
    descriptions = "\n".join("* " + line for line in scene.descriptions)
    result = (prefix + f"\n\n> `シーン` 1\n# シーン 00:00.000 --> {format_emd_time(duration_ms)}\n"
              f"* `H3長` {frames}\n" + descriptions + "\n## ショット 00:00.000\n" + body + "\n")
    if scene.audio_directives:
        lines = text.splitlines()
        result += "## 音響\n" + "\n".join(lines[d.line_number - 1] for d in scene.audio_directives) + "\n"
    parsed = parse_emd(result)
    if (parsed.scenes[0].shots[0].body != scene.shots[0].body or
        tuple(d.mode for d in parsed.scenes[0].audio_directives) != tuple(d.mode for d in scene.audio_directives)):
        raise ValueError("Performance or Camera changed in documentary EMD")
    return result


def verify_pcm(clock, audio):
    import torch
    from tools.analyze_audio_activity import decode_audio
    checks, fullmix = [], None
    for row in audio:
        original, rate, _ = decode_audio(Path(row["source"]), FFMPEG)
        crop, crop_rate, digest = decode_audio(Path(row["crop"]), FFMPEG)
        size = clock["source_end_sample"] - clock["source_start_sample"]
        if rate != crop_rate or rate != clock["sample_rate"] or not torch.equal(
                original[..., clock["source_start_sample"]:clock["source_end_sample"]], crop[..., :size]):
            raise ValueError("Source PCM was shifted or altered")
        if crop.shape[-1] != clock["render_frames"] * (rate // 24) or crop[..., size:].count_nonzero():
            raise ValueError("Wrong PCM duration or non-silent padding")
        checks.append({"crop": row["crop"], "samples": crop.shape[-1], "source_pcm_equal": True,
                       "tail_is_silence": True, "sha256": digest})
        if "fullmix" in Path(row["crop"]).name:
            fullmix = crop
    return checks, fullmix


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a fresh output directory")
    manifest = read(source / "h3-manifest.json")
    baseline_video = Path(read(source / "media-checks.json")["videos"]["dance"]["path"])
    if not baseline_video.is_file():
        raise ValueError("Completed accepted baseline video is missing")
    clock = short_clock(manifest)
    baseline = read(source / "dance-plan.json")
    candidate = deepcopy(baseline)
    candidate["shots"][0]["length"] = clock["render_frames"]
    verify_duration_only(baseline, candidate, clock["render_frames"])
    emd = isolated_emd((source / "dance.md").read_text(encoding="utf-8"), 5000, clock["render_frames"])
    targets = [INPUT / f"mvd_duration_b16_momiji2_{stem}_s11_20261004.wav" for stem in ("vocal", "fullmix")]
    if any(p.exists() for p in targets):
        raise ValueError("Refusing to overwrite existing PCM")
    graph = read(source / "h3-dance.json")
    if graph["48"]["inputs"]["enable"] or graph["37"]["inputs"]["reference_alignment"] != "off":
        raise ValueError("Unexpected audio clock processing")
    if graph["40"]["inputs"]["voice"] != ["48", 1] or graph["28"]["inputs"]["enabled"]:
        raise ValueError("Standard lip-sync route or ReviewGate setting changed")
    output.mkdir(parents=True, exist_ok=True)
    audio = []
    for row, target in zip(manifest["audio"], targets):
        subprocess.run([FFMPEG, "-v", "error", "-i", row["source"], "-af",
            f"atrim=start_sample={clock['source_start_sample']}:end_sample={clock['source_end_sample']},"
            f"asetpts=PTS-STARTPTS,apad=whole_len={clock['render_frames'] * (clock['sample_rate']//24)}",
            "-c:a", "pcm_f32le", str(target)], check=True)
        audio.append({"source": row["source"], "crop": str(target)})
    checks, _ = verify_pcm(clock, audio)
    for old, new in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                     ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json")):
        shutil.copy2(source / old, output / new)
    (output / "dance.md").write_text(emd, encoding="utf-8")
    save(output / "dance-plan.json", candidate)
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(candidate, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = RUN_NAME
    graph["21"]["inputs"]["filename"] = RUN_NAME
    graph["33"]["inputs"]["audio"] = targets[0].name
    graph["32"]["inputs"]["audio"] = targets[1].name
    save(output / "h3-dance.json", graph)
    save(output / "pcm-checks.json", checks)
    save(output / "h3-manifest.json", {"source": str(source), "baseline_video": str(baseline_video),
        "baseline_clock": manifest, "short_clock": {**clock, "audio": audio},
        "run_name": RUN_NAME, "planner_rerun": False, "compiler_rerun": False,
        "documentary_emd_local_scene": 1, "source_scene": 11, "duration_only_plan_verified": True,
        "comparison_frames": clock["render_frames"], "comparison_no_speed_change": True,
        "fixed": ["Subject", "Event", "Performance", "Camera", "seed", "H3 settings", "source start"],
        "new_render_count": 1, "baseline_render_reused": True})
    print(json.dumps({"prepared": True, "clock": clock, "plan_only_length_changed": True}), flush=True)


def finalize(args):
    import torch
    from tools.analyze_audio_activity import decode_audio
    output = args.output.resolve(strict=True)
    if any((output / name).exists() for name in ("comparison.mp4", "contact-sheet.png", "media-checks.json")):
        raise ValueError("Refusing to overwrite finalized media")
    manifest = read(output / "h3-manifest.json")
    verify_duration_only(read(output / "baseline-plan.json"), read(output / "dance-plan.json"),
                         manifest["short_clock"]["render_frames"])
    candidate = Path(r"C:\Software\ComfyUI\output\h3_chains") / RUN_NAME / "final" / (RUN_NAME + ".mp4")
    videos, checks = {}, {}
    for label, path, clock in (("baseline", Path(manifest["baseline_video"]), manifest["baseline_clock"]),
                              ("dance", candidate, manifest["short_clock"])):
        history = read(output / f"render-{label}.json")
        if history["history"]["status"]["status_str"] != "success":
            raise ValueError("Incomplete render")
        checks[label], fullmix = verify_pcm(clock, clock["audio"])
        probe = json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(path)], encoding="utf-8"))
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        if (video["width"], video["height"], video["r_frame_rate"], int(video["nb_frames"])) != (864, 480, "24/1", clock["render_frames"]):
            raise ValueError("Video resolution or frame clock changed")
        delivered, rate, _ = decode_audio(path, FFMPEG)
        if fullmix is None or rate != clock["sample_rate"]:
            raise ValueError("Fullmix clock unavailable")
        size = min(fullmix.shape[-1], delivered.shape[-1])
        cosine = float(torch.nn.functional.cosine_similarity(
            fullmix.mean(dim=1)[..., :size].reshape(-1), delivered.mean(dim=1)[..., :size].reshape(-1), dim=0))
        if cosine < 0.98:
            raise ValueError("Rendered audio does not match the original clock")
        videos[label] = {"path": str(path), "streams": probe["streams"], "render_wait_s": history["elapsed_s"],
                         "render_audio_zero_offset_fullmix_cosine": cosine}
    frames = manifest["comparison_frames"]
    filters = []
    for i, title in enumerate(("Baseline 10s - first 5s", "Short Shot 5s")):
        filters.append(f"[{i}:v]trim=end_frame={frames},setpts=PTS-STARTPTS,"
            f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='{title}':x=16:y=12:fontsize=24:"
            f"fontcolor=white:box=1:boxcolor=black@0.7[v{i}]")
    filters.append("[v0][v1]vstack[v]")
    comparison = output / "comparison.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-i", videos["baseline"]["path"], "-i", videos["dance"]["path"],
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "1:a:0", "-t", str(frames/24),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", str(comparison)], check=True)
    probe = json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames,r_frame_rate", "-of", "json", str(comparison)], encoding="utf-8"))
    if int(probe["streams"][0]["nb_frames"]) != frames or probe["streams"][0]["r_frame_rate"] != "24/1":
        raise ValueError("Comparison frame clock mismatch")
    subprocess.run([FFMPEG, "-v", "error", "-i", str(comparison), "-vf", "fps=1,scale=432:480,tile=5x1",
                    "-frames:v", "1", str(output / "contact-sheet.png")], check=True)
    save(output / "media-checks.json", {"videos": videos, "pcm_checks": checks, "comparison": str(comparison),
        "comparison_frames": frames, "comparison_audio": "short crop; same source start; tail silence",
        "comparison_no_speed_change": True})
    print(str(comparison), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "render", "finalize"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    args = parser.parse_args()
    if args.task == "prepare":
        if not args.source:
            parser.error("prepare requires --source")
        prepare(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
