"""Build compact visual-spec variants for the sacred-tree and foxfire Scenes.

Only the local summary and Shot prose of Scenes 6 and 9 change. The saved
source Plan, seeds, Scene 5/8 guides, global prompt, and references stay fixed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
COMPACT_LINES = {
    6: {
        5: (
            "[reference generation] <Subject 1> stands on the approach path "
            "beside the sacred tree. She raises her hands and briefly closes "
            "her eyes as red leaves spiral upward around the tree."
        ),
        12: (
            "[Shot 1] The sacred tree sways and red leaves spiral above it "
            "while <Subject 1> raises her hands, briefly closes her eyes, and "
            "responds. Arc Shot with large amplitude at fast speed around her "
            "and the tree; blend in Roll Counterclockwise with small amplitude, "
            "then level the horizon. Show the tree, leaves, hands, and face together."
        ),
    },
    9: {
        5: (
            "[reference generation] Foxfire appears around <Subject 1> on the "
            "stone path. She raises her right hand and moves her left at chest height."
        ),
        12: (
            "[Shot 1] Foxfire appears before <Subject 1> as she raises her right "
            "hand and waves her left at chest height. Push In at fast speed; "
            "show the fire, both hands, and her singing face."
        ),
        13: (
            "[Shot 2] At 00:04.958, foxfire circles around her and red light "
            "moves with it. She lifts her right hand near her head and lowers "
            "her left toward her waist. Arc Shot with large amplitude at fast "
            "speed around her and the fire; blend in Roll Counterclockwise with "
            "small amplitude, then level the horizon. Keep the fire, hands, "
            "and face in view."
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
        expected = {5} | {
            index for index, line in enumerate(before) if line.startswith("[Shot ")
        }
        if set(replacements) != expected:
            raise AssertionError((scene_number, sorted(expected), sorted(replacements)))
        for index, text in replacements.items():
            prefix = "[reference generation]" if index == 5 else f"[Shot {index - 11}]"
            if not before[index].startswith(prefix):
                raise ValueError((scene_number, index, "unexpected source line"))
            after[index] = text
        changed_indices = [
            index for index, (left, right) in enumerate(zip(before, after, strict=True))
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
