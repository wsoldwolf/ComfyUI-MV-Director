"""A/B artifact: re-render saved finite Camera records, leaving all other Plan text fixed.

This reverse lookup accepts only the exact detailed string emitted by the
Planner's finite Camera serializer. It is for a matched H3 experiment, not
part of the production Planner/Compiler pipeline.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.planner.engine import (
    _CAMERA_COVERAGE_TEXT,
    _CAMERA_MOTION_TYPES,
    _CAMERA_PATH_TEXT,
    _CAMERA_SCALE_TEXT,
    _CAMERA_VIEW_TEXT,
    _CameraPlan,
    _render_camera_plan,
)


SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
TARGET_SCENES = (6, 9)
_MOTION_RE = re.compile(
    r"(?:"
    + "|".join(re.escape(value) for value in sorted(_CAMERA_MOTION_TYPES, key=len, reverse=True))
    + r")(?: with (?:small|large) amplitude)?(?: at (?:slow|fast) speed)?$"
)
_DETAILED_RE = re.compile(
    r"(?P<motion>[^.]+)\. Start with (?P<start_scale>.+?) from "
    r"(?P<start_view>.+?); end with (?P<end_scale>.+?) from "
    r"(?P<end_view>.+?)\. (?P<path>.+?)\. (?P<coverage>.+?)\."
)


def _reverse(values: dict[str, str], text: str) -> str:
    matches = [key for key, value in values.items() if value == text]
    if len(matches) != 1:
        raise ValueError(f"Camera finite field is not uniquely recognized: {text!r}")
    return matches[0]


def _compact_camera_line(line: str) -> str:
    if not line.startswith("[Shot ") or ". Start with " not in line:
        raise ValueError(f"not a finite Camera Shot line: {line[:80]!r}")
    motion_prefix = line.split(". Start with ", 1)[0]
    motion = _MOTION_RE.search(motion_prefix)
    if motion is None:
        raise ValueError(f"finite Camera motion not found: {line[:100]!r}")
    detailed = line[motion.start():]
    fields = _DETAILED_RE.fullmatch(detailed)
    if fields is None:
        raise ValueError(f"finite Camera serializer did not match: {detailed!r}")
    plan = _CameraPlan(
        motion=fields["motion"],
        start_scale=_reverse(_CAMERA_SCALE_TEXT, fields["start_scale"]),
        end_scale=_reverse(_CAMERA_SCALE_TEXT, fields["end_scale"]),
        start_view=_reverse(_CAMERA_VIEW_TEXT, fields["start_view"]),
        end_view=_reverse(_CAMERA_VIEW_TEXT, fields["end_view"]),
        path=_reverse(_CAMERA_PATH_TEXT, fields["path"]),
        coverage=_reverse(_CAMERA_COVERAGE_TEXT, fields["coverage"]),
    )
    if _render_camera_plan(plan) != detailed:
        raise AssertionError("detailed Camera did not round-trip")
    return line[:motion.start()] + _render_camera_plan(plan, style="compact")


def build(source: Path, output: Path) -> dict[int, dict[str, object]]:
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("unexpected source Plan SHA256")
    if output.exists():
        raise FileExistsError(output)
    original = json.loads(raw)
    changed = copy.deepcopy(original)
    report: dict[int, dict[str, object]] = {}
    for scene_number in TARGET_SCENES:
        before = original["shots"][scene_number - 1]["prompt"]
        after = changed["shots"][scene_number - 1]["prompt"]
        changed_indices = []
        for index, line in enumerate(before):
            if line.startswith("[Shot "):
                after[index] = _compact_camera_line(line)
                changed_indices.append(index)
        if not changed_indices:
            raise AssertionError(f"Scene {scene_number} has no finite Camera")
        report[scene_number] = {
            "changed_prompt_lines": changed_indices,
            "before_chars": sum(len(before[index]) for index in changed_indices),
            "after_chars": sum(len(after[index]) for index in changed_indices),
        }
    for index, (before, after) in enumerate(zip(original["shots"], changed["shots"], strict=True), start=1):
        if index not in TARGET_SCENES and before != after:
            raise AssertionError(f"Scene {index} changed unexpectedly")
        if index in TARGET_SCENES:
            fixed = copy.deepcopy(after)
            fixed["prompt"] = before["prompt"]
            if fixed != before:
                raise AssertionError(f"Scene {index} has a non-prompt change")
    output.write_text(json.dumps(changed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), ensure_ascii=False, indent=2))
