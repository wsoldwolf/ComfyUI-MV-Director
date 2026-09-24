"""Append only body-performance prose to the saved English H3 Plan.

The existing English event and camera prose remains byte-for-byte unchanged.
This avoids 8B translation variance in the downstream H3 A/B. The resulting
Plan is an experiment artifact, not a replacement for a normal EMD compile.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


EXPECTED_SOURCE_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
BODY_ADDITIONS = {
    3: (
        "Before the touch, she transfers support to the left foot, turns her pelvis toward the moss, then lets her rib cage follow; her left arm opens low to balance the reach.",
        "After releasing the moss, she shifts support back to the right foot, lifts her rib cage, settles her left arm by her side, and raises her gaze from the moss toward the song.",
    ),
    4: (
        "Just before reaching for the flower, she transfers weight briefly from left foot to right, turns her rib cage toward it a beat later, and opens her left arm low for balance.",
        "Keeping her weight on the right foot, she returns her rib cage toward the camera while her left arm traces a low arc to her side; she holds the singing mouth visible for one beat.",
        "She shifts support back to the left foot, straightens her pelvis and rib cage at different speeds, settles both arms at different heights, and raises her gaze toward the next lyric.",
    ),
    9: (
        "Before lifting her arms, she transfers support to the left foot, lets her pelvis and rib cage turn toward the foxfire at different speeds, and follows the right hand with her gaze.",
        "As the foxfire passes her side, she transfers support to the right foot with one short knee accent; her pelvis leads, her rib cage follows, her right arm opens outward from overhead while her left arm opens in the opposite direction, then both arms settle as her gaze follows the moving flame.",
    ),
}
COMPACT_SCENE9_ADDITIONS = {
    9: (
        "She shifts weight to her left foot before raising her right hand; her torso follows the moving foxfire.",
        "As the foxfire circles her, she shifts to the right foot; her two arms trace opposite arcs and settle.",
    ),
}
CAMERA_STARTS = (
    "Push In at fast speed.",
    "Arc Shot with large amplitude at fast speed.",
    "Truck Right at fast speed.",
    "Tracking Shot at fast speed.",
)


def _insert_before_camera(line: str, addition: str) -> str:
    hits = [(line.find(" " + start), start) for start in CAMERA_STARTS]
    hits = [(position, start) for position, start in hits if position >= 0]
    assert len(hits) == 1, (len(hits), line[:180])
    position, _ = hits[0]
    return line[:position] + " " + addition + line[position:]


def build(
    source: Path,
    output: Path,
    additions_by_scene: dict[int, tuple[str, ...]] = BODY_ADDITIONS,
) -> dict[str, object]:
    payload = source.read_bytes()
    actual_sha = hashlib.sha256(payload).hexdigest()
    assert actual_sha == EXPECTED_SOURCE_SHA256, actual_sha
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing Plan: {output}")
    original = json.loads(payload)
    variant = copy.deepcopy(original)
    assert len(variant["shots"]) == 16
    changed: dict[int, int] = {}
    for scene_number, additions in additions_by_scene.items():
        scene = variant["shots"][scene_number - 1]
        prompt = scene["prompt"]
        ref_indices = [
            index for index, line in enumerate(prompt)
            if line.startswith("[reference generation] ")
        ]
        assert len(ref_indices) == 1, scene_number
        prompt[ref_indices[0]] += " " + additions[0]
        count = 1
        for shot_number, addition in enumerate(additions, start=1):
            prefix = f"[Shot {shot_number}]"
            indices = [
                index for index, line in enumerate(prompt)
                if line.startswith(prefix)
            ]
            assert len(indices) == 1, (scene_number, shot_number)
            index = indices[0]
            prompt[index] = _insert_before_camera(prompt[index], addition)
            count += 1
        changed[scene_number] = count

    assert original["defaults"] == variant["defaults"]
    assert original.get("prompt_prefix") == variant.get("prompt_prefix")
    for scene_number, (old_scene, new_scene) in enumerate(
        zip(original["shots"], variant["shots"], strict=True), start=1
    ):
        assert old_scene.keys() == new_scene.keys()
        assert {
            key: value for key, value in old_scene.items() if key != "prompt"
        } == {
            key: value for key, value in new_scene.items() if key != "prompt"
        }, scene_number
        differences = [
            (old, new)
            for old, new in zip(old_scene["prompt"], new_scene["prompt"], strict=True)
            if old != new
        ]
        assert len(differences) == changed.get(scene_number, 0), scene_number
        for old, new in differences:
            if old.startswith("[reference generation] "):
                assert new.startswith(old + " ")
            else:
                assert old.startswith("[Shot ")
                assert new.startswith(old.split(" ", 2)[0])
                assert any(new.endswith(old[old.index(start):]) for start in CAMERA_STARTS if start in old)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(variant, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_sha256": actual_sha,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "changed_prompt_lines_by_scene": changed,
        "source": str(source),
        "output": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compact-scene9", action="store_true")
    args = parser.parse_args()
    additions = COMPACT_SCENE9_ADDITIONS if args.compact_scene9 else BODY_ADDITIONS
    print(json.dumps(build(args.source, args.output, additions), indent=2))


if __name__ == "__main__":
    main()
