"""Prepare, render, and compare two fresh single-Scene P5 clips."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.debug_instrumental_p4 import save
from tools.prepare_instrumental_h3 import render

FFMPEG = r"C:\Software\ffmpeg\bin\ffmpeg.exe"
FFPROBE = r"C:\Software\ffmpeg\bin\ffprobe.exe"
OUTPUT = Path(r"C:\Software\ComfyUI\output\h3_chains")


def prepare(args):
    dest = args.comparison
    if (dest / "h3-manifest.json").exists():
        raise ValueError("Graphs already prepared")
    source = args.source_comparison
    original = json.loads((source / "h3-activity-a3.json").read_text(encoding="utf-8"))
    conditions = json.loads((dest / "conditions.json").read_text(encoding="utf-8"))
    baseline = json.loads((dest / "baseline-plan.json").read_text(encoding="utf-8"))
    index = conditions["scene_start"] - 1
    scene = baseline["shots"][index]
    skip = sum(s["length"] - s.get("context_length", 0) for s in baseline["shots"][:index])
    prefix = scene.get("context_length", 0)
    frames = scene["length"]
    start_sample = (skip - prefix) * 2000
    end_sample = start_sample + frames * 2000
    if start_sample < 0 or end_sample > 13017600:
        raise ValueError("No actual source PCM available for this fresh isolated clock")
    audio = []
    names = {}
    for stem, filename in (("vocal", "千里の秋を駆ける_vocal.wav"), ("fullmix", "千里の秋を駆ける_normalized.wav")):
        name = f"mvd_p5_momiji2_{stem}_s{index + 1}.wav"
        target = Path(r"C:\Software\ComfyUI\input") / name
        if target.exists():
            raise ValueError("Do not overwrite saved PCM crops")
        path = Path(r"E:\OutputCollection\Momiji2") / filename
        subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-af",
            f"atrim=start_sample={start_sample}:end_sample={end_sample},asetpts=PTS-STARTPTS",
            "-c:a", "pcm_f32le", str(target)], check=True)
        audio.append({"source": str(path), "crop": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        names[stem] = name
    for label in ("baseline", "activity"):
        graph = json.loads(json.dumps(original))
        plan = json.loads((dest / f"{label}-plan.json").read_text(encoding="utf-8"))
        plan["shots"] = [plan["shots"][index]]
        name = f"instrumental-p5-momiji2-s{index + 1}-{label}-20261003"
        for node in ("24", "37", "48"):
            graph[node]["inputs"]["plan_json"] = json.dumps(plan, ensure_ascii=False)
        graph["24"]["inputs"]["run_name"] = name
        graph["21"]["inputs"]["filename"] = name
        graph["32"]["inputs"]["audio"] = names["fullmix"]
        graph["33"]["inputs"]["audio"] = names["vocal"]
        if graph["48"]["inputs"]["enable"] or graph["40"]["inputs"]["voice"] != ["48", 1]:
            raise ValueError("Verified source graph clock or standard voice input changed")
        save(dest / f"h3-{label}.json", graph)
    save(dest / "h3-manifest.json", {"conditions": conditions, "source_graph": str(source / "h3-activity-a3.json"),
        "frames": frames, "sample_rate": 48000, "start_sample": start_sample, "end_sample": end_sample,
        "actual_source_preroll_frames": prefix, "megapixels": 0.4, "steps": 20,
        "no_generated_predecessor": True, "audio": audio})
    print(f"P5 graphs ready: {frames} frames, actual PCM {start_sample}..{end_sample}", flush=True)


def finalize(args):
    import torch
    from tools.analyze_audio_activity import decode_audio
    dest = args.comparison
    manifest = json.loads((dest / "h3-manifest.json").read_text(encoding="utf-8"))
    scene = manifest["conditions"]["scene_start"]
    results = {}
    pcm_checks = []
    for row in manifest["audio"]:
        source, source_rate, _ = decode_audio(Path(row["source"]), FFMPEG)
        crop, crop_rate, digest = decode_audio(Path(row["crop"]), FFMPEG)
        equal = source_rate == crop_rate == manifest["sample_rate"] and torch.equal(
            source[..., manifest["start_sample"]:manifest["end_sample"]], crop)
        if not equal or crop.shape[-1] != manifest["frames"] * 2000:
            raise ValueError("PCM differs from actual source or render frame clock")
        pcm_checks.append({"crop": row["crop"], "source_pcm_equal": equal,
            "samples": crop.shape[-1], "sample_rate": crop_rate, "pcm_sha256": digest})
    for label in ("baseline", "activity"):
        history = json.loads((dest / f"render-{label}.json").read_text(encoding="utf-8"))
        if history["history"]["status"]["status_str"] != "success":
            raise ValueError("Render failed")
        name = f"instrumental-p5-momiji2-s{scene}-{label}-20261003"
        video = OUTPUT / name / "final" / f"{name}.mp4"
        probe = json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(video)], encoding="utf-8"))
        stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
        if (stream["width"], stream["height"], stream["r_frame_rate"], int(stream["nb_frames"])) != (864, 480, "24/1", manifest["frames"]):
            raise ValueError("Unexpected render dimensions or PCM clock")
        results[label] = {"video": str(video), "streams": probe["streams"], "poll_elapsed_s": history["elapsed_s"]}
    target = dest / "comparison.mp4"
    if target.exists():
        raise ValueError("Comparison already completed")
    subprocess.run([FFMPEG, "-v", "error", "-i", results["baseline"]["video"], "-i", results["activity"]["video"],
        "-filter_complex",
        "[0:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='All Candidate Pools':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[t];"
        "[1:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='PCM Routed Candidates':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[b];[t][b]vstack[v]",
        "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac",
        "-b:a", "256k", "-movflags", "+faststart", str(target)], check=True)
    for label in ("baseline", "activity"):
        source = (dest / f"{label}.md").read_text(encoding="utf-8")
        parts = source.split("> `シーン` ")
        excerpt = "# 伴奏SceneのEMD抜粋\n\n本編時刻表記。単独Scene比較で歌唱復帰は含まない。\n\n"
        excerpt += "\n".join("> `シーン` " + part for part in parts[1:] if part.split("\n", 1)[0] in (str(scene), f"{scene}"))
        (dest / f"{label}-excerpt.md").write_text(excerpt, encoding="utf-8")
    results["comparison"] = str(target)
    results["pcm_checks"] = pcm_checks
    save(dest / "media-checks.json", results)
    print(json.dumps(results, ensure_ascii=False), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "render", "finalize"))
    p.add_argument("--comparison", type=Path, required=True)
    p.add_argument("--source-comparison", type=Path)
    p.add_argument("--label", choices=("baseline", "activity"))
    p.add_argument("--url", default="http://127.0.0.1:8191")
    args = p.parse_args()
    if args.task == "render":
        if args.label is None:
            p.error("render requires --label")
        render(args.comparison, args.label, args.url)
    elif args.task == "prepare":
        if args.source_comparison is None:
            p.error("prepare requires --source-comparison")
        prepare(args)
    else:
        finalize(args)


if __name__ == "__main__":
    main()
