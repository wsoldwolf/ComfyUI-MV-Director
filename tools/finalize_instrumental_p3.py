"""CPU-only comparison of the saved P2 activity result and the P3 candidate."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--run-name", default="instrumental-p3-momiji2-prompt-20261003")
    parser.add_argument("--candidate-label", default="P3 Prompt Update")
    args = parser.parse_args()
    ffmpeg = r"C:\Software\ffmpeg\bin\ffmpeg.exe"
    ffprobe = r"C:\Software\ffmpeg\bin\ffprobe.exe"
    checks = json.loads((args.previous / "media-checks.json").read_text(encoding="utf-8"))
    baseline_plan = json.loads((args.comparison / "baseline-plan.json").read_text(encoding="utf-8"))
    candidate_plan = json.loads((args.comparison / "activity-plan.json").read_text(encoding="utf-8"))
    baseline_globals = {k: v for k, v in baseline_plan.items() if k != "shots"}
    candidate_globals = {k: v for k, v in candidate_plan.items() if k != "shots"}
    if baseline_globals != candidate_globals:
        raise ValueError("Plan globals or activity metadata changed")
    baseline = Path(checks["activity"]["video"])
    if not args.run_name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in args.run_name):
        raise ValueError("Invalid run name")
    if not args.candidate_label or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -" for c in args.candidate_label):
        raise ValueError("Use a plain ASCII comparison label")
    run = Path(r"C:\Software\ComfyUI\output\h3_chains") / args.run_name
    history = json.loads((args.comparison / "render-activity.json").read_text(encoding="utf-8"))
    if history["history"]["status"]["status_str"] != "success":
        raise ValueError("Candidate did not finish successfully")
    videos = list((run / "final").glob("*.mp4"))
    if len(videos) != 1:
        raise ValueError("Expected one completed candidate video")
    candidate = videos[0]
    result = {"common_plan_globals_equal": True}
    prefix_hashes = []
    prefixes = (Path(checks["activity"]["predecessor"]), *list((run / "segments").glob("clip_0001.*.mp4")))
    if len(prefixes) != 2:
        raise ValueError("Unexpected predecessor clips")
    for label, video, prefix in zip(("baseline", "candidate"), (baseline, candidate), prefixes):
        probe = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(video)], encoding="utf-8"))
        stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
        if (stream["width"], stream["height"], stream["nb_frames"]) != (864, 480, "498"):
            raise ValueError("Render dimensions or audio-clock frame count changed")
        result[label] = {"video": str(video), "streams": probe["streams"]}
        prefix_hashes.append(subprocess.check_output([ffmpeg, "-v", "error", "-i", str(prefix),
            "-map", "0:v:0", "-f", "framemd5", "-"], encoding="utf-8"))
    result["common_predecessor_decoded_frames_equal"] = prefix_hashes[0] == prefix_hashes[1]
    result["candidate_poll_elapsed_s"] = history["elapsed_s"]
    target = args.comparison / "comparison.mp4"
    if target.exists():
        raise ValueError("Do not overwrite a completed comparison")
    subprocess.run([ffmpeg, "-v", "error", "-i", str(baseline), "-i", str(candidate),
        "-filter_complex",
        "[0:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='P2 Audio Activity':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[t];"
        f"[1:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='{args.candidate_label}':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[b];[t][b]vstack[v]",
        "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(target)], check=True)
    result["comparison_video"] = str(target)
    for label in ("baseline", "activity"):
        source = (args.comparison / f"{label}.md").read_text(encoding="utf-8")
        parts = source.split("> `シーン` ")
        excerpt = "# 伴奏と歌唱復帰のEMD抜粋\n\nScene 12–13。本編時刻表記。比較動画は98.458333秒から始まる。\n\n"
        excerpt += "\n".join("> `シーン` " + p for p in parts[1:] if p.split("\n", 1)[0] in ("12", "13"))
        (args.comparison / f"{label}-excerpt.md").write_text(excerpt, encoding="utf-8")
    (args.comparison / "media-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
