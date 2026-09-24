"""Build matched P1 summary-only and summary+Action H3 Plan probes.

This is a research-only ablation against a hash-locked saved Plan. The
original detailed finite Camera text, all other Scenes, seeds, and metadata
are preserved. It does not modify the production Planner or Compiler.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from build_compact_scene6_9_plan import COMPACT_LINES, SOURCE_SHA256


TARGETS = {6: {5, 12}, 9: {5, 12, 13}}
MOTION_MARKERS = {(6, 12): " Arc Shot with ",
                  (9, 12): " Push In at ",
                  (9, 13): " Arc Shot with "}


def _camera_start(line: str, marker: str) -> int:
    if line.count(marker) != 1:
        raise ValueError(f"Camera boundary is not unique: {marker!r}")
    return line.index(marker) + 1


def build(source: Path, output_dir: Path) -> dict[str, object]:
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != SOURCE_SHA256:
        raise ValueError(f"unexpected source Plan SHA256: {source_hash}")
    original = json.loads(raw)
    variants: dict[str, dict] = {}
    report: dict[str, object] = {"source_sha256": source_hash, "variants": {}}
    for name, change_actions in (("summary-only", False),
                                 ("summary-action", True)):
        changed = copy.deepcopy(original)
        changed_lines: dict[int, list[int]] = {}
        for scene_number, expected_indices in TARGETS.items():
            before = original["shots"][scene_number - 1]["prompt"]
            after = changed["shots"][scene_number - 1]["prompt"]
            manual = COMPACT_LINES[scene_number]
            if set(manual) != expected_indices:
                raise AssertionError("manual Plan line set changed")
            after[5] = manual[5]
            changed_lines[scene_number] = [5]
            if change_actions:
                for index in sorted(expected_indices - {5}):
                    marker = MOTION_MARKERS[(scene_number, index)]
                    original_camera_start = _camera_start(before[index], marker)
                    manual_camera_start = _camera_start(manual[index], marker)
                    if not before[index].startswith(f"[Shot {index - 11}]"):
                        raise AssertionError("unexpected source Shot order")
                    after[index] = (
                        manual[index][:manual_camera_start]
                        + before[index][original_camera_start:]
                    )
                    if after[index][manual_camera_start:] != before[index][original_camera_start:]:
                        raise AssertionError("detailed Camera changed")
                    changed_lines[scene_number].append(index)
        for scene_number, (before_scene, after_scene) in enumerate(
            zip(original["shots"], changed["shots"], strict=True), start=1
        ):
            if set(before_scene) != set(after_scene):
                raise AssertionError("Scene keys changed")
            if {key: value for key, value in before_scene.items() if key != "prompt"} != {
                key: value for key, value in after_scene.items() if key != "prompt"
            }:
                raise AssertionError("non-prompt Scene field changed")
            if len(before_scene["prompt"]) != len(after_scene["prompt"]):
                raise AssertionError("prompt line count changed")
            actual = [index for index, (left, right) in enumerate(
                zip(before_scene["prompt"], after_scene["prompt"], strict=True)
            ) if left != right]
            if actual != changed_lines.get(scene_number, []):
                raise AssertionError((name, scene_number, actual))
        fixed = copy.deepcopy(changed)
        fixed["shots"] = original["shots"]
        if fixed != original:
            raise AssertionError("top-level Plan field changed")
        variants[name] = changed
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"p1-{name}-scene6-9-plan.json"
        if output.exists():
            raise FileExistsError(output)
        output.write_text(
            json.dumps(changed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["variants"][name] = {
            "path": str(output),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "changed_prompt_lines": changed_lines,
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output_dir), ensure_ascii=False, indent=2))
