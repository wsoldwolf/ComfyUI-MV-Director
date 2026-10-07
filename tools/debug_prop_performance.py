"""Opt-in P1: compare existing Performance prompts on saved EMD Scenes.

No H3 submission, translation, semantic Python repair, or new authoring stage.
Events, Camera, timing, mouth annotations and existing supplements stay fixed.
Only primary Performance fields are reopened; the first boundary Shot stays fixed.
Outputs go to an explicitly supplied external evidence directory.
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
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.mouth_performance import mouth_scene_payload
from core.planner.requests import request_entities
from core.planner.scene_author import _lyrics, _shot_positions, _split_terminal_state
from core.planner.section_context import section_context_by_scene
from core.planner.template import PlannerTemplate
from core.planner.types import PlannerEntity
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _planner_transport_policy

PROMPT_PATH = "prompts/timeline_planner_scene_author_performance_system_prompt.txt"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_inputs(text, scene_numbers):
    doc = parse_emd(text)
    template = PlannerTemplate(doc.scenes, doc.audio_activity)
    contexts = section_context_by_scene(template)
    concept = re.split(r"\n(?=# (?!サブジェクト)|> `シーン`)", text, maxsplit=1)[0].strip() + "\n"
    if "# シーン設定" in text:
        scene_emd = "# シーン設定" + text.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
    else:
        scene_emd = ""
    common = doc.common_prompt_dict()
    requests = []
    for number in scene_numbers:
        scene = next((s for s in doc.scenes if s.scene_number == number), None)
        if scene is None:
            raise ValueError(f"Scene {number} is absent")
        fixed, original, supplements, reopened = {}, {}, {}, []
        for index, shot in enumerate(scene.shots, 1):
            performances = [d.text for d in shot.directives if d.kind == "演技"]
            if not performances:
                raise ValueError("Expected completed primary performances")
            original[str(index)] = performances[0]
            if len(performances) > 1:
                supplements[str(index)] = performances[1:]
            if number == scene_numbers[0] and index == 1:
                fixed[str(index)] = " ".join(performances)
                reopened.append(shot)
            else:
                reopened.append(replace(shot,
                    body=tuple(t for t in shot.body if not t.startswith("`演技` ")),
                    directives=tuple(d for d in shot.directives if d.kind != "演技")))
        partial = replace(scene, shots=tuple(reopened))
        positions = _shot_positions(partial)
        events = {str(i): " ".join(d.text for d in s.directives if d.kind == "演出") or "なし"
                  for i, s in enumerate(scene.shots, 1)}
        shared = {
            "scene_number": number, "scene_start_ms": scene.start_ms,
            "scene_end_ms": scene.end_ms, "continuation": scene.continuation,
            "scene_descriptions": list(scene.descriptions), "original_lyrics": _lyrics(scene),
            "section_lyric_context": contexts[number], "subject_emd": concept,
            "scene_emd": scene_emd, "shot_positions": positions,
            "scene_environment": list(doc.scene_setting.environment) if doc.scene_setting else [],
            "scene_time_lighting": list(doc.scene_setting.time_lighting) if doc.scene_setting else [],
            "scene_motion": list(common.get("モーション", ())),
            "scene_other": list(common.get("その他", ())),
            "staging_candidates_optional": [], "staging_candidate_policy": "optional",
            "fixed_performances": fixed, "accepted_events_by_shot": events,
            "event_sources_by_shot": {i: "author" for i in events},
        }
        if doc.audio_activity:
            shared["audio_activity"] = doc.audio_activity.scene_payload(
                start_ms=scene.start_ms, end_ms=scene.end_ms, audio_mode="context_loop")
        if scene.mouth_performances:
            shared["mouth_performance"] = mouth_scene_payload(scene, scene.mouth_performances)
        # This comparison exposes the *unchanged* final supplement in both arms.
        # It does not change production post-author ordering or selection.
        active = {i: texts for i, texts in supplements.items() if i not in fixed}
        if len(active) > 1:
            raise ValueError("Probe supports at most one scheduled supplement per Scene")
        if active:
            index, texts = next(iter(active.items()))
            shared["scheduled_motion_composition"] = {
                "shot": int(index), "source": "saved_emd", "text": " ".join(texts)}
        entities = [PlannerEntity(number, (i,), {
            "scene_number": number, "scene": number, "shot": i, "position": position})
            for i, position in enumerate(positions, 1) if str(i) not in fixed]
        requests.append({"scene_number": number, "shared": shared, "entities": entities,
                         "original": original, "supplements": supplements})
    return requests


def replace_primary_performances(text, replacements):
    """Assign experimental LLM fields verbatim; keep every other source line."""
    scene = shot = 0
    seen = set()
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"> `シーン` (\d+)\s*$", line)
        if match:
            scene, shot = int(match.group(1)), 0
        if line.startswith("## ショット "):
            shot += 1
        key = (scene, shot)
        if line.startswith("* `演技` ") and key in replacements and key not in seen:
            line = "* `演技` " + replacements[key] + "\n"
            seen.add(key)
        lines.append(line)
    if seen != set(replacements):
        raise ValueError("Could not assign all selected Performance fields")
    result = "".join(lines)
    before, after = parse_emd(text), parse_emd(result)
    if (before.subjects, before.common_prompt, before.retention, before.scene_setting,
        before.audio_activity) != (after.subjects, after.common_prompt, after.retention,
                                    after.scene_setting, after.audio_activity):
        raise ValueError("Non-performance document settings changed")
    for a, b in zip(before.scenes, after.scenes):
        if replace(a, shots=b.shots) != b:
            raise ValueError("Scene time, audio, mouth or metadata changed")
        for index, (old, new) in enumerate(zip(a.shots, b.shots), 1):
            if (old.start_ms, old.lyric_annotations, old.lyric_lip_sync) != (
                    new.start_ms, new.lyric_annotations, new.lyric_lip_sync):
                raise ValueError("Shot time or lyrics changed")
            for kind in ("演出", "カメラ"):
                if [d for d in old.directives if d.kind == kind] != [
                        d for d in new.directives if d.kind == kind]:
                    raise ValueError("Event or Camera changed")
            old_p = [d.text for d in old.directives if d.kind == "演技"]
            new_p = [d.text for d in new.directives if d.kind == "演技"]
            expected = replacements.get((a.scene_number, index), old_p[0])
            if new_p != [expected, *old_p[1:]]:
                raise ValueError("Boundary performance or supplement changed")
    return result


def run_condition(backend, requests, prompt, config):
    previous = ""
    rows, replacements = [], {}
    for item in requests:
        shared = deepcopy(item["shared"])
        shared["previous_scene_state"] = previous if shared["continuation"] else ""
        result, issues, retries, missing, recovered = request_entities(
            backend, task="scene-author-performance", record_type="PERFORMANCE",
            entities=item["entities"], shared=shared, system_prompt=prompt,
            runtime_config=config, interrupt_callback=None)
        if missing:
            raise RuntimeError(f"Incomplete Scene {item['scene_number']}: {missing}")
        actions, states = {}, {}
        for key, value in result.items():
            prose, state = _split_terminal_state(value)
            actions[str(key[0])], states[str(key[0])] = prose, state
            replacements[(item["scene_number"], key[0])] = prose
        last = str(len(shared["shot_positions"]))
        previous = states.get(last, "")
        rows.append({"scene_number": item["scene_number"], "original": item["original"],
                     "generated": actions, "terminal_states": states, "input": shared,
                     "issue_count": len(issues), "retried_scenes": retries,
                     "recovered": recovered})
    return rows, replacements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emd", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-start", type=int, default=15)
    parser.add_argument("--scene-length", type=int, default=3)
    parser.add_argument("--baseline-ref", default="cdf6f12")
    parser.add_argument("--candidate-prompt", type=Path,
                        help="Experimental prompt file; production prompt is used if omitted")
    parser.add_argument("--conditions", choices=("both", "candidate"), default="both")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    if args.scene_start < 1 or args.scene_length < 1:
        raise ValueError("Use positive Scene ranges")
    if not args.prepare_only and args.model is None:
        raise ValueError("Inference requires an explicit model")
    text = args.emd.read_text(encoding="utf-8-sig")
    numbers = list(range(args.scene_start, args.scene_start + args.scene_length))
    requests = prepare_inputs(text, numbers)
    baseline = subprocess.check_output(["git", "show", f"{args.baseline_ref}:{PROMPT_PATH}"],
                                      cwd=ROOT).decode("utf-8").rstrip() + "\n"
    candidate_path = args.candidate_prompt or ROOT / PROMPT_PATH
    candidate = candidate_path.read_text(encoding="utf-8").rstrip() + "\n"
    if baseline == candidate:
        raise ValueError("The two prompts are identical")
    config = LlamaRuntimeConfig(max_tokens=1536, n_ctx=16384, n_batch=256,
                               temperature=0.2, seed=20261007)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, prompt in (("baseline", baseline), ("candidate", candidate)):
        (args.output / f"{name}-system.txt").write_text(prompt, encoding="utf-8")
    (args.output / "source-emd.md").write_text(text, encoding="utf-8")
    save(args.output / "inputs.json", [{**r, "entities": [e.value for e in r["entities"]]}
                                       for r in requests])
    save(args.output / "conditions.json", {
        "source_emd": str(args.emd.resolve()), "scene_numbers": numbers,
        "source_sha256": hashlib.sha256(args.emd.read_bytes()).hexdigest(),
        "model": str(args.model.resolve()) if args.model else None,
        "runtime": config.to_dict(), "baseline_ref": args.baseline_ref,
        "candidate_prompt_source": str(candidate_path.resolve()),
        "inferred_conditions": ["baseline", "candidate"] if args.conditions == "both" else ["candidate"],
        "boundary_first_performance_fixed": True,
        "staging_candidates_replayed": False,
        "saved_events_cameras_mouth_supplements_fixed": True,
        "saved_supplement_exposed_pre_author_in_both_conditions": True,
        "inference_stages": ["scene-author-performance"], "h3_generated": False,
        "system_prompt_sha256": {name: hashlib.sha256(prompt.encode()).hexdigest()
                                  for name, prompt in (("baseline", baseline), ("candidate", candidate))},
        "seed_policy": "matched base/scene/task/call; exclude varying payload from comparison seed"})
    if args.prepare_only:
        print("CPU preparation passed; no model loaded", flush=True)
        return

    class MatchedBackend(_LlamaPlannerBackend):
        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            request = json.loads(payload.split("\0", 1)[0])
            material = f"{base_seed}/{request['scene_number']}/{task}/{call_number}"
            return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1

    lifecycle = LlamaCppLifecycle()
    try:
        started = time.perf_counter()
        model = lifecycle.ensure_loaded(args.model, config)
        print(f"Model ready in {time.perf_counter() - started:.2f}s", flush=True)
        conditions = (("baseline", baseline), ("candidate", candidate))
        if args.conditions == "candidate":
            conditions = conditions[1:]
        for name, prompt in conditions:
            model.reset()
            backend = MatchedBackend(lifecycle)
            backend.transport_policy = _planner_transport_policy(args.model.name)
            started = time.perf_counter()
            rows, replacements = run_condition(backend, requests, prompt, config)
            save(args.output / f"{name}-inference.json", {
                "scenes": rows, "trace": backend.trace,
                "elapsed_s": time.perf_counter() - started})
            (args.output / f"{name}-emd.md").write_text(
                replace_primary_performances(text, replacements), encoding="utf-8")
            print(f"{name} finished in {time.perf_counter() - started:.2f}s", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    main()
