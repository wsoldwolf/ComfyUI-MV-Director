"""Opt-in P3: saved translations and Shot prose, explicit timed mouth only.

All evidence/media is written to the specified external research directory.
The original full EMD/Plan and ComfyUI output runs are never overwritten.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.compiler import compile_ref2va
from core.emd import parse_emd
from core.planner.mouth_performance import plan_mouth_performances
from core.planner.renderer import format_emd_time
from core.planner.template import parse_template_emd
from tools.prepare_instrumental_h3 import render
from tools.analyze_audio_activity import decode_audio


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(source: Path, output: Path, *, scene_start=12, scene_length=2,
            run_prefix="mouth-p3-momiji2"):
    if (output / "conditions.json").exists():
        raise ValueError("Evidence exists; do not overwrite a prepared comparison")
    output.mkdir(parents=True, exist_ok=True)
    original_text = (source / "full-emd.md").read_text(encoding="utf-8")
    original_plan = json.loads((source / "plan.json").read_text(encoding="utf-8"))
    template = parse_template_emd((source / "template.md").read_text(encoding="utf-8"))
    original_doc = parse_emd(original_text)
    policy = plan_mouth_performances(template, lip_sync_mode="context_loop",
        lip_sync_target="サブジェクト1", subject_count=len(original_doc.subjects))
    if not 1 <= scene_start <= len(template.scenes) or not 1 <= scene_length <= len(template.scenes)-scene_start+1:
        raise ValueError("Selected Scene range is outside the saved Template")
    if not run_prefix or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in run_prefix):
        raise ValueError("Use a simple lowercase run prefix")
    targets = tuple(range(scene_start,scene_start+scene_length))
    selected = [s for s in template.scenes if s.scene_number in targets]
    if len(selected) != scene_length or any(s.mouth_performances for s in original_doc.scenes):
        raise ValueError("Expected target Scenes and an unannotated saved baseline")
    parts = original_text.split("> `シーン` ")
    annotated = [parts[0]]
    for part in parts[1:]:
        number = int(part.split("\n", 1)[0])
        if number in targets:
            first_shot = part.index("## ショット ")
            annotations = "".join(
                f"> `口元` `{i.target_concept_id}` {format_emd_time(i.start_ms)} --> "
                f"{format_emd_time(i.end_ms)} `{i.state}`\n" for i in policy[number])
            part = part[:first_shot] + annotations + part[first_shot:]
        annotated.append("> `シーン` " + part)
    annotated_text = "".join(annotated)
    parsed = parse_emd(annotated_text)
    for a, b in zip(original_doc.scenes, parsed.scenes):
        if (a.shots, a.descriptions, a.audio_directives, a.start_ms, a.end_ms,
            a.h3_length, a.continuation) != (b.shots, b.descriptions, b.audio_directives,
            b.start_ms, b.end_ms, b.h3_length, b.continuation):
            # Parser source line numbers change when annotations are inserted.
            def fields(s):
                return ([(i.start_ms, i.body, [(l.section,l.text,l.start_ms,l.end_ms)
                         for l in i.lyric_annotations], i.lyric_lip_sync,
                         [(d.kind,d.text) for d in i.directives]) for i in s.shots],
                        s.descriptions, [(d.mode,d.target_concept_id,d.audio_slot)
                        for d in s.audio_directives], s.start_ms,s.end_ms,s.h3_length,s.continuation)
            if fields(a) != fields(b):
                raise ValueError("Author prose or Scene clock changed")
    cache = {}
    for row in json.loads((source / "translation.json").read_text(encoding="utf-8")):
        key, value = tuple(row["fragments"]), tuple(row["translated"])
        if key in cache and cache[key] != value:
            raise ValueError("Saved translations conflict")
        cache[key] = value

    class SavedTranslator:
        def translate(self, units):
            key = tuple(units)
            if key not in cache:
                raise ValueError("A new translation would invalidate the mouth-only comparison")
            return cache[key]

    baseline = compile_ref2va(original_text, SavedTranslator()).plan
    candidate = compile_ref2va(annotated_text, SavedTranslator()).plan
    for a, b, saved in zip(baseline["shots"], candidate["shots"], original_plan["shots"]):
        a["seed"] = b["seed"] = saved["seed"]
    if baseline != original_plan:
        raise ValueError("Current baseline compilation differs from the saved Plan")
    if {k:v for k,v in baseline.items() if k != "shots"} != {
        k:v for k,v in candidate.items() if k != "shots"}:
        raise ValueError("Global Plan settings changed")
    for index, (a,b) in enumerate(zip(baseline["shots"], candidate["shots"]),1):
        if index not in targets and a != b:
            raise ValueError("A non-target Scene changed")
        if {k:v for k,v in a.items() if k != "prompt"} != {
            k:v for k,v in b.items() if k != "prompt"}:
            raise ValueError("A non-prompt generation property changed")
    (output / "baseline.md").write_text(original_text, encoding="utf-8")
    (output / "mouth.md").write_text(annotated_text, encoding="utf-8")
    save(output / "baseline-plan.json", baseline)
    save(output / "mouth-plan.json", candidate)
    # The first isolated clip has no visual prefix, so include actual source
    # pre-roll to keep the following clip on its original delivered PCM clock.
    start = targets[0]-1
    prefix_frames = baseline["shots"][start].get("context_length",0)
    skip_frames = sum(s["length"]-s.get("context_length",0) for s in baseline["shots"][:start])
    render_frames = prefix_frames + sum(s["length"]-s.get("context_length",0)
                                      for s in baseline["shots"][start:start+scene_length])
    source_start = (skip_frames-prefix_frames)*2000
    source_end = source_start+render_frames*2000
    if source_start < 0:
        raise ValueError("Source pre-roll unavailable")
    graph = json.loads((source / "h3-full.json").read_text(encoding="utf-8"))
    evidence = []
    import torch
    for node_id, stem in (("32","fullmix"),("33","vocal")):
        original_audio = Path(r"C:\Software\ComfyUI\input") / graph[node_id]["inputs"]["audio"]
        target = original_audio.parent / f"mvd_{run_prefix}_{stem}_20261005.wav"
        if target.exists():
            raise ValueError(f"Input collision: {target}")
        subprocess.run([r"C:\Software\ffmpeg\bin\ffmpeg.exe","-v","error","-i",
            str(original_audio),"-af",f"atrim=start_sample={source_start}:end_sample={source_end},asetpts=PTS-STARTPTS",
            "-c:a","pcm_f32le",str(target)],check=True)
        source_pcm, source_rate, _ = decode_audio(original_audio,r"C:\Software\ffmpeg\bin\ffmpeg.exe")
        cropped_pcm, crop_rate, crop_digest = decode_audio(target,r"C:\Software\ffmpeg\bin\ffmpeg.exe")
        if source_rate != 48000 or crop_rate != 48000 or not torch.equal(
            source_pcm[...,source_start:source_end],cropped_pcm):
            raise ValueError("Cropped PCM differs from the exact source samples")
        graph[node_id]["inputs"]["audio"] = target.name
        evidence.append({"source":str(original_audio),"crop":str(target),
            "sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
            "pcm_sha256":crop_digest,"source_pcm_equal":True})
    for label, plan in (("baseline",baseline),("mouth",candidate)):
        current = deepcopy(graph)
        sliced = {**plan,"shots":plan["shots"][start:start+scene_length]}
        text = json.dumps(sliced,ensure_ascii=False)
        for node_id in ("24","37","48"):
            current[node_id]["inputs"]["plan_json"] = text
        name = f"{run_prefix}-{label}-20261005"
        current["24"]["inputs"].update(run_name=name,default_steps=20)
        current["21"]["inputs"]["filename"] = name
        current["48"]["inputs"].update(enable=False,scene_start=1,scene_length=scene_length)
        current["37"]["inputs"].pop("timeline",None)
        current["7"]["inputs"].update(start_clip=1,scene_range="")
        current["29"]["inputs"].update(start_clip=1,scene_range="")
        current["28"]["inputs"]["enabled"] = False
        if current["40"]["inputs"]["voice"] != ["48",1]:
            raise ValueError("Standard Context Loop vocal wiring changed")
        save(output / f"h3-{label}.json",current)
    voices=template.audio_activity.scene_payload(start_ms=selected[0].start_ms,
        end_ms=selected[-1].end_ms,audio_mode="context_loop")["intervals"]
    first_voice=next((i["start_ms"]/1000-source_start/48000
                      for i in voices if i["state"]=="vocal_candidate"),None)
    save(output / "conditions.json",{
        "source":str(source),"scene_numbers":targets,"mouth_policy_from_saved_template":True,
        "run_prefix":run_prefix,
        "fixed_authored_diagnostic":True,"planner_rerun":False,"new_translation_calls":0,
        "all_original_prose_and_translation_preserved":True,"full_baseline_plan_exactly_reproduced":True,
        "sample_rate":48000,"source_start_sample":source_start,"source_end_sample":source_end,
        "source_start_s":source_start/48000,"raw_render_frames":render_frames,
        "first_isolated_preroll_frames":prefix_frames,"expected_singing_s":first_voice,
        "audio":evidence,"mouth_intervals":{
            str(n):[[i.start_ms,i.end_ms,i.state] for i in policy[n]] for n in targets},
        "megapixels":0.4,"steps":20,"context_loop_lip_sync":True,"review_gate":False,
        "turbo_lora":False,"seed":[s["seed"] for s in baseline["shots"][start:start+scene_length]],
    })
    print("Prepared mouth-only graphs; saved baseline Plan reproduced exactly",flush=True)


def verify(output: Path, url: str):
    """Non-mutating verification against the running node schema and PCM."""
    with urlopen(url+"/object_info",timeout=60) as response:
        schema=json.load(response)
    for label in ("baseline","mouth"):
        graph=json.loads((output/f"h3-{label}.json").read_text(encoding="utf-8"))
        for node in graph.values():
            info=schema[node["class_type"]]
            required=info["input"].get("required",{})
            if set(required)-set(node["inputs"]):
                raise ValueError(f"Missing inputs: {node['class_type']}")
            for key,value in node["inputs"].items():
                spec=required.get(key,info["input"].get("optional",{}).get(key))
                if spec and isinstance(spec[0],list) and value not in spec[0]:
                    raise ValueError(f"Invalid combo: {node['class_type']}.{key}={value}")
    conditions=json.loads((output/"conditions.json").read_text(encoding="utf-8"))
    import torch
    rows=[]
    for row in conditions["audio"]:
        source,rate,_=decode_audio(Path(row["source"]),r"C:\Software\ffmpeg\bin\ffmpeg.exe")
        crop,crop_rate,digest=decode_audio(Path(row["crop"]),r"C:\Software\ffmpeg\bin\ffmpeg.exe")
        if not (rate==crop_rate==48000 and torch.equal(
            source[...,conditions["source_start_sample"]:conditions["source_end_sample"]],crop)):
            raise ValueError("Cropped PCM verification failed")
        rows.append({"crop":row["crop"],"pcm_sha256":digest,"source_pcm_equal":True,
                     "samples":crop.shape[-1]})
    save(output/"preflight-verification.json",{"live_schema_valid":True,"audio":rows})
    print("Live schema valid; both crops match source PCM exactly",flush=True)


def finalize(output: Path):
    conditions=json.loads((output/"conditions.json").read_text(encoding="utf-8"))
    videos=[]
    checks={}
    ffmpeg=r"C:\Software\ffmpeg\bin\ffmpeg.exe"
    for label in ("baseline","mouth"):
        history=json.loads((output/f"render-{label}.json").read_text(encoding="utf-8"))
        if history["history"]["status"]["status_str"]!="success":
            raise ValueError("Both videos must finish before comparison")
        prefix=conditions.get("run_prefix","mouth-p3-momiji2")
        run=Path(r"C:\Software\ComfyUI\output\h3_chains")/f"{prefix}-{label}-20261005"
        files=list((run/"final").glob("*.mp4"))
        if len(files)!=1:
            raise ValueError("Expected one final video")
        video=files[0]
        probe=json.loads(subprocess.check_output([r"C:\Software\ffmpeg\bin\ffprobe.exe",
            "-v","error","-show_entries","stream=codec_type,width,height,r_frame_rate,nb_frames,duration",
            "-of","json",str(video)],encoding="utf-8"))
        stream=next(i for i in probe["streams"] if i["codec_type"]=="video")
        if (stream["width"],stream["height"],int(stream["nb_frames"]))!=(864,480,conditions["raw_render_frames"]):
            raise ValueError("Video size or audio clock changed")
        checks[label]={"video":str(video),"streams":probe["streams"],"elapsed_s":history["elapsed_s"]}
        videos.append(video)
    target=output/"comparison.mp4"
    if target.exists():
        raise ValueError("Do not overwrite comparison media")
    subprocess.run([ffmpeg,"-v","error","-i",str(videos[0]),"-i",str(videos[1]),
        "-filter_complex",
        "[0:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='Baseline':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[t];"
        "[1:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='Timed mouth plan':x=16:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7[b];[t][b]vstack[v]",
        "-map","[v]","-map","0:a:0","-c:v","libx264","-crf","18","-preset","fast",
        "-c:a","aac","-b:a","256k","-movflags","+faststart",str(target)],check=True)
    checks["comparison_video"]=str(target)
    checks["expected_vocal_return_s"]=conditions["expected_singing_s"]
    save(output/"media-checks.json",checks)
    for label in ("baseline","mouth"):
        parts=(output/f"{label}.md").read_text(encoding="utf-8").split("> `シーン` ")
        excerpt="\n".join("> `シーン` "+part for part in parts[1:]
                          if int(part.split("\n",1)[0]) in conditions["scene_numbers"])
        (output/f"{label}-excerpt.md").write_text(excerpt,encoding="utf-8")
    print(json.dumps(checks,ensure_ascii=False),flush=True)


def infer(source: Path, output: Path, url: str):
    """Check two actual Planner Scenes separately from the fixed-video pair."""
    from dataclasses import replace
    from core.artifacts import DirectionArtifact
    from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
    from core.planner.api import generate_planner_content, render_planner_content
    from core.planner.section_context import section_context_by_scene
    from core.planner.template import PlannerTemplate
    from core.planner.types import PlannerContent
    from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy

    prepared=json.loads((output/"conditions.json").read_text(encoding="utf-8"))
    if prepared["scene_numbers"] != [12,13]:
        raise ValueError("The live Planner probe currently supports the Scene 12-13 pair only")
    if (output/"planner-live.json").exists() or (output/"planner-inference.json").exists():
        raise ValueError("Do not overwrite an inference attempt")
    with urlopen(url+"/queue",timeout=30) as response:
        queue=json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI busy; existing jobs left intact")
    with urlopen(Request(url+"/free",data=b'{"unload_models":true,"free_memory":true}',
                        headers={"Content-Type":"application/json"}),timeout=30):
        pass
    # The idle Comfy worker services the model-release flags asynchronously.
    time.sleep(3)
    conditions=json.loads((source/"conditions.json").read_text(encoding="utf-8"))
    config=LlamaRuntimeConfig(**conditions["runtime"])
    full_template=parse_template_emd((source/"template.md").read_text(encoding="utf-8"))
    selected=PlannerTemplate(tuple(s for s in full_template.scenes if s.scene_number in (11,12,13)),
                             full_template.audio_activity)
    contexts=section_context_by_scene(full_template)
    old=json.loads((source/"inference.json").read_text(encoding="utf-8"))
    replay={}
    for row in old["trace"]:
        request=json.loads(row["payload"]) if isinstance(row["payload"],str) else row["payload"]
        if request["scene_number"]==11 and not request.get("retry"):
            replay[row["task"]]=row["response"]
    if len(replay)!=3:
        raise ValueError("Saved three-role predecessor incomplete")
    lifecycle=LlamaCppLifecycle()
    started=time.perf_counter()

    class Backend(_LlamaPlannerBackend):
        def complete_planner(self,*,task,payload,**kwargs):
            request=json.loads(payload)
            request["section_lyric_context"]=contexts[request["scene_number"]]
            if request["scene_number"]==11:
                self._task_calls[task]=self._task_calls.get(task,0)+1
                self._primary_calls[task]=self._primary_calls.get(task,0)+1
                self.trace.append({"task":task,"payload":request,"response":replay[task],
                                   "replayed_predecessor_only":True})
                return replay[task]
            response=super().complete_planner(task=task,payload=json.dumps(request,ensure_ascii=False),**kwargs)
            save(output/"planner-live.json",{"trace":self.trace,"elapsed_s":time.perf_counter()-started})
            print(f"Scene {request['scene_number']} {task} finished",flush=True)
            return response

    try:
        lifecycle.ensure_loaded(Path(conditions["model"]),config)
        print(f"31B loaded; elapsed={time.perf_counter()-started:.1f}s",flush=True)
        backend=Backend(lifecycle)
        backend.transport_policy=_planner_transport_policy(conditions["model"])
        prompts=_system_prompts()
        save(output/"planner-system-prompts.json",prompts)
        content,missing=generate_planner_content(backend,template=selected,
            concept_emd=(source/"concept.md").read_text(encoding="utf-8"),
            scene_emd=(source/"scene.md").read_text(encoding="utf-8"),
            direction=DirectionArtifact.from_dict(json.loads((source/"direction.json").read_text(encoding="utf-8"))),
            lip_sync_mode="context_loop",lip_sync_target="サブジェクト1",
            system_prompts=prompts,runtime_config=config,staging_candidate_policy="optional")
        save(output/"planner-inference.json",{"content":content.to_dict() if content else None,
            "missing":missing,"trace":backend.trace,"elapsed_s":time.perf_counter()-started,
            "model":conditions["model"],"runtime":conditions["runtime"],
            "live_scenes":[12,13],"replayed_predecessor_scene":11,"new_video_generated":False})
        if content is None or missing:
            raise ValueError(f"Planner probe incomplete: {missing}")
        original=PlannerContent.from_dict(old["content"])
        def merged(key):
            return tuple(r for r in getattr(original,key) if r[0] not in (12,13))+tuple(
                r for r in getattr(content,key) if r[0] in (12,13))
        combined=replace(original,actions=merged("actions"),cameras=merged("cameras"),events=merged("events"),
            terminal_states=merged("terminal_states"),motion_compositions=merged("motion_compositions"),
            mouth_performances=tuple(r for r in content.mouth_performances if r[0] in (12,13)))
        emd=render_planner_content(content=combined,concept_emd=(source/"concept.md").read_text(encoding="utf-8"),
            scene_emd=(source/"scene.md").read_text(encoding="utf-8"),template=full_template,
            direction=DirectionArtifact.from_dict(json.loads((source/"direction.json").read_text(encoding="utf-8"))),
            lip_sync_mode="context_loop",lip_sync_target="サブジェクト1",lip_sync_audio_slot=1)
        parse_emd(emd.text)
        (output/"planner-probe.md").write_text(emd.text,encoding="utf-8")
        excerpt="\n".join("> `シーン` "+part for part in emd.text.split("> `シーン` ")[1:]
                          if int(part.split("\n",1)[0]) in (12,13))
        (output/"planner-probe-excerpt.md").write_text(excerpt,encoding="utf-8")
        print("Actual Planner probe completed; V3 annotations retained; no additional video",flush=True)
    finally:
        lifecycle.clear()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--render",choices=("baseline","mouth"))
    p.add_argument("--verify",action="store_true")
    p.add_argument("--finalize",action="store_true")
    p.add_argument("--infer",action="store_true")
    p.add_argument("--scene",type=int,default=12)
    p.add_argument("--scene-length",type=int,default=2)
    p.add_argument("--run-prefix",default="mouth-p3-momiji2")
    p.add_argument("--url",default="http://127.0.0.1:8191")
    a=p.parse_args()
    if a.infer:
        if a.source is None:
            p.error("--source is required to infer")
        infer(a.source,a.output,a.url)
    elif a.finalize:
        finalize(a.output)
    elif a.verify:
        verify(a.output,a.url)
    elif a.render:
        render(a.output,a.render,a.url)
    else:
        if a.source is None:
            p.error("--source is required to prepare")
        prepare(a.source,a.output,scene_start=a.scene,scene_length=a.scene_length,run_prefix=a.run_prefix)


if __name__ == "__main__":
    main()
