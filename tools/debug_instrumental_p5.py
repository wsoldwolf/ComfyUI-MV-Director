"""Opt-in P5: unfiltered versus PCM-routed pools on a fresh instrumental Scene.

The only comparison variable is the Performance candidate list. Camera is a
saved P4 line, Event is authored once, prose remains AS IS. Research output only.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.artifacts import DirectionArtifact
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.api import generate_planner_content, render_planner_content
from core.planner.requests import request_entities
from core.planner.scene_author import _split_terminal_state
from core.planner.section_context import section_context_by_scene
from core.planner.template import PlannerTemplate, parse_template_emd
from core.planner.types import PlannerEntity
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy
from nodes.node_emd_compiler.node import _system_prompt
from tools.debug_instrumental_p4 import CANDIDATE, save, verify_body_only_plan
from tools.instrumental_candidate_routing import ScopedCandidate, route_candidates


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--previous", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--scene", type=int, default=11)
    p.add_argument("--prepare-only", action="store_true")
    args = p.parse_args()
    previous = args.previous.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    conditions = json.loads((previous / "conditions.json").read_text(encoding="utf-8"))
    template = parse_template_emd((Path(conditions["source_alignment"]) / "template.md").read_text(encoding="utf-8"))
    scene = next(s for s in template.scenes if s.scene_number == args.scene)
    if len(scene.shots) != 1:
        raise ValueError("This probe requires a single-Shot Scene")
    activity = template.audio_activity.scene_payload(start_ms=scene.start_ms, end_ms=scene.end_ms, audio_mode="context_loop")
    pools = [
        ScopedCandidate("歌い出し前のイントロで、目を閉じて静かに呼吸し、腕を低く置いたまま風を感じる。", "intro"),
        ScopedCandidate(CANDIDATE, "interlude"),
        ScopedCandidate("曲が終わった後の余韻で、手を静かに下ろし、呼吸を収めて遠くを見つめる。", "outro"),
        # Existing untyped author text stays general, even if it mentions vocals.
        ScopedCandidate(conditions["direction"]["staging_candidates"][1]),
    ]
    routing = route_candidates(pools, activity, start_ms=scene.start_ms, end_ms=scene.end_ms)
    if routing["fallback"] or "interlude" not in routing["eligible_scopes"]:
        raise ValueError("Chosen research Scene is not a confirmed instrumental window")
    saved = json.loads((previous / "selected-performance.json").read_text(encoding="utf-8"))["content"]
    camera = next(text for s, i, text in saved["cameras"] if (s, i) == (13, 1))
    prompts = _system_prompts()
    save(output / "system-prompts.json", prompts)
    save(output / "routing.json", {"pools": [dict(text=c.text, scope=c.scope) for c in pools],
        "routing": routing, "activity": activity, "scene": args.scene,
        "fixed_camera_source": "P4 Scene 13 Shot 1", "fixed_camera": camera,
        "prior_context": "isolated fresh Scene; no generated predecessor state"})
    if args.prepare_only:
        print(json.dumps(routing, ensure_ascii=False), flush=True)
        return
    config = LlamaRuntimeConfig(**conditions["runtime"])
    direction = DirectionArtifact.from_dict(conditions["direction"])
    contexts = section_context_by_scene(template)
    reference = Path(conditions["reference_emd"]).read_text(encoding="utf-8-sig")
    concept = reference.split("\n# シーン設定", 1)[0].strip() + "\n"
    scene_emd = "# シーン設定" + reference.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
    lifecycle = LlamaCppLifecycle()

    class Backend(_LlamaPlannerBackend):
        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            value = json.loads(payload.split("\0", 1)[0])
            material = f"{base_seed}/{value['scene_number']}/{task}/{call_number}"
            return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1

        def complete_planner(self, *, task, payload, **kwargs):
            request = json.loads(payload)
            request["section_lyric_context"] = contexts[args.scene]
            if task == "scene-author-performance":
                request["staging_candidates_optional"] = [c.text for c in pools]
                for position in request["shot_positions"]:
                    position["fixed_camera"] = camera
                for slot in request["slots"]:
                    slot["position"]["fixed_camera"] = camera
            if task == "scene-author-camera":
                response = "CAMERA\t1\t" + camera
                self.trace.append({"task": task, "payload": request, "response": response,
                    "replayed_fixed_p4_camera": True})
                return response
            return super().complete_planner(task=task, payload=json.dumps(request, ensure_ascii=False), **kwargs)

    try:
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        baseline_backend = Backend(lifecycle)
        baseline_backend.transport_policy = _planner_transport_policy(conditions["model"])
        started = time.perf_counter()
        baseline, missing = generate_planner_content(baseline_backend,
            template=PlannerTemplate((scene,), template.audio_activity), concept_emd=concept,
            scene_emd=scene_emd, direction=direction, lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            system_prompts=prompts, runtime_config=config)
        save(output / "baseline-inference.json", {"content": baseline.to_dict() if baseline else None,
            "missing": missing, "trace": baseline_backend.trace, "elapsed_s": time.perf_counter() - started})
        if baseline is None or missing:
            raise RuntimeError(f"Incomplete baseline: {missing}")
        request = next(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            for r in baseline_backend.trace if r["task"] == "scene-author-performance")
        shared = {k: v for k, v in request.items() if k not in ("slots", "protocol", "task")}
        shared["staging_candidates_optional"] = routing["texts"]
        selected = {k: v for k, v in request["slots"][0].items() if k != "slot"}
        routed_backend = _LlamaPlannerBackend(lifecycle)
        routed_backend._call_seed = Backend._call_seed
        routed_backend.transport_policy = baseline_backend.transport_policy
        started = time.perf_counter()
        result, issues, retries, missing, recovered = request_entities(routed_backend,
            task="scene-author-performance", record_type="PERFORMANCE",
            entities=[PlannerEntity(args.scene, (1,), selected)], shared=shared,
            system_prompt=prompts["scene-author-performance"], runtime_config=config, interrupt_callback=None)
        if missing:
            save(output / "activity-inference.json", {"trace": routed_backend.trace, "missing": missing})
            raise RuntimeError(f"Incomplete routed performance: {missing}")
        prose, terminal = _split_terminal_state(result[(1,)])
        routed = replace(baseline, actions=((args.scene, 1, prose),), terminal_states=tuple(
            (s, event, terminal, cam) for s, event, state, cam in baseline.terminal_states))
        save(output / "activity-inference.json", {"content": routed.to_dict(), "trace": routed_backend.trace,
            "missing": missing, "issues": [str(i) for i in issues], "retries": retries,
            "recovered": recovered, "elapsed_s": time.perf_counter() - started})
        a = json.loads(request["payload"]) if "payload" in request else request
        b = json.loads(routed_backend.trace[0]["payload"])
        if {k: v for k, v in a.items() if k != "staging_candidates_optional"} != {
                k: v for k, v in b.items() if k != "staging_candidates_optional"}:
            raise ValueError("A/B request contains a variable outside candidate routing")
        cache = {}
        p2 = Path(conditions["previous_comparison"])
        for row in json.loads((p2 / "activity-translation.json").read_text(encoding="utf-8")):
            cache[tuple(row["fragments"])] = tuple(row["translated"])
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
            runtime_config=replace(config, temperature=0.0, max_tokens=4096))

        class CachedTranslator:
            def __init__(self):
                self.translation_trace = []
                self.reused = False
            def translate(self, units):
                key = tuple(units)
                self.reused = key in cache
                value = cache[key] if self.reused else tuple(translator.translate(units))
                cache[key] = value
                return value
            def record_field_translation(self, **kwargs):
                self.translation_trace.append({**kwargs, "reused_saved_translation": self.reused})

        plans, traces = {}, {}
        for label, content in (("baseline", baseline), ("activity", routed)):
            actions, cameras = list(content.actions), list(content.cameras)
            for item in template.scenes:
                if item.scene_number != args.scene:
                    for index, _ in enumerate(item.shots, 1):
                        actions.append((item.scene_number, index, "検証対象外。"))
                        cameras.append((item.scene_number, index, "検証対象外。"))
            emd = render_planner_content(content=replace(content, actions=tuple(actions), cameras=tuple(cameras)),
                concept_emd=concept, scene_emd=scene_emd, template=template, direction=direction,
                lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1)
            (output / f"{label}.md").write_text(emd.text, encoding="utf-8")
            cached = CachedTranslator()
            compiled = compile_ref2va(emd.text, cached)
            for index, shot in enumerate(compiled.plan["shots"], 1):
                shot["seed"] = 20261003 + index
            save(output / f"{label}-plan.json", compiled.plan)
            save(output / f"{label}-translation.json", cached.translation_trace)
            plans[label], traces[label] = compiled.plan, cached.translation_trace
        field = f"scene.{args.scene - 1}.shot.0.body.{1 if baseline.events else 0}"
        old_row = next(r for r in traces["baseline"] if r["field_id"] == field)
        new_row = next(r for r in traces["activity"] if r["field_id"] == field)
        if old_row["restored"] != new_row["restored"]:
            verify_body_only_plan(plans["baseline"], plans["activity"], args.scene, old_row["restored"], new_row["restored"])
        elif plans["baseline"] != plans["activity"]:
            raise ValueError("Unexpected Plan difference despite equal performance")
        save(output / "conditions.json", {**conditions, "scene_start": args.scene, "scene_length": 1,
            "target_scene": args.scene, "source_window_ms": [scene.start_ms, scene.end_ms],
            "comparison": "same scoped pool content; only Performance sees all versus PCM-routed pools",
            "original_role_calls": 2, "routed_role_calls": 1, "camera_replayed": True,
            "prior_context": "fresh isolated Scene; no generated predecessor", "routing": routing,
            "scope": "only Scene 11 is renderable; other Scenes are placeholders"})
        print("P5 A/B ready; Event, Camera, globals and seed protected", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    main()
