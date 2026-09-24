"""Replace only the brief body-action clauses in saved Scene 9 H3 prompts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
REPLACEMENTS = (
    (
        "Raise the right hand slowly, and lightly wave the left hand at chest height.",
        "Shift weight left; raise the right hand, and sweep the left hand across the chest as the torso follows.",
        2,
    ),
    (
        "Raise the right hand to the head, and lower the left hand to the waist position.",
        "Shift onto the right foot; open the right arm upward and the left arm low, then settle.",
        1,
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256
    if args.output.exists():
        raise FileExistsError(args.output)
    original = json.loads(raw)
    changed = copy.deepcopy(original)
    prompts = changed["shots"][8]["prompt"]
    counts = []
    for before, after, expected in REPLACEMENTS:
        matches = sum(line.count(before) for line in prompts)
        assert matches == expected, (before, matches)
        counts.append(matches)
        prompts[:] = [line.replace(before, after) for line in prompts]
    assert len(changed["shots"]) == len(original["shots"])
    for index, (left, right) in enumerate(zip(original["shots"], changed["shots"], strict=True)):
        assert {key: value for key, value in left.items() if key != "prompt"} == {
            key: value for key, value in right.items() if key != "prompt"
        }
        if index != 8:
            assert left == right
    args.output.write_text(json.dumps(changed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_sha256": SOURCE_SHA256,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "replaced_clause_counts": counts,
        "scene9_prompt_chars_before": len(" ".join(original["shots"][8]["prompt"])),
        "scene9_prompt_chars_after": len(" ".join(prompts)),
    }, indent=2))


if __name__ == "__main__":
    main()
