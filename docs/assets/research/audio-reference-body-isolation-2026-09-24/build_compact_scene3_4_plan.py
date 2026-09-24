"""Build a short visual-spec variant of the saved Scene 3–4 H3 Plan.

Only each Scene's summary and Shot-specific text are shortened. Identity,
environment, global prompt, timing, seeds, audio, and every other Scene stay
byte-for-byte equivalent after JSON parsing. This is an offline H3 experiment,
not a change to Planner or Compiler output.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
COMPACT_LINES = {
    3: {
        5: (
            "[reference generation] At the base of the large tree beside the path, "
            "<Subject 1> notices the moss, reaches toward it, and touches it once."
        ),
        12: (
            "[Shot 1] <Subject 1> touches the moss at the large tree's base with "
            "her fingertips. Push In at fast speed toward the moss and her hand; "
            "keep her face visible with them."
        ),
        13: (
            "[Shot 2] At 00:03.416, she releases the moss and reacts with her "
            "eyes and singing mouth. Arc Shot with large amplitude at fast speed "
            "around her and the tree; keep the moss, hand, and face in view."
        ),
    },
    4: {
        5: (
            "[reference generation] A flower appears beside the moss. "
            "<Subject 1> reaches toward it; the flower blooms and its petals scatter."
        ),
        12: (
            "[Shot 1] <Subject 1> reaches toward the flower beside the moss. "
            "Push In at fast speed; show the flower, her hand, and singing face together."
        ),
        13: (
            "[Shot 2] At 00:03.125, she lowers her hand as the flower blooms "
            "and petals scatter. Arc Shot with large amplitude at fast speed "
            "around her and the flower."
        ),
        14: (
            "[Shot 3] At 00:06.625, petals drift past her hand and face toward "
            "the path; she follows them with her eyes. Tracking Shot at fast speed "
            "with her and the petals."
        ),
    },
}


def build(source: Path, output: Path) -> dict[str, object]:
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != SOURCE_SHA256:
        raise ValueError(f"unexpected source Plan SHA256: {source_hash}")
    if output.exists():
        raise FileExistsError(output)
    original = json.loads(raw)
    changed = copy.deepcopy(original)
    summary: dict[int, dict[str, object]] = {}

    for scene_number, replacements in COMPACT_LINES.items():
        before = original["shots"][scene_number - 1]["prompt"]
        after = changed["shots"][scene_number - 1]["prompt"]
        expected = {5, 12, 13} if scene_number == 3 else {5, 12, 13, 14}
        if set(replacements) != expected:
            raise AssertionError((scene_number, sorted(replacements)))
        for index, text in replacements.items():
            if index >= len(after) or not before[index].startswith(
                "[reference generation]" if index == 5 else f"[Shot {index - 11}]"
            ):
                raise ValueError((scene_number, index, "unexpected source line"))
            after[index] = text
        changed_indices = [
            index
            for index, (left, right) in enumerate(zip(before, after, strict=True))
            if left != right
        ]
        if set(changed_indices) != expected:
            raise AssertionError((scene_number, changed_indices))
        summary[scene_number] = {
            "changed_prompt_lines": changed_indices,
            "before_chars": len(" ".join(before)),
            "after_chars": len(" ".join(after)),
        }

    if original["defaults"] != changed["defaults"]:
        raise AssertionError("defaults changed")
    if original.get("prompt_prefix") != changed.get("prompt_prefix"):
        raise AssertionError("global prompt changed")
    for number, (before, after) in enumerate(
        zip(original["shots"], changed["shots"], strict=True), start=1
    ):
        if {key: value for key, value in before.items() if key != "prompt"} != {
            key: value for key, value in after.items() if key != "prompt"
        }:
            raise AssertionError((number, "non-prompt field changed"))
        if number not in COMPACT_LINES and before != after:
            raise AssertionError((number, "unselected Scene changed"))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(changed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "source_sha256": SOURCE_SHA256,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "scenes": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
