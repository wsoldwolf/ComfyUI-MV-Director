"""Opt-in P4 probe: change only one instrumental performance from saved P2.

No production prompt edits, new authoring stage, or semantic Python repair.
Other LLM-authored fields and English translations are reused verbatim.
Only the selected pair of Scenes may be rendered from the placeholder Plan.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.artifacts import DirectionArtifact
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.api import render_planner_content
from core.planner.requests import request_entities
from core.planner.scene_author import _split_terminal_state
from core.planner.template import parse_template_emd
from core.planner.types import PlannerContent, PlannerEntity
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy
from nodes.node_emd_compiler.node import _system_prompt

CANDIDATE = (
    "歌詞のない間奏で、人物は歌い出すまで目を閉じたまま、"
    "足を地面に置いて短く荷重を移す。膝の小さな弾みから胸郭を開き、"
    "右腕を外側へ上げる弧に左腕の低い逆向きの弧を添える。"
    "上がった右手の指先をほどく瞬間を短いアクセントにし、"
    "胸郭と肘を緩めて次の歌唱姿勢へつなぐ。"
    "Cameraが後方へ引く間に見える上半身の連鎖として扱う。"
)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def verify_body_only_plan(saved, candidate, scene_number, old_english, new_english):
    """Validate an analytical copy; never modify the delivered candidate."""
    if not old_english or not new_english or old_english == new_english:
        raise ValueError("Expected two distinct body translations")
    normalized = json.loads(json.dumps(candidate))
    target = normalized["shots"][scene_number - 1]
    if not any(new_english in line for line in target["prompt"]):
        raise ValueError("New translated performance is missing")
    target["prompt"] = [line.replace(new_english, old_english) for line in target["prompt"]]
    if normalized != saved:
        raise ValueError("Plan contains a change outside the chosen performance")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    previous = args.previous.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a fresh research directory")
    output.mkdir(parents=True, exist_ok=True)
    conditions = json.loads((previous / "conditions.json").read_text(encoding="utf-8"))
    template = parse_template_emd((Path(conditions["source_alignment"]) / "template.md").read_text(encoding="utf-8"))
    scene = conditions["scene_start"] + 1
    old = json.loads((previous / "activity-inference.json").read_text(encoding="utf-8"))
    content = PlannerContent.from_dict(old["content"])
    actions = {(s, i): text for s, i, text in content.actions}
    cameras = {(s, i): text for s, i, text in content.cameras}
    request = None
    for row in old["trace"]:
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        if row["task"] == "scene-author-performance" and payload["scene_number"] == scene:
            request = payload
    if request is None or len(request["slots"]) != 2:
        raise ValueError("Expected saved P2 two-Shot performance request")
    original_request = json.loads(json.dumps(request))
    selected = request["slots"][0]
    shared = {k: v for k, v in request.items() if k not in ("slots", "protocol", "task")}
    shared["staging_candidates_optional"] = [CANDIDATE, *request["staging_candidates_optional"][1:]]
    shared["fixed_performances"] = {"2": actions[(scene, 2)]}
    for position in shared["shot_positions"]:
        position["fixed_camera"] = cameras[(scene, position["shot"])]
        if position["shot"] == 2:
            position["fixed_performance"] = actions[(scene, 2)]
    selected["position"] = shared["shot_positions"][0]
    selected = {k: v for k, v in selected.items() if k != "slot"}
    prompts = _system_prompts()
    save(output / "system-prompts.json", prompts)
    save(output / "input-contract.json", {
        "original_request": original_request, "shared": shared, "selected_entity": selected,
        "candidate": CANDIDATE, "protected_scene": scene - 1,
        "protected_fields": ["all events", "all cameras", "singing Shot performance", "Plan globals", "PCM clock", "seeds"],
    })
    if args.prepare_only:
        print("CPU preparation passed; no model loaded")
        return
    lifecycle = LlamaCppLifecycle()
    config = LlamaRuntimeConfig(**conditions["runtime"])
    direction = DirectionArtifact.from_dict(conditions["direction"])

    class Backend(_LlamaPlannerBackend):
        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            value = json.loads(payload.split("\0", 1)[0])
            material = f"{base_seed}/{value['scene_number']}/{task}/{call_number}"
            return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1

    try:
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        backend = Backend(lifecycle)
        backend.transport_policy = _planner_transport_policy(conditions["model"])
        backend._task_calls["scene-author-performance"] = 1
        backend._primary_calls["scene-author-performance"] = 1
        started = time.perf_counter()
        result, issues, retries, missing, recovered = request_entities(
            backend, task="scene-author-performance", record_type="PERFORMANCE",
            entities=[PlannerEntity(scene, (1,), selected)], shared=shared,
            system_prompt=prompts["scene-author-performance"], runtime_config=config, interrupt_callback=None)
        save(output / "activity-inference.json", {"trace": backend.trace, "missing": missing,
            "issues": [str(i) for i in issues], "retried_scenes": retries,
            "recovered": recovered, "elapsed_s": time.perf_counter() - started})
        if missing:
            raise RuntimeError(f"Incomplete local performance: {missing}")
        prose, terminal = _split_terminal_state(result[(1,)])
        updated = replace(content, actions=tuple(
            (s, i, prose if (s, i) == (scene, 1) else text) for s, i, text in content.actions))
        assert updated.events == content.events and updated.cameras == content.cameras
        assert [(s, i, t) for s, i, t in updated.actions if (s, i) != (scene, 1)] == [
            (s, i, t) for s, i, t in content.actions if (s, i) != (scene, 1)]
        save(output / "selected-performance.json", {"old": actions[(scene, 1)], "new": prose,
            "terminal_state": terminal, "content": updated.to_dict()})
        reference = Path(conditions["reference_emd"]).read_text(encoding="utf-8-sig")
        concept = reference.split("\n# シーン設定", 1)[0].strip() + "\n"
        scene_emd = "# シーン設定" + reference.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
        all_actions, all_cameras = list(updated.actions), list(updated.cameras)
        for item in template.scenes:
            if item.scene_number not in (scene - 1, scene):
                for index, _ in enumerate(item.shots, 1):
                    all_actions.append((item.scene_number, index, "検証対象外。"))
                    all_cameras.append((item.scene_number, index, "検証対象外。"))
        emd = render_planner_content(content=replace(updated, actions=tuple(all_actions), cameras=tuple(all_cameras)),
            concept_emd=concept, scene_emd=scene_emd, template=template, direction=direction,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1)
        (output / "activity.md").write_text(emd.text, encoding="utf-8")
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
            runtime_config=replace(config, temperature=0.0, max_tokens=4096))
        cache = {}
        for row in json.loads((previous / "activity-translation.json").read_text(encoding="utf-8")):
            key, value = tuple(row["fragments"]), tuple(row["translated"])
            if key in cache and cache[key] != value:
                raise ValueError("Conflicting saved English translations")
            cache[key] = value

        class CachedTranslator:
            def __init__(self):
                self.translation_trace = []
                self.reused = False
            def translate(self, units):
                key = tuple(units)
                self.reused = key in cache
                return cache[key] if self.reused else translator.translate(units)
            def record_field_translation(self, **kwargs):
                self.translation_trace.append({**kwargs, "reused_saved_translation": self.reused})

        cached = CachedTranslator()
        compiled = compile_ref2va(emd.text, cached)
        for index, shot in enumerate(compiled.plan["shots"], 1):
            shot["seed"] = 20261003 + index
        saved = json.loads((previous / "activity-plan.json").read_text(encoding="utf-8"))
        field = f"scene.{scene - 1}.shot.0.body.0"
        old_row = next(row for row in json.loads((previous / "activity-translation.json").read_text(encoding="utf-8")) if row["field_id"] == field)
        new_row = next(row for row in cached.translation_trace if row["field_id"] == field)
        verify_body_only_plan(saved, compiled.plan, scene,
            old_row["restored"], new_row["restored"])
        if {k: v for k, v in saved.items() if k != "shots"} != {k: v for k, v in compiled.plan.items() if k != "shots"}:
            raise ValueError("Plan globals changed")
        for index, (before, after) in enumerate(zip(saved["shots"], compiled.plan["shots"]), 1):
            if index != scene and before != after:
                raise ValueError(f"Protected Scene {index} changed")
        save(output / "activity-plan.json", compiled.plan)
        save(output / "activity-translation.json", cached.translation_trace)
        for original, dest in (("activity.md", "baseline.md"), ("activity-plan.json", "baseline-plan.json"),
                               ("activity-inference.json", "baseline-inference.json")):
            shutil.copy2(previous / original, output / dest)
        save(output / "conditions.json", {**conditions, "previous_comparison": str(previous),
            "comparison": "Only Scene 13 Shot 1 performance reauthored with a more concrete instrumental candidate; P2 Event, singing Shot and Camera retained verbatim",
            "candidate": CANDIDATE, "system_prompt_sha256": {
                task: hashlib.sha256(text.encode()).hexdigest() for task, text in prompts.items()}})
        print("P4 body-only Plan compiled; all protected fields unchanged", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    main()
