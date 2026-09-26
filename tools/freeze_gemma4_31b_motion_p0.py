"""Freeze the archived 31B Scene-author calls against adopted EMD and Plan.

This is a research-only, CPU-only provenance check. It does not run inference.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.planner.scene_author import _split_terminal_state
from core.planner.template import parse_template_emd


SOURCE = ROOT / "docs/assets/research/gemma4-31b-full-2026-09-25"
SCENE5 = ROOT / "docs/assets/research/gemma4-31b-scene5-2026-09-25"
PHASES = ROOT / "docs/assets/research/gemma4-31b-pipeline-phases-2026-09-25"
OUTPUT = ROOT / "docs/assets/research/gemma4-31b-motion-pipeline-p0-2026-09-25/manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parsed_response(task: str, response: str) -> dict[int, str] | tuple[int, str] | None:
    if task == "event":
        lines = response.splitlines()
        if len(lines) != 1:
            return None
        fields = lines[0].split("\t", 2)
        if len(fields) != 3 or fields[:2] != ["EVENT", "1"]:
            return None
        prose, _ = _split_terminal_state(fields[2])
        matched = re.fullmatch(r"SHOT=([1-9][0-9]*)(?:｜|[ \t\u3000]+)(.+)", prose)
        return (int(matched[1]), matched[2]) if matched else None

    rows: dict[int, str] = {}
    for line in response.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3 or fields[0] != task.upper() or not fields[1].isdigit():
            return None
        number = int(fields[1])
        if number in rows:
            return None
        rows[number] = _split_terminal_state(fields[2])[0]
    return rows or None


def main() -> None:
    content = load(SOURCE / "planner-summary.json")["content"]
    template = parse_template_emd((SOURCE / "template.md").read_text(encoding="utf-8"))
    plan = load(SOURCE / "plan.json")
    if len(template.scenes) != len(plan["shots"]):
        raise ValueError("Template/Plan Scene count differs")

    expected: dict[tuple[str, int], object] = {}
    for task, field in (("performance", "actions"), ("camera", "cameras")):
        for scene, shot, prose in content[field]:
            expected.setdefault((task, scene), {})[shot] = prose
    events = {scene: (shot, prose) for scene, shot, prose in content["events"]}
    for scene in template.scenes:
        expected[("event", scene.scene_number)] = events.get(scene.scene_number)

    adopted: dict[tuple[str, int], dict] = {}
    rejected_counts = {task: 0 for task in ("event", "performance", "camera")}
    for task in rejected_counts:
        for path in sorted((SOURCE / "llm_calls").glob(f"scene-author-{task}-*.json")):
            call = load(path)
            request = call["request"]
            user = json.loads(request["messages"][-1]["content"])
            scene = int(user["scene_number"])
            actual = parsed_response(task, call["response"])
            wanted = expected[(task, scene)]
            matched = (
                actual is not None and actual[1] == "なし"
                if task == "event" and wanted is None and isinstance(actual, tuple)
                else actual == wanted
            )
            if not matched:
                rejected_counts[task] += 1
                continue
            key = (task, scene)
            if key in adopted:
                raise ValueError(f"ambiguous adopted response: {key}")
            adopted[key] = {
                "path": path.relative_to(ROOT).as_posix(),
                "file_sha256": digest(path),
                "request_sha256": hashlib.sha256(
                    request["messages"][-1]["content"].encode("utf-8")
                ).hexdigest(),
                "response_sha256": hashlib.sha256(
                    call["response"].encode("utf-8")
                ).hexdigest(),
            }

    if len(adopted) != len(template.scenes) * 3:
        missing = sorted(set(expected) - set(adopted))
        raise ValueError(f"missing adopted calls: {missing}")

    scenes: list[dict] = []
    for scene, plan_shot in zip(template.scenes, plan["shots"], strict=True):
        number = scene.scene_number
        if plan_shot["id"] != f"scene_{number:04d}":
            raise ValueError(f"Plan Scene ID differs: {number}")
        if plan_shot["length"] != scene.h3_length:
            raise ValueError(f"Plan H3 length differs: {number}")
        scenes.append({
            "scene": number,
            "start_ms": scene.start_ms,
            "end_ms": scene.end_ms,
            "continuation": scene.continuation,
            "h3_length": scene.h3_length,
            "shots": [
                {
                    "shot": index,
                    "start_ms": shot.start_ms,
                    "end_ms": scene.shots[index].start_ms if index < len(scene.shots) else scene.end_ms,
                    "lyrics": [lyric.text for lyric in shot.lyric_annotations],
                    "fixed_event": any(value.kind == "演出" for value in shot.directives),
                    "fixed_performance": any(value.kind == "演技" for value in shot.directives),
                    "fixed_camera": any(value.kind == "カメラ" for value in shot.directives),
                }
                for index, shot in enumerate(scene.shots, 1)
            ],
            "plan_id": plan_shot["id"],
            "plan_prompt_sha256": hashlib.sha256(
                json.dumps(plan_shot["prompt"], ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
            "adopted_calls": {
                task: adopted[(task, number)]
                for task in ("event", "performance", "camera")
            },
        })

    referenced = [
        SOURCE / name for name in (
            "input-manifest.json", "template.md", "planned.md", "plan.json", "planner-summary.json"
        )
    ] + [
        SCENE5 / name for name in (
            "source-manifest.json", "system-performance.txt", "scene5-gemma-user.txt",
            "scene5-gemma-performance.json", "gemma4-31b-body-full.emd.md",
        )
    ] + [
        PHASES / name for name in ("p0-manifest.json",)
    ] + [
        PHASES / "calls" / name for name in (
            "p5-scene2-grounded-performance.json",
            "p6-scene5-grounded-performance.json", "p6-scene6-grounded-performance.json",
        )
    ]
    payload = {
        "purpose": "31B motion pipeline P0 provenance freeze; no inference or rendering",
        "sources": {
            path.relative_to(ROOT).as_posix(): digest(path)
            for path in referenced
        },
        "call_counts": {
            "adopted": len(adopted),
            "rejected_or_superseded": rejected_counts,
        },
        "scenes": scenes,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"frozen {len(scenes)} Scenes and {len(adopted)} adopted calls: {OUTPUT}")


if __name__ == "__main__":
    main()
