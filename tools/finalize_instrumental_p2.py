"""CPU-only P2 media comparison and common-predecessor pixel verification."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    args = parser.parse_args()
    ffmpeg = r"C:\Software\ffmpeg\bin\ffmpeg.exe"
    ffprobe = r"C:\Software\ffmpeg\bin\ffprobe.exe"
    videos = []
    checks = {}
    prefix_hashes = []
    for label in ("baseline", "activity"):
        source = (args.comparison / f"{label}.md").read_text(encoding="utf-8")
        parts = source.split("> `シーン` ")
        excerpt = "# 伴奏と歌唱復帰のEMD抜粋\n\n原EMDのScene 12と13。時刻は本編Plan上の時刻で、比較映像は元音源98.458333秒から始まる。\n\n"
        excerpt += "\n".join("> `シーン` " + part for part in parts[1:] if part.split("\n", 1)[0] in ("12", "13"))
        (args.comparison / f"{label}-excerpt.md").write_text(excerpt, encoding="utf-8")
        history = json.loads((args.comparison / f"render-{label}-a3.json").read_text(encoding="utf-8"))
        if history["history"]["status"]["status_str"] != "success":
            raise ValueError(f"{label} did not succeed")
        run = Path(r"C:\Software\ComfyUI\output\h3_chains") / f"instrumental-p2-momiji2-{label}-a3-20261003"
        finals = list((run / "final").glob("*.mp4"))
        prefix = list((run / "segments").glob("clip_0001.*.mp4"))
        if len(finals) != 1 or len(prefix) != 1:
            raise ValueError(f"Unexpected output files in {run}")
        video = finals[0]
        videos.append(video)
        probe = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(video)], encoding="utf-8"))
        md5 = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(prefix[0]), "-map", "0:v:0", "-f", "framemd5", "-"], encoding="utf-8")
        prefix_hashes.append(md5)
        checks[label] = {"video": str(video), "predecessor": str(prefix[0]), "streams": probe["streams"], "elapsed_s": history["elapsed_s"]}
    checks["common_predecessor_decoded_frames_equal"] = prefix_hashes[0] == prefix_hashes[1]
    target = args.comparison / "comparison.mp4"
    if target.exists():
        raise ValueError("Comparison video already exists")
    subprocess.run([ffmpeg, "-v", "error", "-i", str(videos[0]), "-i", str(videos[1]),
        "-filter_complex",
        "[0:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='Baseline':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[t];"
        "[1:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='Audio Activity':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[b];[t][b]vstack[v]",
        "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(target)], check=True)
    checks["comparison_video"] = str(target)
    checks["comparison_audio"] = "baseline full mix; source PCM is identical for both conditions"
    (args.comparison / "media-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
