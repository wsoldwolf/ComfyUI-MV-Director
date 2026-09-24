"""Replace body-action clauses in the saved moss/flower H3 Plan only.

The lyric object, location, external event, camera, scene structure, and every
other scene are retained. This is an experimental Plan, not an EMD compile.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
REPLACEMENTS = {
    3: (
        (
            "slowly raising the right hand and stroking the moss with the fingertips",
            "shifting support to her left foot and turning her torso as she raises her right hand and strokes the moss with her fingertips",
            2,
        ),
        (
            "lowering the right hand and stroking the moss with the fingertips, then letting go of the hand",
            "shifting support to her right foot as she lowers the right hand, strokes the moss with her fingertips, then lets go",
            1,
        ),
    ),
    4: (
        (
            "slowly raising the right hand to reach out to the flower. Add the action of gently shaking the flower with the fingertips.",
            "shifting support to her left foot as she reaches for the flower with her right hand and gently shakes it with her fingertips; her left arm opens low.",
            2,
        ),
        (
            "Lower the right hand and let the flower bloom. Add the action of slowly lowering the hand, moving the flower naturally as if it were scattering.",
            "Shift support to the right foot as she lowers her right hand and lets the flower bloom; her left arm sweeps low while the flower scatters.",
            1,
        ),
        (
            "From the posture of lowering the right hand, watch as the flowers scatter. Observe quietly how the flowers fall onto the moss.",
            "As she lowers her right hand, shift support to both feet and lift her torso; her eyes follow the scattering flowers as they fall onto the moss, and both arms settle.",
            1,
        ),
    ),
}


def build(source: Path, output: Path) -> dict[str, object]:
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256
    if output.exists():
        raise FileExistsError(output)
    original = json.loads(raw)
    changed = copy.deepcopy(original)
    result: dict[int, dict[str, object]] = {}
    for scene_number, replacements in REPLACEMENTS.items():
        old = original["shots"][scene_number - 1]["prompt"]
        prompt = changed["shots"][scene_number - 1]["prompt"]
        for before, after, expected_count in replacements:
            count = sum(line.count(before) for line in prompt)
            assert count == expected_count, (scene_number, before, count)
            prompt[:] = [line.replace(before, after) for line in prompt]
        changed_lines = [
            index for index, (left, right) in enumerate(zip(old, prompt, strict=True))
            if left != right
        ]
        assert len(changed_lines) == 1 + len(replacements), (scene_number, changed_lines)
        result[scene_number] = {
            "changed_prompt_lines": changed_lines,
            "before_chars": len(" ".join(old)),
            "after_chars": len(" ".join(prompt)),
        }

    assert original["defaults"] == changed["defaults"]
    assert original.get("prompt_prefix") == changed.get("prompt_prefix")
    for number, (old, new) in enumerate(zip(original["shots"], changed["shots"], strict=True), start=1):
        assert {
            key: value for key, value in old.items() if key != "prompt"
        } == {
            key: value for key, value in new.items() if key != "prompt"
        }, number
        if number not in REPLACEMENTS:
            assert old == new, number

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(changed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_sha256": SOURCE_SHA256,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "scenes": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
