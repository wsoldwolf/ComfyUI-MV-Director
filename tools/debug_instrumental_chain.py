"""Research: normal Planner/Compiler and connected H3 Scenes 11-13.

The clip includes actual source pre-roll, never inter-Scene silence insertion.
Research-authored Event/Camera and a chronological candidate are explicit.
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

from core.emd import parse_emd
from tools.debug_momentum_pipeline import production_inputs, infer
from tools.debug_shot_duration import verify_pcm
from tools.prepare_beat_motion_h3 import read, save, FFMPEG, FFPROBE
from tools.prepare_instrumental_h3 import render
from nodes.node_timeline_planner.node import _system_prompts

TARGETS = (11, 12, 13)
SLOTS = ((11, 1), (12, 1), (13, 1), (13, 2))
RUN_NAME = "instrumental-chain-b19-momiji2-s11-13-20261004"
USER_REQUEST = """# 演出候補
* 長い伴奏から歌唱へ戻る一連の演技として、89.458〜99.375秒では短く膝を曲げて荷重を溜め、踏み替えを連ねて勢いよく半回転する。正面、横顔、背中が順に見え、腰に肩が続き、左腕の弧に袖と袴が遅れて流れる。回転の終点で次の踏み替えを始める。99.375〜110.000秒では前の踏み替えから身体の左右へ荷重を受け渡し、腰と胸郭を交互に斜めへ向け、左腕を低い弧から胸前へ通して外側へほどく。足運びと体幹と腕の流れをつないで踊り続ける。110.000〜116.046秒では目を閉じ、踏み替えの幅を少しずつ小さくしながら胸郭を開き、左腕を歌う姿勢へつなぐ。116.046秒からは顔を正面へ向けて目を開き、入力ボーカルに合わせて歌い、伴奏中の身体の流れを歌唱の呼吸へ渡す。剣は右手で握り続け、身体の向きに合わせて腕と一緒に運ぶ。
"""
EVENT = "人物の背後で滝の水が岩に砕け、白い水しぶきが舞い上がる。袖の周囲を細かな水滴と紅葉が横切り、水滴が光を受けてきらめく。"
CAMERAS = {
    (11, 1): "頭部を画面内に収めた正面のミディアムショットからゆっくり後方へ引き、人物の全身と背後の滝の水しぶきを同じ画面で捉える。",
    (12, 1): "前ShotのCameraの高さと距離を引き継ぎ、人物の全身と背後の滝の水しぶきを同じ画面に保つ。足運びと体幹と左腕の連動を一続きに捉える。",
    (13, 1): "前Shotの全身の構図を引き継いでゆっくり近づき、閉眼した顔と上半身の演技を同時に捉える。",
    (13, 2): "正面の胸上の構図で顔、両目、歌唱する口をはっきり捉え、歌唱の呼吸に伴う肩と左腕の動きも画面内に残す。",
}


def chain_input(text):
    parts = re.split(r"(?=> `シーン` \d+)", text)
    found = set()
    for index, chunk in enumerate(parts):
        matched = re.match(r"> `シーン` (\d+)\n", chunk)
        if not matched or int(matched[1]) not in TARGETS:
            continue
        number = int(matched[1])
        chunk = re.sub(r"^\* `(演出|演技|カメラ)` .*?\n", "", chunk, flags=re.M)
        shot_index = 0
        def inject(match):
            nonlocal shot_index
            shot_index += 1
            return (match[0] + "* `演出` " + EVENT + "\n* `カメラ` " + CAMERAS[(number, shot_index)]
                    + "\n* `演技` 検証対象外。\n")
        chunk = re.sub(r"^## ショット .*?\n", inject, chunk, flags=re.M)
        found.add(number)
        parts[index] = chunk
    if found != set(TARGETS):
        raise ValueError("Missing target Scenes")
    result = "".join(parts)
    before, after = parse_emd(text), parse_emd(result)
    for old, new in zip(before.scenes, after.scenes):
        if ((old.start_ms, old.end_ms, old.h3_length, old.continuation) !=
            (new.start_ms, new.end_ms, new.h3_length, new.continuation)):
            raise ValueError("Source timeline changed")
        if [q.lyric_annotations for q in old.shots] != [q.lyric_annotations for q in new.shots]:
            # Source line numbers shift after replacing prose; lyric values must not.
            def annotations(scene):
                return [[(a.text, a.section, a.start_ms, a.end_ms) for a in q.lyric_annotations] for q in scene.shots]
            if annotations(old) != annotations(new):
                raise ValueError("Source lyric timing changed")
    template, _, _, _ = production_inputs(result, USER_REQUEST, target_scenes=TARGETS, preserve_continuation=True)
    if [s.continuation for s in template.scenes if s.scene_number in TARGETS] != [False, True, True]:
        raise ValueError("Requires fresh start followed by two continuations")
    return result


def connected_plan(full_plan):
    plan = deepcopy(full_plan)
    plan["shots"] = plan["shots"][10:13]
    if [q["id"] for q in plan["shots"]] != [f"scene_{i:04d}" for i in TARGETS]:
        raise ValueError("Unexpected Scene IDs")
    for shot, length, context in zip(plan["shots"], (260, 277, 243), (0, 22, 22)):
        if (shot["length"], shot.get("context_length", 0), shot.get("audio_context_length", 0)) != (length, context, context):
            raise ValueError("Unexpected continuation clock")
    plan.pop("mv_director_audio_activity", None)
    return plan


def clock_from_text(text):
    scenes = parse_emd(text).scenes[10:13]
    # Millisecond EMD is a rounded representation of the 24fps source clock.
    start_frame = round(scenes[0].start_ms * 24 / 1000) - 22
    end_frame = round(scenes[-1].end_ms * 24 / 1000)
    frames = end_frame - start_frame
    if frames != 260 + (277 - 22) + (243 - 22):
        raise ValueError("Source PCM and delivered frames disagree")
    return {"source_start_sample": start_frame * 2000, "source_end_sample": end_frame * 2000,
            "sample_rate": 48000, "render_frames": frames, "content_frames": frames,
            "tail_silence_samples": 0, "preroll_frames": 22,
            "clip_start_source_ms": start_frame * 1000 / 24,
            "clip_end_source_ms": end_frame * 1000 / 24}


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty destination")
    text = chain_input((source / "dance.md").read_text(encoding="utf-8"))
    clock = clock_from_text(text)
    connected_plan(read(source / "compiled-full-plan.json"))
    template, direction, _, _ = production_inputs(text, USER_REQUEST, target_scenes=TARGETS, preserve_continuation=True)
    targets = [Path(r"C:\Software\ComfyUI\input") / f"mvd_chain_b19_momiji2_{stem}_s11_13_20261004.wav"
               for stem in ("vocal", "fullmix")]
    if any(p.exists() for p in targets):
        raise ValueError("Refusing to replace existing PCM")
    graph = read(source / "h3-dance.json")
    if graph["48"]["inputs"]["enable"] or graph["37"]["inputs"]["reference_alignment"] != "off":
        raise ValueError("Unexpected audio clock processing")
    if graph["40"]["inputs"]["voice"] != ["48", 1] or graph["28"]["inputs"]["enabled"]:
        raise ValueError("Lip-sync or ReviewGate route changed")
    output.mkdir(parents=True)
    audio = []
    for row, target in zip(read(source / "h3-manifest.json")["audio"], targets):
        subprocess.run([FFMPEG, "-v", "error", "-i", row["source"], "-af",
            f"atrim=start_sample={clock['source_start_sample']}:end_sample={clock['source_end_sample']},asetpts=PTS-STARTPTS",
            "-c:a", "pcm_f32le", str(target)], check=True)
        audio.append({"source": row["source"], "crop": str(target)})
    checks, _ = verify_pcm(clock, audio)
    prompts, conditions = _system_prompts(), read(source / "conditions.json")
    save(output / "conditions.json", {"model": conditions["model"], "runtime": conditions["runtime"],
        "target_scenes": list(TARGETS), "generated_slots": list(SLOTS), "preserve_continuation": True,
        "defer_delivery": True, "staging_candidate_policy": "optional", "compiler_max_tokens": 4096,
        "translation_cache": str(source / "translation.json"), "source": str(source),
        "system_prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()}})
    save(output / "system-prompts.json", prompts)
    (output / "input-emd.md").write_text(text, encoding="utf-8")
    (output / "user-request.md").write_text(USER_REQUEST, encoding="utf-8")
    save(output / "input-contract.json", {"direction": direction.to_dict(), "candidate": USER_REQUEST,
        "fixed_events": {f"{s}:{q}": EVENT for s, q in SLOTS},
        "fixed_cameras": {f"{s}:{q}": t for (s, q), t in CAMERAS.items()},
        "audio_activity": {str(s.scene_number): template.audio_activity.scene_payload(
            start_ms=s.start_ms, end_ms=s.end_ms, audio_mode="context_loop")
            for s in template.scenes if s.scene_number in TARGETS},
        "normal_planner_compiler": True, "research_authored_event_camera": True,
        "comparison": "chronological candidate plus localized Event/Camera; connected clip; not a controlled single-field A/B",
        "accepted_scene11_evidence_unchanged": True, "placeholder_other_scenes_must_not_render": True})
    graph["33"]["inputs"]["audio"], graph["32"]["inputs"]["audio"] = targets[0].name, targets[1].name
    save(output / "h3-template.json", graph)
    save(output / "pcm-checks.json", checks)
    save(output / "h3-manifest.json", {**clock, "audio": audio, "run_names": {"dance": RUN_NAME},
        "source": str(source), "megapixels": 0.4, "steps": 20,
        "source_scenes": list(TARGETS), "raw_lengths": [260, 277, 243], "context_lengths": [0, 22, 22],
        "delivered_lengths": [260, 255, 221], "no_inter_scene_padding": True,
        "same_scene_baseline_video": None, "new_render_count": 1})
    print(json.dumps({"prepared": True, "clock": clock, "GPU_used": False}), flush=True)


def deliver(args):
    output = args.output.resolve(strict=True)
    if (output / "submission-dance.json").exists():
        raise ValueError("Already submitted; preserve evidence")
    full = read(output / "compiled-full-plan.json")
    source = Path(read(output / "conditions.json")["source"])
    old = read(source / "compiled-full-plan.json")
    if {k: v for k, v in full.items() if k != "shots"} != {k: v for k, v in old.items() if k != "shots"}:
        raise ValueError("Protected Plan globals changed")
    for i, (before, after) in enumerate(zip(old["shots"], full["shots"]), 1):
        if i not in TARGETS and before != after:
            raise ValueError(f"Non-target Scene {i} changed")
        if i in TARGETS and {k: v for k, v in before.items() if k != "prompt"} != {k: v for k, v in after.items() if k != "prompt"}:
            raise ValueError(f"Protected target settings changed in Scene {i}")
        if before["prompt"][:4] != after["prompt"][:4]:
            raise ValueError("Subject or background identity changed")
    plan = connected_plan(full)
    if any("Outside the scope of verification." in line for shot in plan["shots"] for line in shot["prompt"]):
        raise ValueError("Do not render placeholder prose")
    trace = read(output / "inference.json")
    translations = read(output / "translation.json")
    excerpt = "# 伴奏から歌唱復帰までの通常生成演技\n\n"
    for s, q, prose in trace["content"]["actions"]:
        row = next(r for r in translations if r["source"] == prose)
        excerpt += f"## Scene {s} Shot {q}\n\n{prose}\n\n```text\n{row['restored']}\n```\n\n"
    (output / "dance-excerpt.md").write_text(excerpt, encoding="utf-8")
    save(output / "dance-plan.json", plan)
    graph = read(output / "h3-template.json")
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(plan, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = graph["21"]["inputs"]["filename"] = RUN_NAME
    save(output / "h3-dance.json", graph)
    save(output / "output-contract.json", {"protected_other_scenes_and_identity_verified": True,
        "target_prompt_only_changes": True, "clip_has_no_placeholders": True,
        "no_semantic_prose_repair": True, "no_authored_english_insertion": True,
        "terminal_states": trace["content"]["terminal_states"]})
    print("Connected output verified; inspect generated prose before H3", flush=True)


def finalize(args):
    import torch
    from tools.analyze_audio_activity import decode_audio
    output = args.output.resolve(strict=True)
    if (output / "media-checks.json").exists():
        raise ValueError("Already finalized")
    manifest, history = read(output / "h3-manifest.json"), read(output / "render-dance.json")
    if history["history"]["status"]["status_str"] != "success":
        raise ValueError("Incomplete H3 run")
    checks, fullmix = verify_pcm(manifest, manifest["audio"])
    path = Path(r"C:\Software\ComfyUI\output\h3_chains") / RUN_NAME / "final" / (RUN_NAME + ".mp4")
    probe = json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,duration,nb_frames", "-of", "json", str(path)], encoding="utf-8"))
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if (video["width"], video["height"], video["r_frame_rate"], int(video["nb_frames"])) != (864, 480, "24/1", manifest["render_frames"]):
        raise ValueError("Unexpected video clock")
    delivered, rate, _ = decode_audio(path, FFMPEG)
    size = min(fullmix.shape[-1], delivered.shape[-1])
    if rate != 48000:
        raise ValueError("Unexpected output audio clock")
    cosine = float(torch.nn.functional.cosine_similarity(fullmix.mean(dim=1)[..., :size].reshape(-1),
                                                       delivered.mean(dim=1)[..., :size].reshape(-1), dim=0))
    if cosine < 0.98:
        raise ValueError("Output fullmix shifted")
    subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", "fps=1/2,scale=432:240,tile=5x3",
                    "-frames:v", "1", str(output / "contact-sheet.png")], check=True)
    save(output / "media-checks.json", {"video": str(path), "streams": probe["streams"], "pcm_checks": checks,
        "render_wait_s": history["elapsed_s"], "render_audio_zero_offset_fullmix_cosine": cosine,
        "scene_boundaries_local_seconds": [260/24, 515/24],
        "vocal_return_local_seconds": 116.045917 - manifest["clip_start_source_ms"]/1000,
        "human_evaluation": "pending"})
    print(str(path), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "infer", "deliver", "render", "finalize"))
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
        deliver(args)
    elif args.task == "deliver":
        deliver(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
