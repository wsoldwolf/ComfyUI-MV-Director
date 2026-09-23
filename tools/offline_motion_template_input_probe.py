"""Compare optional user motion templates against saved Planner inputs.

This is an offline experiment. It does not alter the production Planner or EMD.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts.base import normalize_newlines
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.scene_spine import (
    parse_scene_spine_step, validate_contact_coverage, validate_scene_spine,
)
from core.protocols.llm_records import parse_llm_records
from nodes.node_timeline_planner.node import _LlamaPlannerBackend


SOURCE = ROOT / "docs/assets/research/choreography-full-run-v4-2026-09-22/evidence.json"
TEMPLATES = ROOT / "docs/assets/research/motion-template-input-probe-2026-09-22/motion_templates.emd.md"
SPINE_PROMPT = ROOT / "prompts/timeline_planner_scene_spine_system_prompt.txt"
ACTION_PROMPT = ROOT / "prompts/timeline_planner_actions_dance_phrase_system_prompt.txt"
SCENES = (2, 5, 11, 14)
PALETTE_SPINE_RULE = (
    "\nchoreography_paletteがある場合、候補は任意の着想であり、ID選択や逐語的再現は不要。"
    "歌詞とSceneの出来事に合う独自の身体経路を考案し、Shot間を連続させてよい。\n"
)
PALETTE_ACTION_RULE = (
    "\nchoreography_paletteは任意の着想であり、候補IDの選択や本文の再現は不要。"
    "歌詞・Cue・Camera・前Sceneの終端に適する独自の身体経路を自由に考案してよい。"
    "候補にある対象・場所・接触を歌詞の根拠なく追加しない。"
    "Scene Spineがあれば、その運動のFROM・ADVANCE・TOをShotで連続させる。\n"
)
LOCAL_RULE = (
    "\nmotion_templatesはユーザーの任意の身体経路候補であり、新しい場所・小道具・接触対象の根拠ではない。"
    "現在Sceneの歌詞、visual_beat_grounding、前Scene終端とShotの画角に合う候補を着想として使うか、"
    "合わなければ独自の身体経路を作る。候補の始点姿勢から毎Shot再開しない。"
    "選択番号や候補本文を出力せず、Scene内の準備・アクセント・終端を既存の応答形式で具体化する。\n"
)


def parse_motion_templates(raw: str) -> tuple[str, ...]:
    """Parse one bullet per template, without assigning semantic IDs."""

    if not isinstance(raw, str):
        raise TypeError("motion templates must be text")
    lines = normalize_newlines(raw.lstrip("\ufeff")).split("\n")
    nonempty = [(number, line) for number, line in enumerate(lines, 1) if line.strip()]
    if not nonempty:
        return ()
    if nonempty[0][1].strip() != "# モーションテンプレート":
        raise ValueError("motion templates must start with '# モーションテンプレート'")
    result: list[str] = []
    for number, line in nonempty[1:]:
        if not line.startswith("* ") or not line[2:].strip():
            raise ValueError(f"motion template line {number} is not a nonempty bullet")
        result.append(line[2:].strip())
    return tuple(result)


def _parse_records(raw: str, kind: str, slots: list[int], *, contact: bool = False) -> dict:
    allowed = frozenset(slots)
    parsed = parse_llm_records(
        raw, allowed_slots={kind: allowed},
        required=frozenset((kind, slot) for slot in slots),
    )
    result: dict = {
        "issues": [issue.reason for issue in parsed.issues],
        "missing": [list(item) for item in parsed.missing],
        "texts": {str(record.slot): record.text for record in parsed.records},
    }
    if kind != "SPINE" or result["issues"] or result["missing"]:
        result["valid"] = not result["issues"] and not result["missing"]
        return result
    try:
        values = {record.slot: record.text for record in parsed.records}
        steps = tuple(parse_scene_spine_step(values[slot]) for slot in slots)
        validate_scene_spine(steps)
        validate_contact_coverage(steps, contact_allowed=contact)
        result["steps"] = [step.to_dict() for step in steps]
        result["valid"] = True
    except (KeyError, ValueError) as exc:
        result["valid"] = False
        result["validation_error"] = str(exc)
    return result


def _original_spine_requests(trace: list[dict]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for entry in trace:
        if entry.get("task") != "scene-spine":
            continue
        payload = json.loads(entry["payload"])
        scene = payload.get("scene_number")
        if scene in SCENES and scene not in result and "retry" not in payload:
            result[scene] = entry
    if set(result) != set(SCENES):
        raise ValueError("saved trace is missing one of the selected Scenes")
    return result


def _single_shot_action(trace: list[dict]) -> tuple[dict, dict]:
    for entry in trace:
        if entry.get("task") != "actions":
            continue
        payload = json.loads(entry["payload"])
        for slot in payload.get("slots", []):
            if slot.get("scene_number") == 16 and slot.get("scene_shot_count") == 1:
                payload["slots"] = [slot]
                return entry, payload
    raise ValueError("saved trace lacks Scene 16 single-Shot Action")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--templates", type=Path, default=TEMPLATES)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenes", type=int, nargs="+", default=list(SCENES))
    parser.add_argument("--cue-body-ablation", action="store_true")
    parser.add_argument("--skip-single", action="store_true")
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8"))
    templates = parse_motion_templates(args.templates.read_text(encoding="utf-8"))
    if not templates:
        raise ValueError("experiment requires at least one template")
    config = LlamaRuntimeConfig(**source["runtime"])
    config = replace(config, seed=args.seed)
    spine_prompt = SPINE_PROMPT.read_text(encoding="utf-8")
    action_prompt = ACTION_PROMPT.read_text(encoding="utf-8")
    spine_requests = _original_spine_requests(source["trace"])
    action_entry, action_request = _single_shot_action(source["trace"])
    evidence = {
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "templates_sha256": hashlib.sha256(args.templates.read_bytes()).hexdigest(),
        "model": str(args.model.resolve()),
        "runtime": config.to_dict(),
        "templates": list(templates),
        "scope": {"scenes": args.scenes, "single_shot": not args.skip_single,
                  "cue_body_ablation": args.cue_body_ablation},
        "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene in args.scenes:
            original = spine_requests[scene]
            base = json.loads(original["payload"])
            if args.cue_body_ablation:
                base["visual_beat_grounding"]["body_driver"] = ""
                base["visual_beat_grounding"]["final_state"] = ""
            slots = [int(item["slot"]) for item in base["slots"]]
            contact = base["visual_beat_grounding"]["contact"] == "許可"
            for variant in ("baseline", "palette", "local"):
                payload = json.loads(json.dumps(base, ensure_ascii=False))
                if variant != "palette":
                    payload.pop("choreography_palette", None)
                if variant == "local":
                    payload["motion_templates"] = [
                        {"number": index, "body_path": value}
                        for index, value in enumerate(templates, 1)
                    ]
                prompt = spine_prompt + (
                    PALETTE_SPINE_RULE if variant == "palette" else
                    LOCAL_RULE if variant == "local" else ""
                )
                started = time.perf_counter()
                if variant == "palette" and args.seed == 42 and not args.cue_body_ablation:
                    raw = original["response"]
                    origin = "saved_production_trace"
                else:
                    raw = backend.complete_planner(
                        task="scene-spine", system_prompt=prompt,
                        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        config=replace(config, max_tokens=min(config.max_tokens, max(512, 192 * len(slots) + 128))),
                    )
                    origin = "offline_inference"
                record = {
                    "scene_number": scene, "task": "scene-spine", "variant": variant,
                    "origin": origin, "payload": payload, "response": raw,
                    "parsed": _parse_records(raw, "SPINE", slots, contact=contact),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
                evidence["runs"].append(record)
                args.output.joinpath("evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print(f"scene={scene} variant={variant} valid={record['parsed']['valid']} "
                      f"elapsed={record['elapsed_seconds']}s", flush=True)

        if args.skip_single:
            return 0
        slot = action_request["slots"][0]
        for variant in ("baseline", "palette", "local"):
            payload = json.loads(json.dumps(action_request, ensure_ascii=False))
            if variant != "palette":
                payload.pop("choreography_palette", None)
            if variant == "local":
                payload["motion_templates"] = [
                    {"number": index, "body_path": value}
                    for index, value in enumerate(templates, 1)
                ]
            prompt = action_prompt + (
                PALETTE_ACTION_RULE if variant == "palette" else
                LOCAL_RULE if variant == "local" else ""
            )
            started = time.perf_counter()
            raw = backend.complete_planner(
                task="actions", system_prompt=prompt,
                payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                config=replace(config, max_tokens=min(config.max_tokens, 512)),
            )
            record = {
                "scene_number": 16, "task": "single-shot-action", "variant": variant,
                "origin": "offline_inference", "payload": payload, "response": raw,
                "parsed": _parse_records(raw, "ACTION", [int(slot["slot"])]),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
            evidence["runs"].append(record)
            args.output.joinpath("evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"scene=16 variant={variant} valid={record['parsed']['valid']} "
                  f"elapsed={record['elapsed_seconds']}s", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
