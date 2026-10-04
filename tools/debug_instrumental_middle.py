"""Research: change only Scene 12 Performance in the connected B19 clip.

Rehydrate the saved predecessor state without changing its words. Fixed EMD
fields otherwise clear that state on re-entry. Reject any other payload drift.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts
from tools.debug_momentum_pipeline import production_inputs, infer
from tools.debug_instrumental_chain import connected_plan
from tools.debug_shot_duration import verify_pcm
from tools.prepare_beat_motion_h3 import read, save, finalize, FFMPEG
from tools.prepare_instrumental_h3 import render

RUN_NAME = "instrumental-middle-b20-momiji2-s11-13-20261004"
USER_REQUEST = """# 演出候補
* 99.375〜110.000秒の伴奏の中盤で、片足へ荷重して膝を短く曲げ、腰に続いて胸郭を斜めへ向ける。左腕を胸前から大きく外側へほどき、肩と袖がその動きに遅れて流れる。踏み替えて身体の向きを正面へ戻す途中で、次の腰と胸郭の捻りへつなぐ。膝の溜め、体幹の捻り、左腕の展開を一続きのフレーズとして伴奏中も繰り出す。剣は右手で握り続け、身体の向きに合わせて腕と一緒に運ぶ。
"""


def rehydrate_payload(payload, baseline, candidates):
    """Restore original state; all other ordinary first-call input must match."""
    request = json.loads(payload)
    if request.get("scene_number") != 12 or request.get("continuation") is not True:
        raise ValueError("Requires continuing Scene 12")
    if request.get("previous_scene_state"):
        raise ValueError("Unexpected new predecessor state")
    if request.get("staging_candidates_optional") != list(candidates):
        raise ValueError("Unexpected candidate")
    state = baseline.get("previous_scene_state")
    if not isinstance(state, str) or not state:
        raise ValueError("Saved predecessor state is missing")
    expected = deepcopy(baseline)
    expected["previous_scene_state"] = ""
    expected["staging_candidates_optional"] = list(candidates)
    if request != expected:
        differing = sorted(k for k in request.keys() | expected.keys()
                           if request.get(k) != expected.get(k))
        raise ValueError(f"Unexpected Planner payload drift: {differing}")
    request["previous_scene_state"] = state
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verify_plan(baseline, candidate, old_performance, new_performance, index=11):
    if not new_performance.strip():
        raise ValueError("Empty new Performance")
    expected = deepcopy(baseline)
    lines = expected["shots"][index]["prompt"]
    if sum(line.count(old_performance) for line in lines) != 1:
        raise ValueError("Saved Performance is not unique in target Scene")
    expected["shots"][index]["prompt"] = [
        line.replace(old_performance, new_performance, 1) for line in lines]
    if candidate != expected:
        raise ValueError("Plan changed outside Scene 12 Performance")


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    media, evidence = read(source / "media-checks.json"), read(source / "inference.json")
    if not Path(media["video"]).is_file():
        raise ValueError("Completed baseline video is missing")
    records = [row for row in evidence["trace"]
               if row["task"] == "scene-author-performance"
               and json.loads(row["payload"])["scene_number"] == 12]
    if len(records) != 1:
        raise ValueError("Requires one saved primary Scene 12 call")
    capsule = json.loads(records[0]["payload"])
    if capsule.get("retry"):
        raise ValueError("Requires an unretried primary request")
    state = next(row[2] for row in evidence["content"]["terminal_states"] if row[0] == 11)
    if capsule["previous_scene_state"] != state:
        raise ValueError("Saved predecessor state mismatch")
    text = (source / "dance.md").read_text(encoding="utf-8")
    template, direction, concept, scene_emd = production_inputs(
        text, USER_REQUEST, target_scene=12, preserve_continuation=True)
    baseline = read(source / "compiled-full-plan.json")
    connected_plan(baseline)
    manifest = read(source / "h3-manifest.json")
    verify_pcm(manifest, manifest["audio"])
    prompts, old_conditions = _system_prompts(), read(source / "conditions.json")
    hashes = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()}
    if hashes != old_conditions["system_prompt_sha256"]:
        raise ValueError("Production system prompts changed since baseline")

    # Capture the normal CPU request before any GPU use, and prove the new
    # request differs only in candidate and the cleared fixed-EMD state.
    from core.inference import LlamaRuntimeConfig
    from core.planner.api import generate_planner_content
    class Capture:
        def complete_planner(self, **kwargs):
            if kwargs["task"] != "scene-author-performance":
                raise ValueError("Unexpected reopened stage")
            rehydrate_payload(kwargs["payload"], capsule, direction.staging_candidates)
            return "PERFORMANCE\t1\t準備確認用。｜END_STATE=準備確認用"
    content, missing = generate_planner_content(
        Capture(), template=template, concept_emd=concept, scene_emd=scene_emd,
        direction=direction, system_prompts=prompts,
        runtime_config=LlamaRuntimeConfig(**old_conditions["runtime"]),
        lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
        staging_candidate_policy="optional")
    if missing or content is None or [row[:2] for row in content.actions] != [(12, 1)]:
        raise ValueError("CPU preparation reopened unexpected fields")

    output.mkdir(parents=True)
    for old, new in (("dance.md", "baseline.md"), ("dance-plan.json", "baseline-plan.json"),
                     ("h3-dance.json", "h3-baseline.json"), ("render-dance.json", "render-baseline.json")):
        shutil.copy2(source / old, output / new)
    (output / "input-emd.md").write_text(text, encoding="utf-8")
    (output / "user-request.md").write_text(USER_REQUEST, encoding="utf-8")
    save(output / "system-prompts.json", prompts)
    save(output / "baseline-request.json", capsule)
    save(output / "conditions.json", {
        "source": str(source), "model": old_conditions["model"], "runtime": old_conditions["runtime"],
        "scene": 12, "generated_slots": [[12, 1]], "preserve_continuation": True,
        "defer_delivery": True, "staging_candidate_policy": "optional", "compiler_max_tokens": 4096,
        "translation_cache": str(source / "translation.json"), "system_prompt_sha256": hashes,
        "research_saved_predecessor_state": state, "preceding_performance_call_count": 1})
    save(output / "input-contract.json", {
        "candidate": USER_REQUEST, "target_scene": 12, "normal_api_cpu_request_verified": True,
        "only_candidate_changes_after_saved_predecessor_rehydration": True,
        "previous_scene_state": state, "state_source": str(source / "inference.json"),
        "research_backend_adapter": "rehydrate saved Scene 11 LLM terminal; not a production feature",
        "fixed_fields": ["Scene 11 and 13 Performance", "Camera", "Event", "Subject", "PCM", "H3 seed", "timing", "H3 settings"],
        "semantic_prose_repair": False, "authored_english_insertion": False})
    save(output / "h3-manifest.json", {**manifest,
        "run_names": {"baseline": manifest["run_names"]["dance"], "dance": RUN_NAME},
        "comparison_titles": ["Previous connected clip", "Middle torso phrase"],
        "comparison_labels": ["baseline", "dance"], "baseline_render_reused": True,
        "source": str(source), "new_render_count": 1,
        "comparison": "Scene 12 Performance only; opening and ending prose fixed; same predecessor state"})
    print("CPU preparation verified; only Scene 12 will be inferred", flush=True)


def infer_middle(args):
    output = args.output.resolve(strict=True)
    capsule = read(output / "baseline-request.json")
    _, direction, _, _ = production_inputs(
        (output / "input-emd.md").read_text(encoding="utf-8"), USER_REQUEST,
        target_scene=12, preserve_continuation=True)
    class MiddleBackend(_LlamaPlannerBackend):
        def __init__(self, lifecycle):
            super().__init__(lifecycle)
            # Preserve the original Scene 12 ordinal in the normal seed path.
            self._task_calls["scene-author-performance"] = 1
            self.first = True
        def complete_planner(self, **kwargs):
            if kwargs["task"] != "scene-author-performance":
                raise ValueError("Unexpected stage")
            if self.first:
                kwargs["payload"] = rehydrate_payload(
                    kwargs["payload"], capsule, direction.staging_candidates)
                self.first = False
            else:
                request = json.loads(kwargs["payload"])
                if request.get("scene_number") != 12:
                    raise ValueError("Unexpected retry Scene")
                request["previous_scene_state"] = capsule["previous_scene_state"]
                kwargs["payload"] = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return super().complete_planner(**kwargs)
    infer(args, backend_factory=MiddleBackend)
    deliver(args)


def deliver(args):
    output = args.output.resolve(strict=True)
    if (output / "submission-dance.json").exists():
        raise ValueError("Already submitted")
    conditions = read(output / "conditions.json")
    source = Path(conditions["source"])
    translations = read(output / "translation.json")
    field = "scene.11.shot.0.body.2"
    old_row = next(r for r in read(source / "translation.json") if r["field_id"] == field)
    row = next(r for r in translations if r["field_id"] == field)
    if row["reused_saved_translation"]:
        raise ValueError("Expected a new Scene 12 Performance")
    verify_plan(read(source / "compiled-full-plan.json"), read(output / "compiled-full-plan.json"),
                old_row["restored"], row["restored"])
    plan = connected_plan(read(output / "compiled-full-plan.json"))
    verify_plan(read(output / "baseline-plan.json"), plan, old_row["restored"], row["restored"], index=1)
    uncached = read(output / "compiler-inference.json")["uncached_fields"]
    if uncached != [field]:
        raise ValueError(f"Unexpected retranslated fields: {uncached}")
    save(output / "dance-plan.json", plan)
    graph = read(output / "h3-baseline.json")
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(plan, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = graph["21"]["inputs"]["filename"] = RUN_NAME
    save(output / "h3-dance.json", graph)
    (output / "dance-excerpt.md").write_text(
        "# 中盤だけを変更した通常パイプライン出力\n\n## 演出候補\n\n" + USER_REQUEST
        + "\n## Plannerの実生成\n\n" + row["source"]
        + "\n\n## Compilerの実英訳\n\n" + row["restored"] + "\n", encoding="utf-8")
    save(output / "output-contract.json", {
        "full_and_connected_plan_scene12_performance_only_verified": True,
        "baseline_performance": old_row["restored"], "new_performance": row["restored"],
        "compiler_new_fields": uncached, "no_semantic_prose_repair": True,
        "fixed_opening_and_ending_prose": True,
        "note": "Scene 13 visuals may differ because generated predecessor context differs"})
    print("Plan verified: only Scene 12 Performance changed", flush=True)


def finalize_middle(args):
    finalize(args)
    output = args.output.resolve(strict=True)
    checks = read(output / "media-checks.json")
    for label, row in checks["videos"].items():
        cosine = row["render_audio_zero_offset_fullmix_cosine"]
        if cosine is None or cosine < 0.98:
            raise ValueError(f"Output fullmix alignment failed: {label}")
    # The reusable side-by-side contact sheet samples only the opening.
    # Sample the entire candidate to include the changed middle and the return.
    subprocess.run([FFMPEG, "-v", "error", "-i", checks["videos"]["dance"]["path"],
                    "-vf", "fps=1/2,scale=432:240,tile=5x3", "-frames:v", "1",
                    str(output / "middle-contact-sheet.png")], check=True)
    print("Both output audio tracks align; whole candidate sampled", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "infer", "deliver", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--url", default="http://127.0.0.1:8191")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.task == "prepare":
        if not args.source:
            p.error("prepare requires --source")
        prepare(args)
    elif args.task == "infer":
        infer_middle(args)
    elif args.task == "deliver":
        deliver(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize_middle(args)
