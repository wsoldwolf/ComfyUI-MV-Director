"""Replace only Scene 3–4 body prose in the frozen audio-reference H3 Plan.

The baseline's spatial target, camera instructions, duration, seed, references,
and audio settings remain unchanged. This isolates the effect of Gemma 4 31B
performance text; it is not a full Gemma-driven Planner run.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
SCENE_TARGET = {
    3: "Target position: moss at the base of the large tree beside the path; ",
    4: "Target position: the flower and moss beside the path; ",
}
CAMERA_START = {
    (3, 1): "Push In at fast speed.",
    (3, 2): "Arc Shot with large amplitude at fast speed.",
    (4, 1): "Truck Right at fast speed.",
    (4, 2): "Arc Shot with large amplitude at fast speed.",
    (4, 3): "Tracking Shot at fast speed.",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--translations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source Plan hash does not match the frozen Qwen3 8B Plan")
    if args.output.exists():
        raise FileExistsError(args.output)
    original = json.loads(raw)
    changed = copy.deepcopy(original)
    data = json.loads(args.translations.read_text(encoding="utf-8"))
    translations = {
        (item["scene"], item["shot"]): item["english"].strip()
        for item in data["source"]
    }
    if set(translations) != set(CAMERA_START):
        raise ValueError("Gemma translation coverage is not Scene 3–4's five Shots")

    changed_lines: dict[int, list[int]] = {}
    for scene in (3, 4):
        before = original["shots"][scene - 1]["prompt"]
        after = changed["shots"][scene - 1]["prompt"]
        first = translations[(scene, 1)]
        if not before[5].startswith("[reference generation]"):
            raise ValueError(f"Scene {scene} summary moved")
        after[5] = f"[reference generation] {SCENE_TARGET[scene]}{first}"
        for shot in range(1, 3 if scene == 3 else 4):
            index = 11 + shot
            old = before[index]
            camera = CAMERA_START[(scene, shot)]
            if not old.startswith(f"[Shot {shot}]") or old.count(camera) != 1:
                raise ValueError(f"Scene {scene} Shot {shot} camera not found exactly once")
            suffix = old[old.index(camera):]
            timestamp = ""
            if shot > 1:
                prefix = old[:old.index(camera)]
                at = prefix.find("At 00:")
                if at >= 0:
                    timestamp = prefix[at:prefix.index(",", at) + 1] + " "
            after[index] = (
                f"[Shot {shot}] {timestamp}{SCENE_TARGET[scene]}"
                f"{translations[(scene, shot)]} {suffix}"
            )
        changed_lines[scene] = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        expected = [5] + list(range(12, 14 if scene == 3 else 15))
        if changed_lines[scene] != expected:
            raise AssertionError((scene, changed_lines[scene]))

    if original["defaults"] != changed["defaults"] or original["prompt_prefix"] != changed["prompt_prefix"]:
        raise AssertionError("Global H3 conditions changed")
    for scene, (left, right) in enumerate(zip(original["shots"], changed["shots"], strict=True), 1):
        if {k: v for k, v in left.items() if k != "prompt"} != {k: v for k, v in right.items() if k != "prompt"}:
            raise AssertionError(f"Non-prompt Scene {scene} value changed")
        if scene not in (3, 4) and left != right:
            raise AssertionError(f"Unselected Scene {scene} changed")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(changed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_sha256": SOURCE_SHA256,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "changed_lines": changed_lines,
    }, indent=2))


if __name__ == "__main__":
    main()
