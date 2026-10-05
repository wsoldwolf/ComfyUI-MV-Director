"""Opt-in GPU probe: retain P2 prefix and candidates, change only system prompts.

Reports and generated files belong outside the repository. The saved full Plan
contains test placeholders; only its two selected Scenes may be rendered.
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
from core.planner.api import generate_planner_content, render_planner_content
from core.planner.section_context import section_context_by_scene
from core.planner.template import PlannerTemplate, parse_template_emd
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy
from nodes.node_emd_compiler.node import _system_prompt


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = args.previous.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory; saved runs are not overwritten")
    output.mkdir(parents=True, exist_ok=True)
    conditions = json.loads((previous / "conditions.json").read_text(encoding="utf-8"))
    template = parse_template_emd((Path(conditions["source_alignment"]) / "template.md").read_text(encoding="utf-8"))
    predecessor, target = template.scenes[conditions["scene_start"]-1:conditions["scene_start"]+1]
    old = json.loads((previous / "activity-inference.json").read_text(encoding="utf-8"))
    prefix = {}
    old_event_request = None
    for row in old["trace"]:
        request = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        if request["scene_number"] == predecessor.scene_number:
            prefix[row["task"]] = row["response"]
        elif row["task"] == "scene-author-event":
            old_event_request = request
    if len(prefix) != 3 or old_event_request is None:
        raise ValueError("Saved P2 three-role predecessor is incomplete")
    direction = DirectionArtifact.from_dict(conditions["direction"])
    config = LlamaRuntimeConfig(**conditions["runtime"])
    contexts = section_context_by_scene(template)
    reference = Path(conditions["reference_emd"]).read_text(encoding="utf-8-sig")
    concept = reference.split("\n# シーン設定", 1)[0].strip() + "\n"
    scene_emd = "# シーン設定" + reference.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
    prompts = _system_prompts()
    save(output / "system-prompts.json", prompts)
    lifecycle = LlamaCppLifecycle()

    class Backend(_LlamaPlannerBackend):
        replay_prefix = True

        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            request = json.loads(payload.split("\0", 1)[0])
            material = f"{base_seed}/{request['scene_number']}/{task}/{call_number}"
            return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1

        def complete_planner(self, *, task, payload, **kwargs):
            request = json.loads(payload)
            request["section_lyric_context"] = contexts[request["scene_number"]]
            if self.replay_prefix and request["scene_number"] == predecessor.scene_number:
                self._task_calls[task] = self._task_calls.get(task, 0) + 1
                self._primary_calls[task] = self._primary_calls.get(task, 0) + 1
                self.trace.append({"task": task, "payload": request, "response": prefix[task],
                                   "replayed_common_predecessor": True})
                return prefix[task]
            if self.replay_prefix and task == "scene-author-event" and request != old_event_request:
                raise ValueError("Target Event request differs from P2; do not call this a prompt-only comparison")
            return super().complete_planner(task=task, payload=json.dumps(request, ensure_ascii=False), **kwargs)

    try:
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        backend = Backend(lifecycle)
        backend.transport_policy = _planner_transport_policy(conditions["model"])
        started = time.perf_counter()
        content, missing = generate_planner_content(backend,
            template=PlannerTemplate((predecessor, target), template.audio_activity),
            concept_emd=concept, scene_emd=scene_emd, direction=direction,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            system_prompts=prompts, runtime_config=config)
        save(output / "activity-inference.json", {"content": content.to_dict() if content else None,
             "missing": missing, "trace": backend.trace, "elapsed_s": time.perf_counter()-started})
        if content is None or missing:
            raise RuntimeError(f"Incomplete prompt-only comparison: {missing}")
        actions, cameras = list(content.actions), list(content.cameras)
        for scene in template.scenes:
            if scene.scene_number not in (predecessor.scene_number, target.scene_number):
                for index, _ in enumerate(scene.shots, 1):
                    actions.append((scene.scene_number, index, "検証対象外。"))
                    cameras.append((scene.scene_number, index, "検証対象外。"))
        emd = render_planner_content(content=replace(content, actions=tuple(actions), cameras=tuple(cameras)),
            concept_emd=concept, scene_emd=scene_emd, template=template, direction=direction,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1)
        (output / "activity.md").write_text(emd.text, encoding="utf-8")
        translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(),
                                           runtime_config=replace(config, temperature=0.0, max_tokens=4096))
        cache = {}
        for row in json.loads((previous / "activity-translation.json").read_text(encoding="utf-8")):
            key, value = tuple(row["fragments"]), tuple(row["translated"])
            if key in cache and cache[key] != value:
                raise ValueError("Saved English fragments have conflicting translations")
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
        saved_plan = json.loads((previous / "activity-plan.json").read_text(encoding="utf-8"))
        index = predecessor.scene_number - 1
        if compiled.plan["shots"][index] != saved_plan["shots"][index]:
            raise ValueError("Common predecessor changed during compile")
        if compiled.plan["prompt_prefix"] != saved_plan["prompt_prefix"]:
            raise ValueError("Global prompt changed during compile")
        save(output / "activity-plan.json", compiled.plan)
        save(output / "activity-translation.json", cached.translation_trace)
        for original, dest in (("activity.md", "baseline.md"), ("activity-plan.json", "baseline-plan.json"),
                               ("activity-inference.json", "baseline-inference.json")):
            shutil.copy2(previous / original, output / dest)
        save(output / "conditions.json", {**conditions, "previous_comparison": str(previous),
             "comparison": "Both conditions have audio_activity; only the three Scene Author system prompts changed",
             "system_prompt_sha256": {task: hashlib.sha256(text.encode()).hexdigest() for task, text in prompts.items()}})
        print("Target Scene prompt-only comparison compiled; prefix and global prompt unchanged", flush=True)
        # Intro probe is prose-only and is not part of the rendered Plan pair.
        intro = Backend(lifecycle)
        intro.replay_prefix = False
        intro.transport_policy = _planner_transport_policy(conditions["model"])
        intro_content, intro_missing = generate_planner_content(intro,
            template=PlannerTemplate((template.scenes[0],), template.audio_activity),
            concept_emd=concept, scene_emd=scene_emd, direction=direction,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            system_prompts=prompts, runtime_config=config)
        save(output / "intro-inference.json", {"content": intro_content.to_dict() if intro_content else None,
             "missing": intro_missing, "trace": intro.trace})
        print(f"Intro probe finished: missing={intro_missing}", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    main()
