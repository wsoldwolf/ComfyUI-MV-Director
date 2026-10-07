"""P2 opt-in prop decision -> Performance -> selected derived Camera probe.

Never submitted to H3. Saved generated fields are reopened only by the explicit
Scene range; the first boundary Performance and Camera remain fixed. This tool
cannot identify author-owned fields from a completed EMD; do not use it as an
automatic production rewrite path.
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
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig, fit_context_budget
from core.planner.prop_decision import TASK, build_prop_decision_grammar, request_prop_decisions
from core.planner.prop_inventory import (TASK as INVENTORY_TASK, build_prop_inventory_grammar,
                                         request_prop_inventory)
from core.planner.requests import request_entities
from core.planner.scene_author import _split_terminal_state
from core.planner.types import PlannerEntity
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _planner_transport_policy
from tools.debug_prop_performance import prepare_inputs, replace_primary_performances, save


class ProbeBackend(_LlamaPlannerBackend):
    @staticmethod
    def _call_seed(base_seed, task, call_number, payload):
        request = json.loads(payload.split("\0", 1)[0])
        material = f"{base_seed}/{request['scene_number']}/{task}/{call_number}"
        return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1

    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        if task not in {TASK, INVENTORY_TASK}:
            return super().complete_planner(task=task, system_prompt=system_prompt,
                payload=payload, config=config, interrupt_callback=interrupt_callback)
        request = json.loads(payload)
        model_payload = "/no_think\n" + payload
        count = self.lifecycle.count_serialized_prompt(system_prompt + "\n" + model_payload)
        budget = fit_context_budget(count.count, min(config.max_tokens, 1536),
            self.lifecycle.effective_n_ctx or config.n_ctx,
            minimum_output_tokens=min(512, config.max_tokens), estimated=count.estimated)
        call = self._task_calls.get(task, 0) + 1
        self._task_calls[task] = call
        call_config = replace(config, max_tokens=budget.reserved_output_tokens,
            seed=self._call_seed(config.seed, task, call, payload))
        started = time.perf_counter()
        logging.info("Prop planning started; task=%s; scene=%s; tokens=%s; call=%s",
                     task, request["scene_number"], count.count, call)
        response = self.lifecycle.complete_chat(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": model_payload}], call_config,
            grammar=(build_prop_inventory_grammar() if task == INVENTORY_TASK
                     else build_prop_decision_grammar(request["slots"])),
            interrupt_callback=interrupt_callback)
        self.trace.append({"task": task, "payload": payload, "response": response,
                           "elapsed_s": time.perf_counter() - started})
        logging.info("Prop planning finished; task=%s; scene=%s; elapsed=%.2fs",
                     task, request["scene_number"], time.perf_counter() - started)
        return response


def reopen_cameras(shared, selected_shots):
    """Explicit diagnostic selection, never a guessed author/prose classification."""
    result = deepcopy(shared)
    for p in result["shot_positions"]:
        if p["shot"] in selected_shots:
            p["fixed_camera"] = ""
            p["author_body"] = [line for line in p["author_body"]
                                if not line.startswith("`カメラ` ")]
    result["saved_cameras_are_author_fixed"] = False
    return result


def replace_selected_cameras(text, replacements):
    scene = shot = 0
    seen, lines = set(), []
    for line in text.splitlines(keepends=True):
        match = re.match(r"> `シーン` (\d+)\s*$", line)
        if match:
            scene, shot = int(match.group(1)), 0
        if line.startswith("## ショット "):
            shot += 1
        key = (scene, shot)
        if line.startswith("* `カメラ` ") and key in replacements:
            if key in seen:
                raise ValueError("Probe cannot replace multiple Camera directives in a Shot")
            line = "* `カメラ` " + replacements[key] + "\n"
            seen.add(key)
        lines.append(line)
    if seen != set(replacements):
        raise ValueError("Could not assign all selected Camera fields")
    result = "".join(lines)
    before, after = parse_emd(text), parse_emd(result)
    normalized = []
    for a, b in zip(before.scenes, after.scenes):
        shots = []
        for i, (old, new) in enumerate(zip(a.shots, b.shots), 1):
            old_c = [d for d in old.directives if d.kind == "カメラ"]
            new_c = [d for d in new.directives if d.kind == "カメラ"]
            expected = replacements.get((a.scene_number, i))
            if expected is None and old_c != new_c:
                raise ValueError("Unselected Camera changed")
            if expected is not None and [d.text for d in new_c] != [expected]:
                raise ValueError("Camera assignment changed authored text")
            restored_body = tuple("`カメラ` " + old_c[0].text if t.startswith("`カメラ` ") else t
                                  for t in new.body)
            old_by_line = {d.line_number: d for d in old_c}
            restored_directives = tuple(old_by_line[d.line_number] if d.kind == "カメラ" else d
                                        for d in new.directives)
            shots.append(replace(new, body=restored_body, directives=restored_directives))
        normalized.append(replace(b, shots=tuple(shots)))
    if replace(after, scenes=tuple(normalized)) != before:
        raise ValueError("Non-Camera content changed")
    return result


def run_probe(backend, requests, prompts, config, *, camera_policy, inventory=None):
    if camera_policy not in {"fixed", "reopen_selected"}:
        raise ValueError("unknown Camera policy")
    previous_body = previous_prop = previous_camera = ""
    rows, performances, cameras = [], {}, {}
    for item in requests:
        shared = deepcopy(item["shared"])
        if inventory is not None:
            shared["prop_inventory"] = [dict(p) for p in inventory]
        selected = {e.key[0] for e in item["entities"]}
        if camera_policy == "reopen_selected":
            shared = reopen_cameras(shared, selected)
        else:
            shared["saved_cameras_are_author_fixed"] = True
        continuous = shared["continuation"]
        shared["previous_scene_state"] = previous_body if continuous else ""
        shared["previous_prop_state"] = previous_prop if continuous else ""
        shared["requested_shot_numbers"] = sorted(selected)
        positions = {p["shot"]: p for p in shared["shot_positions"]}
        active_entities = [replace(e, value={**e.value,
                           "position": deepcopy(positions[e.key[0]])})
                           for e in item["entities"]]
        decision = request_prop_decisions(backend, shared=shared,
            system_prompt=prompts["decision"], runtime_config=config)
        shared["accepted_prop_decisions"] = {str(i): dict(v) for i, v in decision.decisions.items()}
        result, issues, retries, missing, recovered = request_entities(backend,
            task="scene-author-performance", record_type="PERFORMANCE",
            entities=active_entities, shared=shared,
            system_prompt=prompts["performance"], runtime_config=config, interrupt_callback=None)
        if missing:
            raise RuntimeError(f"Incomplete Performance in Scene {item['scene_number']}: {missing}")
        actions, states = {}, {}
        for key, value in result.items():
            prose, state = _split_terminal_state(value)
            actions[str(key[0])], states[str(key[0])] = prose, state
            performances[(item["scene_number"], key[0])] = prose
        last = len(shared["shot_positions"])
        previous_body = states.get(str(last), "")
        # This is planned prop state, not a claim the Performance realized it.
        previous_prop = decision.decisions.get(last, {}).get("end_state", "")
        camera_results = {}
        if camera_policy == "reopen_selected":
            all_actions = {**shared["fixed_performances"], **actions}
            for i, supplements in item["supplements"].items():
                if i not in shared["fixed_performances"]:
                    all_actions[i] += " " + " ".join(supplements)
            camera_shared = {**shared, "accepted_performances": all_actions,
                "fixed_cameras": {str(p["shot"]): p["fixed_camera"]
                                  for p in shared["shot_positions"] if p["fixed_camera"]},
                "previous_scene_state": previous_camera if continuous else "",
                "arc_continuity": {"inherited_direction": "clockwise"},
                "arc_roll_policy": "selective_arc"}
            generated, _, _, camera_missing, _ = request_entities(backend,
                task="scene-author-camera", record_type="CAMERA", entities=active_entities,
                shared=camera_shared, system_prompt=prompts["camera"],
                runtime_config=config, interrupt_callback=None)
            if camera_missing:
                raise RuntimeError(f"Incomplete Camera: {camera_missing}")
            for key, value in generated.items():
                prose, state = _split_terminal_state(value)
                camera_results[str(key[0])] = prose
                cameras[(item["scene_number"], key[0])] = prose
                if key[0] == last:
                    previous_camera = state
        rows.append({"scene_number": item["scene_number"], "input": shared,
            "decision_status": decision.status, "decision_attempts": decision.attempts,
            "decisions": {str(i): dict(v) for i, v in decision.decisions.items()},
            "generated": actions, "terminal_states": states, "cameras": camera_results,
            "issues": len(issues), "retries": retries, "recovered": recovered})
    return rows, performances, cameras


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emd", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-start", type=int, default=15)
    parser.add_argument("--scene-length", type=int, default=3)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--inventory-first", action="store_true",
                        help="Extract Subject carryables once, then retain their IDs in every Shot")
    parser.add_argument("--camera-policies", nargs="+", choices=("fixed", "reopen_selected"),
                        default=["fixed", "reopen_selected"])
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    if args.scene_start < 1 or args.scene_length < 1:
        raise ValueError("Use positive Scene ranges")
    if not args.prepare_only and args.model is None:
        raise ValueError("Inference requires an explicit model")
    text = args.emd.read_text(encoding="utf-8-sig")
    requests = prepare_inputs(text, list(range(args.scene_start, args.scene_start + args.scene_length)))
    read = lambda name: (ROOT / "prompts" / name).read_text(encoding="utf-8").rstrip() + "\n"
    prompts = {"decision": read("experimental_prop_decision_system_prompt.txt"),
        "performance": read("timeline_planner_scene_author_performance_system_prompt.txt")
                       + read("experimental_prop_performance_addendum.txt"),
        "camera": read("timeline_planner_scene_author_camera_system_prompt.txt")}
    if args.inventory_first:
        prompts["inventory"] = read("experimental_prop_inventory_system_prompt.txt")
    config = LlamaRuntimeConfig(n_ctx=16384, n_batch=256, max_tokens=1536, seed=20261007)
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output / "inputs.json", [{**r, "entities": [e.value for e in r["entities"]]}
                                      for r in requests])
    for key, prompt in prompts.items():
        (args.output / f"{key}-system.txt").write_text(prompt, encoding="utf-8")
    (args.output / "source-emd.md").write_text(text, encoding="utf-8")
    save(args.output / "conditions.json", {"source_emd": str(args.emd.resolve()),
        "source_sha256": hashlib.sha256(args.emd.read_bytes()).hexdigest(),
        "model": str(args.model.resolve()) if args.model else None, "runtime": config.to_dict(),
        "scene_numbers": [r["scene_number"] for r in requests],
        "camera_policies": args.camera_policies, "h3_generated": False,
        "prop_decision_schema": "diagnostic_v4_stable_inventory_ids" if args.inventory_first else "diagnostic_v3_inventory_objects",
        "inventory_first": args.inventory_first,
        "boundary_first_performance_and_camera_fixed": True,
        "staging_candidates_replayed": False, "supplements_fixed_and_exposed_pre_author": True,
        "prop_decision_transport_is_not_semantic_approval": True})
    if args.prepare_only:
        print("CPU preparation passed; no model loaded", flush=True)
        return
    lifecycle = LlamaCppLifecycle()
    try:
        model = lifecycle.ensure_loaded(args.model, config)
        inventory = None
        if args.inventory_first:
            backend = ProbeBackend(lifecycle)
            started = time.perf_counter()
            inventory_result = request_prop_inventory(backend,
                subject_emd=requests[0]["shared"]["subject_emd"],
                fixed_boundary=requests[0]["shared"]["fixed_performances"],
                scene_number=requests[0]["scene_number"], system_prompt=prompts["inventory"],
                runtime_config=config)
            save(args.output / "inventory-inference.json", {
                "props": inventory_result.props, "status": inventory_result.status,
                "attempts": inventory_result.attempts, "trace": backend.trace,
                "elapsed_s": time.perf_counter() - started})
            if inventory_result.status == "transport_valid":
                inventory = inventory_result.props
            else:
                logging.warning("Inventory transport invalid; ordinary diagnostic decision path retained")
        for policy in dict.fromkeys(args.camera_policies):
            model.reset()
            backend = ProbeBackend(lifecycle)
            backend.transport_policy = _planner_transport_policy(args.model.name)
            started = time.perf_counter()
            rows, actions, cameras = run_probe(backend, requests, prompts, config,
                                             camera_policy=policy, inventory=inventory)
            save(args.output / f"{policy}-inference.json", {"scenes": rows,
                "trace": backend.trace, "elapsed_s": time.perf_counter() - started})
            emd = replace_primary_performances(text, actions)
            emd = replace_selected_cameras(emd, cameras)
            (args.output / f"{policy}-emd.md").write_text(emd, encoding="utf-8")
            print(f"{policy} completed in {time.perf_counter() - started:.2f}s", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    main()
