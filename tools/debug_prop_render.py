"""Prepare an opt-in Scene 16 H3 diagnostic, retaining source predecessor artifacts.

No production prompt changes. Saved prop-decision prose is compiled verbatim;
only the requested Scene's prompt changes in the submitted editor Plan.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def stage_audio(graph, case):
    rows = []
    for key, stem in (("32", "fullmix"), ("33", "vocal")):
        source = Path(graph[key]["inputs"]["audio"])
        target = Path(r"C:\Software\ComfyUI\input") / f"{case}-{stem}.wav"
        if target.exists():
            raise ValueError("Do not overwrite diagnostic input PCM")
        shutil.copy2(source, target)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("PCM copy differs")
        graph[key]["inputs"]["audio"] = target.name
        rows.append({"source": str(source), "input_copy": str(target), "sha256": digest})
    return rows


def finalize(args):
    output_root = Path(r"C:\Software\ComfyUI\output")
    run = output_root / "h3_chains" / args.case
    evidence = read(args.output / "manifest.json")
    history = read(args.output / "render-candidate.json")
    if history["history"]["status"]["status_str"] != "success":
        raise ValueError("H3 render did not succeed")
    current = read(run / "checkpoints" / f"clip_{args.scene:04d}.json")
    original = read(args.source_run / "checkpoints" / f"clip_{args.scene:04d}.json")
    predecessor = read(args.source_run / "checkpoints" / f"clip_{args.scene - 1:04d}.json")
    if current["segment"]["predecessor_checkpoint_sha256"] != predecessor["segment"]["checkpoint_sha256"]:
        raise ValueError("Rendered with a different predecessor")
    for key in ("width", "height"):
        if current["compatibility"][key] != evidence[key]:
            raise ValueError("Rendered dimensions differ")
    for key in ("raw_frames", "delivered_frames", "seed", "steps", "context_length", "audio_context_length"):
        if current["segment"][key] != original["segment"][key]:
            raise ValueError(f"Render changed {key}")
    videos = [output_root / item["segment"]["segment"] for item in (original, current)]
    ffmpeg = r"C:\Software\ffmpeg\bin\ffmpeg.exe"
    ffprobe = r"C:\Software\ffmpeg\bin\ffprobe.exe"
    probes = []
    for video in videos:
        probe = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,nb_frames,duration", "-of", "json", str(video)], encoding="utf-8"))
        stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
        if (stream["width"], stream["height"], stream["r_frame_rate"], int(stream["nb_frames"])) != (1280, 736, "24/1", 238):
            raise ValueError("Unexpected comparison video format")
        probes.append(probe)
    comparison = args.output / "comparison.mp4"
    if comparison.exists():
        raise ValueError("Do not overwrite saved comparison")
    subprocess.run([ffmpeg, "-v", "error", "-i", str(videos[0]), "-i", str(videos[1]),
        "-filter_complex",
        "[0:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='Original':x=16:y=12:fontsize=32:fontcolor=white:box=1:boxcolor=black@0.7[t];"
        "[1:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='Prop Decision - Diagnostic':x=16:y=12:fontsize=32:fontcolor=white:box=1:boxcolor=black@0.7[b];[t][b]vstack[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-movflags", "+faststart", str(comparison)], check=True)
    for label, video in zip(("original", "candidate"), videos):
        subprocess.run([ffmpeg, "-v", "error", "-ss", "4.5", "-i", str(video), "-vf",
            "fps=2,scale=640:368,tile=3x2", "-frames:v", "1", str(args.output / f"{label}-4p5-7p5.png")], check=True)
    save(args.output / "media-checks.json", {
        "videos": list(map(str, videos)), "comparison": str(comparison), "streams": probes,
        "h3_elapsed_seconds": history["elapsed_s"], "same_predecessor_checkpoint": True,
        "same_seed_steps_dimensions_timing": True, "source_run_untouched": True,
        "original_metadata_sha256": hashlib.sha256((args.source_run / "checkpoints" / f"clip_{args.scene:04d}.json").read_bytes()).hexdigest(),
    })
    print(json.dumps({"candidate": str(videos[1]), "comparison": str(comparison)}, ensure_ascii=False), flush=True)


def main():
    from core.compiler import LlamaPromptTranslator, compile_ref2va
    from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
    from nodes.node_emd_compiler.node import _system_prompt

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-run", type=Path, required=True)
    p.add_argument("--source-emd", type=Path, required=True)
    p.add_argument("--candidate-emd", type=Path, required=True)
    cached = p.add_mutually_exclusive_group(required=True)
    cached.add_argument("--cache", type=Path)
    cached.add_argument("--saved-render", type=Path,
                        help="Reuse a verified previous render's full translation trace if temporary cache was cleared")
    p.add_argument("--conditions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--scene", type=int, default=16)
    p.add_argument("--stage-audio-only", action="store_true")
    p.add_argument("--finalize-only", action="store_true")
    args = p.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]+", args.case):
        p.error("Unsafe case name")
    if args.finalize_only:
        finalize(args)
        return
    if args.stage_audio_only:
        graph = read(args.output / "h3-candidate.json")
        rows = stage_audio(graph, args.case)
        save(args.output / "h3-candidate.json", graph)
        save(args.output / "input-pcm-copies.json", rows)
        return
    if args.output.exists():
        raise ValueError("Use a fresh evidence directory")
    run_dest = Path(r"C:\Software\ComfyUI\output\h3_chains") / args.case
    if run_dest.exists():
        raise ValueError("Run name already exists")
    graph = read(args.source_run / "api_prompt.json")
    baseline = json.loads(base64.b64decode(graph["39"]["inputs"]["file_data_base64"]).decode("utf-8-sig"))
    if args.cache:
        cache_payload = read(args.cache)["payload"]
        if json.loads(cache_payload["plan_json"]) != baseline:
            raise ValueError("Translation cache is not the executed source Plan")
        translation_rows = cache_payload["translation_trace"]
    else:
        saved_manifest = read(args.saved_render / "manifest.json")
        if (Path(saved_manifest["source_run"]).resolve() != args.source_run.resolve()
                or saved_manifest["scene"] != args.scene):
            raise ValueError("Saved render has a different source or selected Scene")
        translation_rows = read(args.saved_render / "translation.json")
    source = args.source_emd.read_text(encoding="utf-8-sig")
    candidate = args.candidate_emd.read_text(encoding="utf-8-sig")
    pattern = r"(?=> `シーン` [1-9][0-9]*\n)"
    chunks = re.split(pattern, source)
    candidates = re.split(pattern, candidate)
    selected = [s for s in candidates if s.startswith(f"> `シーン` {args.scene}\n")]
    if len(selected) != 1:
        raise ValueError("Candidate Scene not unique")
    text = "".join(selected[0] if s.startswith(f"> `シーン` {args.scene}\n") else s for s in chunks)
    args.output.mkdir(parents=True)
    (args.output / "candidate.md").write_text(text, encoding="utf-8")
    cache = {}
    for row in translation_rows:
        key, value = tuple(row["fragments"]), tuple(row["translated"])
        if key in cache and cache[key] != value:
            raise ValueError("Conflicting saved translation evidence")
        cache[key] = value
    condition = read(args.conditions)
    config = replace(LlamaRuntimeConfig(**condition["runtime"]), temperature=0.0, max_tokens=4096)
    lifecycle = LlamaCppLifecycle()
    trace = []
    try:
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(), runtime_config=config)
        class CachedTranslator:
            def translate(self, units):
                key = tuple(units)
                self.reused = key in cache
                if not self.reused:
                    lifecycle.ensure_loaded(Path(condition["model"]), config)
                    cache[key] = tuple(translator.translate(units))
                return cache[key]

            def record_field_translation(self, **kwargs):
                trace.append({**kwargs, "reused_saved_translation": self.reused})

        class SavedTranslator:
            def translate(self, units):
                return cache[tuple(units)]
        proof_text = source if args.cache else (args.saved_render / "candidate.md").read_text(encoding="utf-8-sig")
        compiled_baseline = compile_ref2va(proof_text, SavedTranslator()).plan
        if not args.cache:
            # The prior diagnostic altered this Scene, not the original one.
            # Validate its compilation against the executed original everywhere
            # else. Its old selected prompt is intentionally not reused as truth.
            compiled_baseline["shots"][args.scene - 1]["prompt"] = baseline["shots"][args.scene - 1]["prompt"]
        # Fail rather than silently adopting unrelated compiler drift.
        if compiled_baseline != baseline:
            raise ValueError("Current compiler no longer reproduces saved source Plan")
        compiled = compile_ref2va(text, CachedTranslator()).plan
    finally:
        lifecycle.clear()
        save(args.output / "translation.json", trace)
    unchanged = deepcopy(compiled)
    unchanged["shots"][args.scene - 1]["prompt"] = baseline["shots"][args.scene - 1]["prompt"]
    if unchanged != baseline:
        raise ValueError("Compilation changed fields outside selected Scene prompt")
    runtime_plan = read(args.source_run / "plan.json")
    for i, shot in enumerate(compiled["shots"]):
        shot["seed"] = runtime_plan["shots"][i]["seed"]
    save(args.output / "candidate-plan.json", compiled)
    plan_text = json.dumps(compiled, ensure_ascii=False)
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = plan_text
    graph["48"]["inputs"]["enable"] = False
    graph["24"]["inputs"].update(run_name=args.case)
    graph["7"]["inputs"].update(start_clip=args.scene, scene_range=str(args.scene), verify_resume_history=True)
    graph["29"]["inputs"].update(start_clip=args.scene, scene_range=str(args.scene), verify_resume_history=True)
    graph["28"]["inputs"]["enabled"] = False
    graph["21"]["inputs"]["filename"] = args.case
    # Use the exact saved padded PCM; don't rely on a possibly replaced input file.
    graph["32"]["inputs"]["audio"] = runtime_plan["source_timeline"]["audio"]["path"]
    graph["33"]["inputs"]["audio"] = runtime_plan["source_timeline"]["audio_tracks"]["vocals"]["audio"]["path"]
    save(args.output / "input-pcm-copies.json", stage_audio(graph, args.case))
    selected_graph = {}
    def visit(key):
        if key in selected_graph:
            return
        selected_graph[key] = {k: graph[key][k] for k in ("class_type", "inputs")}
        for value in graph[key]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph:
                visit(value[0])
    visit("21")
    save(args.output / "h3-candidate.json", selected_graph)
    # Metadata copies retain original immutable artifact pointers. The source
    # run is never written, and resume-history verification stays enabled.
    (run_dest / "checkpoints").mkdir(parents=True)
    copied = []
    for scene in range(1, args.scene):
        src = args.source_run / "checkpoints" / f"clip_{scene:04d}.json"
        dst = run_dest / "checkpoints" / src.name
        shutil.copy2(src, dst)
        copied.append({"source": str(src), "copy": str(dst), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
    save(args.output / "manifest.json", {
        "source_run": str(args.source_run), "candidate_emd": str(args.candidate_emd),
        "scene": args.scene, "case": args.case, "model": condition["model"], "runtime": config.to_dict(),
        "seed": compiled["shots"][args.scene - 1]["seed"], "steps": 20,
        "width": 1280, "height": 736, "predecessor_metadata": copied,
        "only_selected_scene_prompt_changed": True, "prop_plan_not_visually_verified": True,
        "translation_evidence": str(args.cache or args.saved_render),
        "new_translation_fields": [r["field_id"] for r in trace if not r["reused_saved_translation"]],
        "reference_assets": [{"input": graph[k]["inputs"]["image"],
            "sha256": hashlib.sha256((Path(r"C:\Software\ComfyUI\input") / graph[k]["inputs"]["image"]).read_bytes()).hexdigest()}
            for k in ("26", "45")],
    })
    print(f"Prepared {args.case}: Scene {args.scene}, exact predecessor retained", flush=True)


if __name__ == "__main__":
    main()
