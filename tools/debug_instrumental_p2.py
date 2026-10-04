"""Paired interlude/vocal-return probe with a shared, replayed predecessor.

Only the selected Scenes are rendered. Other completed-EMD rows are explicit
test placeholders to preserve the production splitter's full-song PCM clock.
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
from core.planner.section_context import section_context_by_scene
from core.planner.template import PlannerTemplate, parse_template_emd
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy
from nodes.node_emd_compiler.node import _system_prompt


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("alignment", "model", "reference_emd", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    template = parse_template_emd((args.alignment / "template.md").read_text(encoding="utf-8"))
    diagnostic = json.loads((args.alignment / "activity.json").read_text(encoding="utf-8"))
    gap = max((g for g in diagnostic["long_gaps"] if g["position"] == "internal"),
              key=lambda g: g["end_sample"] - g["start_sample"])
    return_ms = gap["end_sample"] * 1000 / diagnostic["sample_rate"]
    target_index = next(i for i,s in enumerate(template.scenes) if s.start_ms <= return_ms < s.end_ms)
    if target_index == 0:
        raise ValueError("Selected vocal return has no preceding Scene")
    predecessor, target = template.scenes[target_index-1:target_index+1]
    # Original Scene numbers/timecodes are intentionally kept until the normal
    # Scene Debug Splitter performs frame-exact Plan and PCM slicing.
    reference = args.reference_emd.read_text(encoding="utf-8-sig")
    concept = reference.split("\n# シーン設定", 1)[0].strip() + "\n"
    scene_emd = reference.split("# シーン設定", 1)[1].split("# 共通プロンプト", 1)[0]
    scene_emd = "# シーン設定" + scene_emd
    direction = DirectionArtifact(motion_profile_id="anime_scene_author_mv", motion_templates=(),
        environment_direction=("秋の山稜と谷、岩場や滝がある自然の空間。",),
        motion_direction=("伴奏と歌詞の感情に呼応した明瞭な身体フレーズを選ぶ。",),
        staging_candidates=(
            "伴奏が続く場面で、人物は短く荷重を移し、胸郭から腕へ弧を渡す。一拍のアクセント後に手をほどき、異なる姿勢で余韻を残す。",
            "歌唱へ戻る場面で、流れていた手を胸前で受け止め、顔を上げて視線を結び、呼吸から歌へ自然につなぐ。"))
    config = LlamaRuntimeConfig(n_ctx=16384, max_tokens=2048, gpu_layers=-1,
        n_batch=512, temperature=0.2, top_p=0.9, repetition_penalty=1.05, seed=20261003)
    contexts = section_context_by_scene(template)
    prefix_responses = {}
    class PairedBackend(_LlamaPlannerBackend):
        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            request = json.loads(payload.split("\0", 1)[0])
            material = f"{base_seed}/{request['scene_number']}/{task}/{call_number}"
            return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1

        def complete_planner(self, *, task, payload, **kwargs):
            request = json.loads(payload)
            request["section_lyric_context"] = contexts[request["scene_number"]]
            if request["scene_number"] == predecessor.scene_number and task in prefix_responses:
                response = prefix_responses[task]
                # Keep call numbering equal in both downstream conditions.
                self._task_calls[task] = self._task_calls.get(task, 0) + 1
                self._primary_calls[task] = self._primary_calls.get(task, 0) + 1
                self.trace.append({"task": task, "payload": request, "response": response,
                                   "replayed_common_predecessor": True})
                return response
            response = super().complete_planner(task=task,
                payload=json.dumps(request, ensure_ascii=False), **kwargs)
            if request["scene_number"] == predecessor.scene_number:
                prefix_responses[task] = response
            return response
    lifecycle = LlamaCppLifecycle()
    prompts = _system_prompts()
    plans = {}
    try:
        lifecycle.ensure_loaded(args.model, config)
        for enabled in (False, True):
            label = "activity" if enabled else "baseline"
            backend = PairedBackend(lifecycle)
            backend.transport_policy = _planner_transport_policy(str(args.model))
            start = time.perf_counter()
            subset = PlannerTemplate((predecessor, target), template.audio_activity if enabled else None)
            content, missing = generate_planner_content(backend, template=subset,
                concept_emd=concept, scene_emd=scene_emd, direction=direction,
                lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
                system_prompts=prompts, runtime_config=config)
            save(output / f"{label}-inference.json", {"content": content.to_dict() if content else None,
                "missing": missing, "trace": backend.trace, "elapsed_s": time.perf_counter()-start})
            if content is None or missing:
                raise RuntimeError(f"Incomplete {label}: {missing}")
            actions = list(content.actions)
            cameras = list(content.cameras)
            for scene in template.scenes:
                if scene.scene_number not in (predecessor.scene_number, target.scene_number):
                    for index, _ in enumerate(scene.shots, 1):
                        actions.append((scene.scene_number, index, "検証対象外。"))
                        cameras.append((scene.scene_number, index, "検証対象外。"))
            full_content = replace(content, actions=tuple(actions), cameras=tuple(cameras))
            emd = render_planner_content(content=full_content, concept_emd=concept, scene_emd=scene_emd,
                template=PlannerTemplate(template.scenes, template.audio_activity if enabled else None),
                direction=direction, lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
                lip_sync_audio_slot=1)
            (output / f"{label}.md").write_text(emd.text, encoding="utf-8")
            translation_config = replace(config, max_tokens=4096, temperature=0.0)
            translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(), runtime_config=translation_config)
            compiled = compile_ref2va(emd.text, translator)
            for index, shot in enumerate(compiled.plan["shots"], 1):
                shot["seed"] = 20261003 + index
            save(output / f"{label}-plan.json", compiled.plan)
            save(output / f"{label}-translation.json", translator.translation_trace)
            plans[label] = compiled.plan
            print(f"{label} completed: {time.perf_counter()-start:.1f}s", flush=True)
    finally:
        lifecycle.clear()
    a, b = (plans[label]["shots"][target_index-1] for label in ("baseline", "activity"))
    if a != b:
        raise ValueError("Common predecessor compiled Plan differs; do not render")
    save(output / "conditions.json", {"model": str(args.model), "runtime": config.to_dict(),
        "direction": direction.to_dict(), "source_alignment": str(args.alignment),
        "scene_start": predecessor.scene_number, "scene_length": 2,
        "target_scene": target.scene_number, "source_window_ms": [predecessor.start_ms, target.end_ms],
        "vocal_return_ms": return_ms, "common_predecessor_plan_equal": True,
        "comparison": "Only target Scene audio_activity differs; common predecessor responses replayed",
        "scope": "other Scenes contain test placeholders and MUST NOT be rendered",
        "reference_emd": str(args.reference_emd), "video_generated": False})
    print("P2 Plan pair ready", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    main()
