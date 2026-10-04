"""Full-song research run using ordinary Scene Author and Compiler APIs.

No placeholder prose, saved LLM replies, partial PCM, or natural-language patch.
The H3 submission is nonblocking: the server owns the 30-Scene queue afterwards.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import shutil
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import DirectionArtifact
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.direction.enhancer import split_staging_directives
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.api import generate_planner_content, render_planner_content
from core.planner.template import parse_template_emd
from core.planner.types import PlannerContent
from nodes.node_emd_compiler.node import _system_prompt
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _planner_transport_policy, _system_prompts
from tools.analyze_audio_activity import decode_audio
from tools.debug_simple_dance import MOMENTUM_JAPANESE
from tools.debug_instrumental_camera_candidate import USER_REQUEST as CAMERA_CANDIDATE
from tools.prepare_beat_motion_h3 import FFMPEG, FFPROBE, read, save

RUN_NAME = "instrumental-full-momiji2-20261004"
ASSETS = Path(r"E:\ComfyUI\projects\ComfyUI-MV-Director-research\docs\assets\research")
ALIGNMENT = ASSETS / "instrumental-staging-p2-momiji2-2026-10-03" / "alignment"
REFERENCE_PROBE = ASSETS / "instrumental-camera-b25-momiji2-2026-10-04"
USER_REQUEST = ("# 演出候補\n* 歌声のない長い伴奏が続く場面で、" + MOMENTUM_JAPANESE + "\n"
    + CAMERA_CANDIDATE.split("# 演出候補\n", 1)[1]
    + "* 歌唱へ戻る場面で、目を閉じて身体の流れと呼吸を溜め、歌声が始まると目を開き、顔を上げて視線を結び、入力ボーカルに合わせて歌う。流れていた手を胸前で受け止め、伴奏中の身体の流れを歌唱の呼吸へ渡す。\n"
    + "* 歌声のない長い伴奏を滝の近くで見せる場面で、滝の水が岩に砕け、白い水しぶきが舞い上がる。人物の身体の回転と袖の流れに細かな水滴と紅葉が重なり、水滴が光を受けてきらめく。\n")


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_full_content(content, template):
    expected = set(template.shot_keys)
    for kind in ("actions", "cameras"):
        rows = getattr(content, kind)
        if len(rows) != len(expected) or {r[:2] for r in rows} != expected:
            raise ValueError(f"Incomplete/duplicate full-song {kind}")
        if any(not r[2].strip() or "検証対象外" in r[2] for r in rows):
            raise ValueError(f"Placeholder or empty {kind}; do not render")
    # The ordinary Planner intentionally omits EVENT=なし records.
    event_keys = [r[:2] for r in content.events]
    if len(event_keys) != len(set(event_keys)) or not set(event_keys).issubset(expected):
        raise ValueError("Duplicate or unknown full-song events")
    if any(not r[2].strip() or "検証対象外" in r[2] for r in content.events):
        raise ValueError("Placeholder or empty events; do not render")
    if content.motion_compositions:
        raise ValueError("No mechanical motion composition was requested")


def verify_plan(plan, template):
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
    shots = plan["shots"]
    if len(shots) != len(template.scenes):
        raise ValueError("Full-song Scene count changed")
    frames = 0
    for index, (row, scene) in enumerate(zip(shots, template.scenes)):
        context = DEFAULT_H3_TIMING_PROFILE.continuation_context_length if index and scene.continuation else 0
        audio_context = DEFAULT_H3_TIMING_PROFILE.audio_context_length if context else 0
        if (row["id"], row["length"], row["context_length"], row["audio_context_length"]) != (
                f"scene_{scene.scene_number:04d}", scene.h3_length, context, audio_context):
            raise ValueError("Compiler changed full-song timing")
        if row.get("source_audio_target") != "locked":
            raise ValueError("Standard vocal target missing")
        if any("検証対象外" in line for line in row["prompt"]):
            raise ValueError("Partial-probe placeholder detected")
        frames += row["length"] - context
    if frames != round(template.scenes[-1].end_ms * 24 / 1000):
        raise ValueError("Delivered Plan frames do not match Template end")
    return frames


def prepare(output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty research output; never replace prior evidence")
    run = Path(r"C:\Software\ComfyUI\output\h3_chains") / RUN_NAME
    if run.exists():
        raise ValueError("Full run already exists; do not replace")
    summary = read(ALIGNMENT / "alignment-summary.json")
    provenance = read(ALIGNMENT.parent / "input" / "provenance.json")
    if fingerprint(Path(provenance["original"])) != provenance["original_sha256"]:
        raise ValueError("Original lyrics changed since alignment")
    template_text = (ALIGNMENT / "template.md").read_text(encoding="utf-8")
    template = parse_template_emd(template_text)
    if len(template.scenes) != 30 or template.audio_activity is None:
        raise ValueError("Expected full 30-Scene activity Template")
    for scene in template.scenes:
        if scene.audio_directives or any(q.directives for q in scene.shots):
            raise ValueError("Use original unplanned Template, not completed partial probe")
    reference = read(REFERENCE_PROBE / "reference-contract.json")
    if fingerprint(Path(reference["input_snapshot"])) != reference["sha256"]:
        raise ValueError("Reference snapshot changed")
    if fingerprint(Path(reference["source"])) != reference["sha256"]:
        raise ValueError("Author reference changed; prepare an updated snapshot first")
    text = (REFERENCE_PROBE / "dance.md").read_text(encoding="utf-8")
    concept = text.split("\n# シーン設定", 1)[0].strip() + "\n"
    scene_emd = "# シーン設定" + text.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
    common = parse_emd(text).common_prompt_dict()
    common_request, candidates = split_staging_directives(USER_REQUEST)
    if common_request or len(candidates) != 4:
        raise ValueError("Expected four optional staging candidates")
    direction = DirectionArtifact(environment_direction=common.get("環境", ()),
        motion_direction=common.get("モーション", ()), motion_profile_id="anime_scene_author_mv",
        motion_templates=(), staging_candidates=candidates)
    # CPU decode proves the saved energy/Whisper analysis is still applicable.
    audio = []
    for stem in ("vocal", "fullmix"):
        source = Path(summary[stem])
        wave, rate, digest = decode_audio(source, FFMPEG)
        if rate != 48000 or wave.shape[-1] not in (13017600, 13017599) or digest != summary[f"{stem}_sha256"]:
            raise ValueError("Aligned source PCM changed")
        target = Path(r"C:\Software\ComfyUI\input") / f"mvd_instrumental_full_momiji2_{stem}_20261004.wav"
        if target.exists() and fingerprint(target) != fingerprint(source):
            raise ValueError("Input snapshot collision; do not overwrite")
        if not target.exists():
            shutil.copy2(source, target)
        audio.append({"stem": stem, "source": str(source), "input": str(target),
                      "pcm_sha256": digest, "file_sha256": fingerprint(target),
                      "source_samples": wave.shape[-1]})
    output.mkdir(parents=True)
    for name, value in (("template.md", template_text), ("concept.md", concept),
                        ("scene.md", scene_emd), ("user-request.md", USER_REQUEST)):
        (output / name).write_text(value, encoding="utf-8")
    save(output / "direction.json", direction.to_dict())
    prompts = _system_prompts()
    save(output / "system-prompts.json", prompts)
    conditions = read(REFERENCE_PROBE / "conditions.json")
    save(output / "conditions.json", {"model": conditions["model"], "runtime": conditions["runtime"],
        "compiler_max_tokens": 4096, "alignment": str(ALIGNMENT), "run_name": RUN_NAME,
        "staging_candidate_policy": "optional", "lip_sync_mode": "context_loop",
        "scene_count": len(template.scenes), "shot_count": len(template.shot_keys),
        "audio": audio, "reference": reference, "reference_emd_reused": True,
        "enhancer_vision_rerun": False, "all_event_performance_camera_regenerated": True,
        "semantic_prose_repair": False, "mechanical_motion_composition": False,
        "system_prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k,v in prompts.items()},
        "compiler_prompt_sha256": hashlib.sha256(_system_prompt().encode()).hexdigest(),
        "h3_source_graph": str(REFERENCE_PROBE / "h3-dance.json"),
        "megapixels": 0.4, "steps": 20, "turbo_lora": False, "review_gate": False})
    print(f"CPU prepared: {len(template.scenes)} Scenes / {len(template.shot_keys)} Shots", flush=True)


def infer(output, url, *, resume_compile=False):
    if resume_compile:
        if not (output / "inference.json").exists() or (output / "translation-live.json").exists():
            raise ValueError("Resume only complete saved Planner before translation starts")
    elif (output / "inference.json").exists() or (output / "planner-live.json").exists():
        raise ValueError("Inference already attempted; no silent overwrite")
    with urlopen(url + "/queue", timeout=30) as r:
        queue = json.load(r)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; existing jobs left intact")
    conditions = read(output / "conditions.json")
    config = LlamaRuntimeConfig(**conditions["runtime"])
    prompts = read(output / "system-prompts.json")
    if {k: hashlib.sha256(v.encode()).hexdigest() for k,v in prompts.items()} != conditions["system_prompt_sha256"]:
        raise ValueError("Prepared prompts changed")
    template = parse_template_emd((output / "template.md").read_text(encoding="utf-8"))
    direction = DirectionArtifact.from_dict(read(output / "direction.json"))
    concept, scene_emd = [(output / n).read_text(encoding="utf-8") for n in ("concept.md", "scene.md")]
    class TracedBackend(_LlamaPlannerBackend):
        def complete_planner(self, **kwargs):
            value = super().complete_planner(**kwargs)
            request = json.loads(kwargs["payload"])
            save(output / "planner-live.json", {"trace": self.trace, "last_scene": request["scene_number"],
                "last_task": kwargs["task"], "elapsed_s": time.perf_counter()-started})
            print(f"Scene {request['scene_number']}/{len(template.scenes)} {kwargs['task']} finished", flush=True)
            return value
    lifecycle = LlamaCppLifecycle()
    try:
        load_started = time.perf_counter()
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        print(f"31B loaded: {time.perf_counter()-load_started:.2f}s", flush=True)
        backend = TracedBackend(lifecycle)
        backend.transport_policy = _planner_transport_policy(conditions["model"])
        started = time.perf_counter()
        if resume_compile:
            saved = read(output / "inference.json")
            content = PlannerContent.from_dict(saved["content"])
            missing = saved["missing"]
            covered = {(json.loads(row["payload"])["scene_number"], row["task"])
                       for row in saved["trace"]}
            required = {(s.scene_number, task) for s in template.scenes for task in
                        ("scene-author-event", "scene-author-performance", "scene-author-camera")}
            if not required.issubset(covered):
                raise ValueError("Saved Planner trace does not cover every Scene and task")
            print("Complete saved Planner retained; resuming fresh Compiler only", flush=True)
        else:
            content, missing = generate_planner_content(backend, template=template, concept_emd=concept,
                scene_emd=scene_emd, direction=direction, lip_sync_mode="context_loop",
                lip_sync_target="サブジェクト1", system_prompts=prompts, runtime_config=config,
                staging_candidate_policy="optional")
            save(output / "inference.json", {"content": content.to_dict() if content else None, "missing": missing,
                "trace": backend.trace, "elapsed_s": time.perf_counter()-started})
        if content is None or missing:
            raise ValueError(f"Full Planner incomplete; do not render: {missing}")
        assert_full_content(content, template)
        emd = render_planner_content(content=content, concept_emd=concept, scene_emd=scene_emd,
            template=template, direction=direction, lip_sync_mode="context_loop",
            lip_sync_target="サブジェクト1", lip_sync_audio_slot=1)
        (output / "full-emd.md").write_text(emd.text, encoding="utf-8")
        if hashlib.sha256(_system_prompt().encode()).hexdigest() != conditions["compiler_prompt_sha256"]:
            raise ValueError("Compiler prompt changed")
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
            runtime_config=replace(config, max_tokens=4096, temperature=0.0))
        class TracedTranslator:
            def __init__(self):
                self.translation_trace = []
            def translate(self, units):
                return translator.translate(units)
            def record_field_translation(self, **kwargs):
                self.translation_trace.append(kwargs)
                save(output / "translation-live.json", self.translation_trace)
                print(f"Compiler {kwargs['field_id']} completed", flush=True)
        traced = TracedTranslator()
        started = time.perf_counter()
        compiled = compile_ref2va(emd.text, traced)
        save(output / "translation.json", traced.translation_trace)
        save(output / "compiler-inference.json", {"elapsed_s": time.perf_counter()-started,
            "field_count": len(traced.translation_trace), "trace": translator.translation_trace})
        frames = verify_plan(compiled.plan, template)
        for index, shot in enumerate(compiled.plan["shots"], 1):
            shot["seed"] = 20261003 + index
        save(output / "plan.json", compiled.plan)
        graph = read(Path(conditions["h3_source_graph"]))
        for k in ("24", "37", "48"):
            graph[k]["inputs"]["plan_json"] = json.dumps(compiled.plan, ensure_ascii=False)
        graph["24"]["inputs"].update(run_name=RUN_NAME, default_steps=20)
        graph["21"]["inputs"]["filename"] = RUN_NAME
        for k in ("7", "29"):
            graph[k]["inputs"].update(start_clip=1, scene_range="")
        graph["48"]["inputs"].update(enable=False, scene_start=1, scene_length=30)
        graph["37"]["inputs"]["reference_alignment"] = "off"
        for k, stem in (("32", "fullmix"), ("33", "vocal")):
            graph[k]["inputs"]["audio"] = Path(next(r["input"] for r in conditions["audio"] if r["stem"] == stem)).name
        if graph["40"]["inputs"]["voice"] != ["48", 1] or graph["28"]["inputs"]["enabled"] or "44" in graph:
            raise ValueError("Lip-sync/ReviewGate/Turbo route changed")
        save(output / "h3-full.json", graph)
        save(output / "full-summary.json", {"scenes": len(template.scenes), "shots": len(template.shot_keys),
            "frames": frames, "duration_s": frames/24, "all_generated_fields_present": True,
            "source_samples": template.audio_activity.source_samples, "target_samples": frames*2000,
            "vocal_tail_silence_samples": frames*2000-template.audio_activity.source_samples,
            "inter_scene_audio_insertion": False, "standard_context_loop_lip_sync": True,
            "candidate_adoption": "optional; semantic review required", "video_generated": False})
        print(f"Plan ready: {frames} frames / {frames/24:.3f}s; inspect before submit", flush=True)
    finally:
        lifecycle.clear()


def submit(output, url):
    if (output / "submission-full.json").exists():
        raise ValueError("Already submitted; do not duplicate the full run")
    conditions = read(output / "conditions.json")
    template = parse_template_emd((output / "template.md").read_text(encoding="utf-8"))
    verify_plan(read(output / "plan.json"), template)
    with urlopen(url + "/queue", timeout=30) as r:
        queue = json.load(r)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; jobs unchanged")
    run = Path(r"C:\Software\ComfyUI\output\h3_chains") / RUN_NAME
    if run.exists():
        raise ValueError("Run exists; inspect it instead of overwriting")
    graph = read(output / "h3-full.json")
    if graph["24"]["inputs"]["run_name"] != RUN_NAME:
        raise ValueError("Run name changed")
    for row in conditions["audio"]:
        if fingerprint(Path(row["input"])) != row["file_sha256"]:
            raise ValueError("Input audio snapshot changed")
    ref = conditions["reference"]
    if fingerprint(Path(ref["input_snapshot"])) != ref["sha256"]:
        raise ValueError("Reference changed")
    request = Request(url+"/prompt", data=json.dumps({"prompt": graph}).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=60) as r:
        result = json.load(r)
    save(output / "submission-full.json", {**result, "run_name": RUN_NAME,
        "expected_final": str(run / "final" / (RUN_NAME + ".mp4")), "server_owns_queue": True})
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "infer", "resume-compile", "submit"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "prepare":
        prepare(args.output.resolve())
    elif args.task == "resume-compile":
        infer(args.output.resolve(strict=True), args.url, resume_compile=True)
    else:
        {"infer": infer, "submit": submit}[args.task](args.output.resolve(strict=True), args.url)
