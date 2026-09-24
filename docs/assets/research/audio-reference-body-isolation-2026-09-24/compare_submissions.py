"""List changed leaf paths between two submitted ComfyUI prompt graphs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def differences(left: object, right: object, path: str = "") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return [path + "{keys}"]
        return [
            change
            for key in left
            for change in differences(left[key], right[key], f"{path}.{key}")
        ]
    if isinstance(left, list):
        if len(left) != len(right):
            return [path + "{length}"]
        return [
            change
            for index, (a, b) in enumerate(zip(left, right, strict=True))
            for change in differences(a, b, f"{path}[{index}]")
        ]
    return [path] if left != right else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("variant", type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    variant = json.loads(args.variant.read_text(encoding="utf-8"))
    assert baseline["scene"] == variant["scene"] == 9
    assert baseline["scene_length"] == variant["scene_length"] == 1
    changed = differences(baseline["prompt"], variant["prompt"], "prompt")
    print(json.dumps({"changed_prompt_paths": changed}, indent=2))


if __name__ == "__main__":
    main()
