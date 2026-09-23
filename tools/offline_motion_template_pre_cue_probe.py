"""Offline A/B probe: combine Direction motion and user templates before Cue generation.

This intentionally leaves the production Planner, EMD schema, and workflows unchanged.
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

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.engine import _Entity, _parse_cue_card
from core.planner.scene_spine import (
    parse_scene_spine_step,
    validate_contact_coverage,
    validate_scene_spine,
)
from core.protocols.llm_records import parse_llm_records
from nodes.node_timeline_planner.node import _LlamaPlannerBackend
from tools.offline_motion_template_input_probe import parse_motion_templates

SOURCE = ROOT / "docs/assets/research/choreography-full-run-v4-2026-09-22/evidence.json"
TEMPLATES = ROOT / "docs/assets/research/motion-template-input-probe-2026-09-22/motion_templates.emd.md"
CUE_PROMPT = ROOT / "prompts/timeline_planner_visual_beats_bounded_system_prompt.txt"
SPINE_PROMPT = ROOT / "prompts/timeline_planner_scene_spine_system_prompt.txt"
SCENES = (11, 14)
INTEGRATION_RULE = (
    "\nmotion_templatesはユーザーが提示した身体経路の任意候補である。現在slotの歌詞、"
    "Directionのmotion、候補を同時に読み、対象・根拠・配置・可視展開を先に決めてから、"
    "身体主導と終端へSceneに合う一続きの動きを書く。候補は選択、融合、改変、不使用の"
    "いずれも可能。候補を新しい場所・小道具・接触対象・外部現象の根拠にしない。"
    "接触を選んだら可視展開に実際の到達と接触を残し、外部自律の現象は人物から独立させる。"
    "候補全文を写さず、全slotで同じ身体経路を繰り返さない。出力形式は変えない。\n"
)


def _saved_requests(trace: list[dict], task: str) -> dict[int, dict]:
    selected: dict[int, dict] = {}
    for entry in trace:
        if entry.get("task") != task:
            continue
        payload = json.loads(entry["payload"])
        if task == "visual-beats":
            numbers = {slot.get("scene_number") for slot in payload.get("slots", ())}
            for scene in SCENES:
                if scene in numbers and scene not in selected and "retry" not in payload:
                    selected[scene] = entry
        elif payload.get("scene_number") in SCENES and "retry" not in payload:
            selected.setdefault(payload["scene_number"], entry)
    if set(selected) != set(SCENES):
        raise ValueError(f"saved trace lacks {task} for selected scenes")
    return selected


def _parse_cues(raw: str, payload: dict) -> dict:
    slots = [int(slot["slot"]) for slot in payload["slots"]]
    parsed = parse_llm_records(
        raw,
        allowed_slots={"BEAT": frozenset(slots)},
        required=frozenset(("BEAT", slot) for slot in slots),
    )
    by_slot = {record.slot: record.text for record in parsed.records if record.record_type == "BEAT"}
    cards: dict[str, dict] = {}
    for slot in payload["slots"]:
        number = int(slot["slot"])
        if number not in by_slot:
            continue
        card = _parse_cue_card(
            _Entity(slot["scene_number"], (number,), slot), by_slot[number]
        )
        cards[str(slot["scene_number"])] = {
            "slot": number, "text": by_slot[number], "card": card.to_dict(),
        }
    return {
        "issues": [issue.reason for issue in parsed.issues],
        "missing": [list(item) for item in parsed.missing],
        "cards": cards,
        "valid": not parsed.issues and not parsed.missing
        and len(cards) == len(slots)
        and all(item["card"]["valid"] for item in cards.values()),
    }


def _parse_spine(raw: str, payload: dict) -> dict:
    slots = [int(slot["slot"]) for slot in payload["slots"]]
    parsed = parse_llm_records(
        raw,
        allowed_slots={"SPINE": frozenset(slots)},
        required=frozenset(("SPINE", slot) for slot in slots),
    )
    result = {
        "issues": [issue.reason for issue in parsed.issues],
        "missing": [list(item) for item in parsed.missing],
        "texts": {str(record.slot): record.text for record in parsed.records},
        "valid": False,
    }
    if result["issues"] or result["missing"]:
        return result
    try:
        by_slot = {record.slot: record.text for record in parsed.records}
        steps = tuple(parse_scene_spine_step(by_slot[slot]) for slot in slots)
        validate_scene_spine(steps)
        validate_contact_coverage(
            steps, contact_allowed=payload["visual_beat_grounding"]["contact"] == "許可"
        )
        result["steps"] = [step.to_dict() for step in steps]
        result["valid"] = True
    except (KeyError, ValueError) as exc:
        result["validation_error"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--templates", type=Path, default=TEMPLATES)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43])
    parser.add_argument("--skip-spine", action="store_true")
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    source = json.loads(source_bytes)
    template_bytes = args.templates.read_bytes()
    templates = parse_motion_templates(template_bytes.decode("utf-8"))
    if not templates:
        raise ValueError("at least one motion template is required")
    model = Path(source["model"])
    runtime = LlamaRuntimeConfig(**source["runtime"])
    cues = _saved_requests(source["trace"], "visual-beats")
    spines = _saved_requests(source["trace"], "scene-spine")
    cue_prompt = CUE_PROMPT.read_text(encoding="utf-8")
    spine_prompt = SPINE_PROMPT.read_text(encoding="utf-8")
    evidence = {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "templates_sha256": hashlib.sha256(template_bytes).hexdigest(),
        "cue_prompt_sha256": hashlib.sha256(cue_prompt.encode()).hexdigest(),
        "spine_prompt_sha256": hashlib.sha256(spine_prompt.encode()).hexdigest(),
        "model": str(model), "runtime": runtime.to_dict(),
        "seeds": args.seeds, "scenes": SCENES,
        "rule": INTEGRATION_RULE, "templates": list(templates), "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "evidence.json"
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    try:
        lifecycle.ensure_loaded(model, runtime)
        for seed in args.seeds:
            config = replace(runtime, seed=seed, max_tokens=min(runtime.max_tokens, 1536))
            for scene in SCENES:
                original_cue = json.loads(cues[scene]["payload"])
                for variant in ("baseline", "pre_cue_templates"):
                    payload = json.loads(json.dumps(original_cue, ensure_ascii=False))
                    if variant == "pre_cue_templates":
                        payload["motion_templates"] = list(templates)
                    started = time.perf_counter()
                    raw = backend.complete_planner(
                        task="visual-beats",
                        system_prompt=cue_prompt + (INTEGRATION_RULE if variant != "baseline" else ""),
                        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        config=config,
                    )
                    parsed = _parse_cues(raw, payload)
                    item = {
                        "seed": seed, "scene_number": scene, "variant": variant,
                        "task": "visual-beats", "payload": payload, "response": raw,
                        "parsed": parsed,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                    }
                    evidence["runs"].append(item)
                    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print(f"seed={seed} scene={scene} cue={variant} valid={parsed['valid']} elapsed={item['elapsed_seconds']}s", flush=True)
                    if args.skip_spine or not parsed["valid"]:
                        continue
                    card = parsed["cards"][str(scene)]
                    spine_payload = json.loads(spines[scene]["payload"])
                    spine_payload["visual_beat"] = card["text"]
                    spine_payload["visual_beat_grounding"] = card["card"]
                    started = time.perf_counter()
                    spine_raw = backend.complete_planner(
                        task="scene-spine", system_prompt=spine_prompt,
                        payload=json.dumps(spine_payload, ensure_ascii=False, separators=(",", ":")),
                        config=replace(config, max_tokens=min(config.max_tokens, 768)),
                    )
                    spine_parsed = _parse_spine(spine_raw, spine_payload)
                    spine_item = {
                        "seed": seed, "scene_number": scene, "variant": variant,
                        "task": "scene-spine", "payload": spine_payload,
                        "response": spine_raw, "parsed": spine_parsed,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                    }
                    evidence["runs"].append(spine_item)
                    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print(f"seed={seed} scene={scene} spine={variant} valid={spine_parsed['valid']} elapsed={spine_item['elapsed_seconds']}s", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
