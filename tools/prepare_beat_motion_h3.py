"""Research B2: compile saved B1 prose and render a clock-aligned fresh pair.

No Planner rerun and no production prompt changes. Only performance differs.
Fresh length/PCM changes are identical in both arms and explicitly recorded.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FFMPEG = r"C:\Software\ffmpeg\bin\ffmpeg.exe"
FFPROBE = r"C:\Software\ffmpeg\bin\ffprobe.exe"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def replace_scene_prose(text, prose, camera, scene=11):
    chunks = re.split(r"(?=> `シーン` [1-9][0-9]*\n)", text)
    found = 0
    for i, chunk in enumerate(chunks):
        if chunk.startswith(f"> `シーン` {scene}\n"):
            chunk, n = re.subn(r"^\* `演技` .+$", lambda _: "* `演技` " + prose, chunk, flags=re.M)
            chunk, m = re.subn(r"^\* `カメラ` .+$", lambda _: "* `カメラ` " + camera, chunk, flags=re.M)
            if n != 1 or m != 1:
                raise ValueError("Expected one Performance and one Camera")
            chunks[i] = chunk
            found += 1
    if found != 1:
        raise ValueError("Target Scene not unique")
    return "".join(chunks)


def fresh_plan(plan, frames, scene=11):
    result = deepcopy(plan)
    result["shots"] = [result["shots"][scene - 1]]
    shot = result["shots"][0]
    shot.update(length=frames, context_length=0, audio_context_length=0)
    # The full-song activity/source-copies clock is invalid for a direct PCM crop.
    result.pop("mv_director_audio_activity", None)
    return result


def verify_subject_only(before, after, old_english, new_english):
    normalized = deepcopy(after)
    count = 0
    for shot in normalized["shots"]:
        for i, line in enumerate(shot["prompt"]):
            if new_english in line:
                count += 1
                shot["prompt"][i] = line.replace(new_english, old_english)
    if count != len(before["shots"]) or normalized != before:
        raise ValueError("Plan changed outside the shared Subject description")


def repair_clothing(args):
    from core.compiler import LlamaPromptTranslator, compile_ref2va
    from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
    from nodes.node_emd_compiler.node import _system_prompt
    from tools.debug_instrumental_p4 import verify_body_only_plan
    source, dest = args.source, args.output
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Use an empty correction destination")
    with urlopen(args.url + "/queue", timeout=30) as response:
        queue = json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; left intact")
    manifest = read(source / "h3-manifest.json")
    condition = read(Path(manifest["source_b1"]) / "conditions.json")
    old_japanese = "黒と赤の縞模様の下着"
    new_japanese = "黒地に赤い裾模様の足首丈の袴スカート"
    cache = {}
    for label in ("baseline", "timed"):
        for row in read(source / f"{label}-translation.json"):
            cache[tuple(row["fragments"])] = tuple(row["translated"])
    dest.mkdir(parents=True)
    config = LlamaRuntimeConfig(**condition["runtime"])
    lifecycle = LlamaCppLifecycle()
    plans, bodies, names = {}, {}, {}
    try:
        lifecycle.ensure_loaded(Path(condition["model"]), config)
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
            runtime_config=replace(config, temperature=0.0, max_tokens=4096))
        class CachedTranslator:
            def __init__(self):
                self.translation_trace = []
            def translate(self, units):
                key = tuple(units)
                self.reused = key in cache
                if not self.reused:
                    cache[key] = tuple(translator.translate(units))
                return cache[key]
            def record_field_translation(self, **kwargs):
                self.translation_trace.append({**kwargs, "reused_saved_translation": self.reused})
        for label in ("baseline", "timed"):
            emd = (source / f"{label}.md").read_text(encoding="utf-8")
            if emd.count(old_japanese) != 1:
                raise ValueError("Expected exactly one inherited clothing error")
            emd = emd.replace(old_japanese, new_japanese)
            (dest / f"{label}.md").write_text(emd, encoding="utf-8")
            cached = CachedTranslator()
            plan = compile_ref2va(emd, cached).plan
            for index, shot in enumerate(plan["shots"], 1):
                shot["seed"] = 20261003 + index
            before = read(source / f"{label}-full-plan.json")
            old_subject = next(row["restored"] for row in read(source / f"{label}-translation.json")
                               if row["field_id"] == "subject.0.description")
            new_subject = next(row["restored"] for row in cached.translation_trace
                               if row["field_id"] == "subject.0.description")
            verify_subject_only(before, plan, old_subject, new_subject)
            bodies[label] = next(row["restored"] for row in cached.translation_trace
                                 if row["field_id"] == "scene.10.shot.0.body.1")
            save(dest / f"{label}-translation.json", cached.translation_trace)
            save(dest / f"{label}-full-plan.json", plan)
            plans[label] = plan
            print(json.dumps({"label": label, "subject": new_subject}, ensure_ascii=False), flush=True)
    finally:
        lifecycle.clear()
    verify_body_only_plan(plans["baseline"], plans["timed"], 11, bodies["baseline"], bodies["timed"])
    for label in ("baseline", "timed"):
        plan = fresh_plan(plans[label], manifest["render_frames"])
        save(dest / f"{label}-plan.json", plan)
        graph = read(source / f"h3-{label}.json")
        names[label] = f"beat-b2-momiji2-s11-{label}-costume-a2-20261003"
        for key in ("24", "37", "48"):
            graph[key]["inputs"]["plan_json"] = json.dumps(plan, ensure_ascii=False)
        graph["24"]["inputs"]["run_name"] = names[label]
        graph["21"]["inputs"]["filename"] = names[label]
        save(dest / f"h3-{label}.json", graph)
    save(dest / "h3-manifest.json", {**manifest, "source_b2": str(source), "run_names": names,
        "clothing_correction": {"before": old_japanese, "after": new_japanese},
        "subject_only_correction_verified": True, "original_emd_modified": False})
    print("Corrected pair ready; only shared Subject changed from B2", flush=True)


def prepare(args):
    from core.compiler import LlamaPromptTranslator, compile_ref2va
    from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
    from nodes.node_emd_compiler.node import _system_prompt
    from tools.debug_instrumental_p4 import verify_body_only_plan
    source, dest = args.source, args.output
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Use a new empty research destination")
    with urlopen(args.url + "/queue", timeout=30) as response:
        queue = json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; left intact")
    condition = read(source / "conditions.json")
    contract = read(source / "input-contract.json")
    previous = Path(condition["previous"])
    saved = read(source / "results.json")["results"][0]
    timed = read(source / "timed-results.json")["results"][0]
    if saved["label"] != "baseline" or timed["label"] != "timed":
        raise ValueError("Unexpected B1 lineage")
    dest.mkdir(parents=True)
    cache = {}
    for row in read(previous / "baseline-translation.json"):
        cache[tuple(row["fragments"])] = tuple(row["translated"])
    config = LlamaRuntimeConfig(**condition["runtime"])
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(condition["model"]), config)
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
            runtime_config=replace(config, temperature=0.0, max_tokens=4096))
        class CachedTranslator:
            def __init__(self):
                self.translation_trace = []
            def translate(self, units):
                key = tuple(units)
                self.reused = key in cache
                if not self.reused:
                    cache[key] = tuple(translator.translate(units))
                return cache[key]
            def record_field_translation(self, **kwargs):
                self.translation_trace.append({**kwargs, "reused_saved_translation": self.reused})
        plans, bodies = {}, {}
        for label, row in (("baseline", saved), ("timed", timed)):
            emd = replace_scene_prose((previous / "baseline.md").read_text(encoding="utf-8"),
                                     row["prose"], contract["camera"])
            (dest / f"{label}.md").write_text(emd, encoding="utf-8")
            cached = CachedTranslator()
            plan = compile_ref2va(emd, cached).plan
            for index, shot in enumerate(plan["shots"], 1):
                shot["seed"] = 20261003 + index
            body = next(r["restored"] for r in cached.translation_trace
                        if r["field_id"] == "scene.10.shot.0.body.1")
            if label == "timed" and not all(re.search(rf"\b{n}\b", body) for n in (3, 5)):
                raise ValueError("Translated local timing not preserved; inspect evidence")
            save(dest / f"{label}-translation.json", cached.translation_trace)
            save(dest / f"{label}-full-plan.json", plan)
            (dest / f"{label}-excerpt.md").write_text(
                f"# Scene 11\n\n* `演技` {row['prose']}\n* `カメラ` {contract['camera']}\n\n"
                f"## 実際の英訳\n\n{body}\n", encoding="utf-8")
            plans[label], bodies[label] = plan, body
        verify_body_only_plan(plans["baseline"], plans["timed"], 11, bodies["baseline"], bodies["timed"])
    finally:
        lifecycle.clear()
    start, end = condition["source_pcm_window_samples"]
    rate = condition["sample_rate"]
    requested = (end - start) // (rate // 24)
    if (end - start) % (rate // 24):
        raise ValueError("Content not on frame grid")
    frames, delivered, context = DEFAULT_H3_TIMING_PROFILE.quantize_delivered_frames(requested, first_scene=True)
    if context or frames != delivered:
        raise ValueError("Fresh clip unexpectedly needs context")
    names, audio = {}, []
    for stem, suffix in (("vocal", "vocal"), ("fullmix", "normalized")):
        path = Path(r"E:\OutputCollection\Momiji2") / f"千里の秋を駆ける_{suffix}.wav"
        name = f"mvd_beat_b2_momiji2_{stem}_s11_20261003.wav"
        target = Path(r"C:\Software\ComfyUI\input") / name
        if target.exists():
            raise ValueError("Do not overwrite PCM")
        subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-af",
            f"atrim=start_sample={start}:end_sample={end},asetpts=PTS-STARTPTS,apad=whole_len={frames*2000}",
            "-c:a", "pcm_f32le", str(target)], check=True)
        names[stem] = name
        audio.append({"source": str(path), "crop": str(target),
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    original = read(previous / "h3-baseline.json")
    for label in ("baseline", "timed"):
        plan = fresh_plan(plans[label], frames)
        save(dest / f"{label}-plan.json", plan)
        graph = deepcopy(original)
        run = f"beat-b2-momiji2-s11-{label}-20261003"
        for key in ("24", "37", "48"):
            graph[key]["inputs"]["plan_json"] = json.dumps(plan, ensure_ascii=False)
        graph["24"]["inputs"].update(run_name=run, default_steps=20)
        graph["21"]["inputs"]["filename"] = run
        graph["32"]["inputs"]["audio"] = names["fullmix"]
        graph["33"]["inputs"]["audio"] = names["vocal"]
        if graph["48"]["inputs"]["enable"] or graph["37"]["inputs"]["reference_alignment"] != "off":
            raise ValueError("Unexpected source clock processing")
        if graph["40"]["inputs"]["voice"] != ["48", 1] or graph["28"]["inputs"]["enabled"]:
            raise ValueError("Lip-sync route or review setting changed")
        save(dest / f"h3-{label}.json", graph)
    save(dest / "h3-manifest.json", {"source_b1": str(source), "source_graph": str(previous / "h3-baseline.json"),
        "source_start_sample": start, "source_end_sample": end, "sample_rate": rate,
        "content_frames": requested, "render_frames": frames, "tail_silence_samples": frames*2000-(end-start),
        "preroll_frames": 0, "clip_zero_equals_b1_scene_zero": True, "megapixels": 0.4, "steps": 20,
        "seed": 20261014, "audio": audio, "body_only_plan_verified": True,
        "comparison": "B1 baseline versus B1 timed instruction plus rhythm; not data-only causal test"})
    print(json.dumps({"prepared": True, "frames": frames, "content_frames": requested,
                      "baseline_english": bodies["baseline"], "timed_english": bodies["timed"]}, ensure_ascii=False), flush=True)


def finalize(args):
    import torch
    from tools.analyze_audio_activity import decode_audio
    dest = args.output
    manifest = read(dest / "h3-manifest.json")
    labels = manifest.get("comparison_labels", ["baseline", "timed"])
    if len(labels) != 2 or labels[0] != "baseline":
        raise ValueError("Expected baseline plus one candidate")
    checks, videos = [], {}
    fullmix_pcm = None
    for row in manifest["audio"]:
        original, rate, _ = decode_audio(Path(row["source"]), FFMPEG)
        crop, crop_rate, digest = decode_audio(Path(row["crop"]), FFMPEG)
        size = manifest["source_end_sample"] - manifest["source_start_sample"]
        equal = rate == crop_rate == manifest["sample_rate"] and torch.equal(
            original[..., manifest["source_start_sample"]:manifest["source_end_sample"]], crop[..., :size])
        if not equal or crop[..., size:].count_nonzero() or crop.shape[-1] != manifest["render_frames"]*2000:
            raise ValueError("PCM clock or tail padding mismatch")
        checks.append({"crop": row["crop"], "source_pcm_equal": equal, "tail_is_silence": True, "sha256": digest})
        if "fullmix" in Path(row["crop"]).name:
            fullmix_pcm = crop
    for label in labels:
        history = read(dest / f"render-{label}.json")
        if history["history"]["status"]["status_str"] != "success":
            raise ValueError("Render incomplete")
        run = manifest.get("run_names", {}).get(label, f"beat-b2-momiji2-s11-{label}-20261003")
        video = Path(r"C:\Software\ComfyUI\output\h3_chains") / run / "final" / f"{run}.mp4"
        probe = json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(video)], encoding="utf-8"))
        stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
        if (stream["width"], stream["height"], stream["r_frame_rate"], int(stream["nb_frames"])) != (864,480,"24/1",manifest["render_frames"]):
            raise ValueError("Video clock changed")
        delivered_audio, delivered_rate, _ = decode_audio(video, FFMPEG)
        audio_match = None
        if fullmix_pcm is not None and delivered_rate == manifest["sample_rate"]:
            n = min(fullmix_pcm.shape[-1], delivered_audio.shape[-1])
            expected = fullmix_pcm.mean(dim=1)[..., :n].reshape(-1)
            actual = delivered_audio.mean(dim=1)[..., :n].reshape(-1)
            audio_match = float(torch.nn.functional.cosine_similarity(expected, actual, dim=0))
        videos[label] = {"path": str(video), "streams": probe["streams"], "render_wait_s": history["elapsed_s"],
                         "render_audio_zero_offset_fullmix_cosine": audio_match}
    target = dest / "comparison.mp4"
    if target.exists():
        raise ValueError("Comparison already exists")
    filters = []
    titles = manifest.get("comparison_titles", ["Baseline", "Rhythm + Timed Performance"])
    if len(titles) != 2 or any(not re.fullmatch(r"[A-Za-z0-9 +_-]+", t) for t in titles):
        raise ValueError("Unexpected comparison titles")
    for index, (label, title) in enumerate(zip(labels, titles)):
        filters.append(f"[{index}:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='{title}':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[{label}]")
    filters.append(f"[{labels[0]}][{labels[1]}]vstack[v]")
    subprocess.run([FFMPEG, "-v", "error", "-i", videos[labels[0]]["path"], "-i", videos[labels[1]]["path"],
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264",
        "-crf", "18", "-preset", "fast", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(target)], check=True)
    sheet = dest / "contact-sheet.png"
    if sheet.exists():
        raise ValueError("Contact sheet already exists")
    subprocess.run([FFMPEG, "-v", "error", "-i", str(target), "-vf",
        "fps=1,scale=432:480,tile=5x2", "-frames:v", "1", str(sheet)], check=True)
    save(dest / "media-checks.json", {"videos": videos, "pcm_checks": checks, "comparison": str(target)})
    print(str(target), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "repair-clothing", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--label", choices=("baseline", "timed"))
    p.add_argument("--url", default="http://127.0.0.1:8191")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "render":
        from tools.prepare_instrumental_h3 import render
        if not args.label:
            p.error("render requires --label")
        render(args.output, args.label, args.url)
    elif args.task in ("prepare", "repair-clothing"):
        if not args.source:
            p.error("prepare requires --source")
        (prepare if args.task == "prepare" else repair_clothing)(args)
    else:
        finalize(args)
