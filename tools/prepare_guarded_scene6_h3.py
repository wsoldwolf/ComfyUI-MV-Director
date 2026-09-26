"""Prepare Scene 6 H3 A/B from a frozen Plan, removing only one composition."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


RESEARCH = Path(r"E:\ComfyUI\projects\ComfyUI-MV-Director-research\docs\assets\research")
BASE = RESEARCH / "gemma4-31b-composition-audit-h3-s15-2026-09-25"
SOURCE_PLAN = BASE / "current" / "plan.json"
SOURCE_TRACE = BASE / "current" / "compile-summary.json"
SOURCE_GRAPH = BASE / "current" / "h3-api-prompt.json"
DEST = RESEARCH / "gemma4-31b-guarded-scene6-h3-2026-09-26"
VARIANTS = ("current", "without_composition")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> None:
    baseline = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
    trace = json.loads(SOURCE_TRACE.read_text(encoding="utf-8"))["translation_trace"]
    rows = [item for item in trace if item["field_id"] == "scene.5.shot.0.body.2"]
    if len(rows) != 1 or "後ろ足へ短く荷重" not in rows[0]["source"]:
        raise ValueError("Frozen Scene 6 composition translation not identified")
    supplement = rows[0]["restored"]
    reduced = copy.deepcopy(baseline)
    lines = reduced["shots"][5]["prompt"]
    positions = [index for index, line in enumerate(lines) if line.startswith("[Shot 1]")]
    if len(positions) != 1:
        raise ValueError("Scene 6 Shot 1 is not unique")
    old = lines[positions[0]]
    needle = f" {supplement} "
    if old.count(needle) != 1:
        raise ValueError("Translated composition is not uniquely present in Scene 6")
    lines[positions[0]] = old.replace(needle, " ", 1)
    if baseline["shots"][5]["prompt"][positions[0]] == lines[positions[0]]:
        raise ValueError("No prompt difference after removing composition")
    for variant, plan in zip(VARIANTS, (baseline, reduced)):
        target = DEST / variant
        plan_text = json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
        (target).mkdir(parents=True, exist_ok=True)
        (target / "plan.json").write_text(plan_text, encoding="utf-8")
        graph = json.loads(SOURCE_GRAPH.read_text(encoding="utf-8"))
        for node in ("24", "37", "48"):
            graph[node]["inputs"]["plan_json"] = plan_text
        graph["48"]["inputs"].update({"enable": True, "scene_start": 6,
                                       "scene_length": 1})
        run_name = f"guarded-composition-s6-{variant}-20260926"
        graph["24"]["inputs"]["run_name"] = run_name
        graph["21"]["inputs"]["filename"] = run_name
        _write(target / "h3-api-prompt.json", graph)
        _write(target / "h3-manifest.json", {
            "variant": variant, "run_name": run_name, "scene": 6,
            "seed": 42, "megapixels": 0.4,
            "source_plan": str(SOURCE_PLAN), "source_plan_sha256": _sha(SOURCE_PLAN),
            "source_trace": str(SOURCE_TRACE), "source_trace_sha256": _sha(SOURCE_TRACE),
            "plan_sha256": _sha(target / "plan.json"),
            "graph_sha256": _sha(target / "h3-api-prompt.json"),
        })
    changed = [index + 1 for index, (left, right) in enumerate(zip(
        baseline["shots"], reduced["shots"]
    )) if left != right]
    if changed != [6]:
        raise ValueError(f"Unexpected changed Scenes: {changed}")
    print("Prepared Scene 6 A/B: only Shot 1 composition sentence differs", flush=True)


if __name__ == "__main__":
    main()
